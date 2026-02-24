# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)

ACCOUNT_CODE = '113.02.01'
ACCOUNT_NAME = 'ISR A Favor'
ACCOUNT_TYPE = 'asset_current'


def post_init_hook(cr, registry):
    """
    1. Crea la cuenta contable 113.02.01 ISR A Favor para cada compañía
       que use la localización mexicana y no la tenga definida.
    2. Reasigna las líneas de asiento (account.move.line) que quedaron
       huérfanas (account_id apuntando a un registro eliminado) a la
       cuenta recién creada.
    3. Registra en el log los asientos que aún queden descuadrados para
       revisión manual.
    """
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})

    # Buscar compañías que usen la localización mexicana
    mx_chart = env.ref('l10n_mx.mx_coa', raise_if_not_found=False)

    if mx_chart:
        companies = env['res.company'].search([
            ('chart_template_id', '=', mx_chart.id)
        ])
    else:
        companies = env['res.company'].search([])
        _logger.warning(
            'anfepi_account_fix: No se encontró el template l10n_mx.mx_coa. '
            'Se intentará crear la cuenta en todas las compañías activas.'
        )

    if not companies:
        _logger.warning(
            'anfepi_account_fix: No se encontraron compañías con localización '
            'mexicana. Verificar configuración.'
        )
        return

    for company in companies:
        account = _create_or_get_isr_account(env, company)
        if account:
            _fix_orphan_move_lines(cr, env, account, company)
            _fix_unbalanced_moves(cr, env, account, company)


# ---------------------------------------------------------------------------
# Creación de la cuenta
# ---------------------------------------------------------------------------

def _create_or_get_isr_account(env, company):
    """
    Devuelve la cuenta 113.02.01, creándola si no existe todavía.
    Retorna el recordset account.account.
    """
    existing = env['account.account'].search([
        ('code', '=', ACCOUNT_CODE),
        ('company_id', '=', company.id),
    ], limit=1)

    if existing:
        _logger.info(
            'anfepi_account_fix: La cuenta %s ya existe para la compañía '
            '"%s" (id=%d). Se usará para reparar líneas huérfanas.',
            ACCOUNT_CODE, company.name, existing.id
        )
        return existing

    # Buscar el grupo contable más específico para 113.02.01
    group = env['account.group'].search([
        ('code_prefix_start', '<=', ACCOUNT_CODE),
        ('code_prefix_end', '>=', ACCOUNT_CODE),
        ('company_id', '=', company.id),
    ], limit=1, order='code_prefix_start desc')

    if not group:
        group = env['account.group'].search([
            ('code_prefix_start', 'like', '113'),
            ('company_id', '=', company.id),
        ], limit=1)

    vals = {
        'code': ACCOUNT_CODE,
        'name': ACCOUNT_NAME,
        'account_type': ACCOUNT_TYPE,
        'company_id': company.id,
        'reconcile': False,
    }
    if group:
        vals['group_id'] = group.id

    new_account = env['account.account'].create(vals)
    _logger.info(
        'anfepi_account_fix: Cuenta "%s %s" creada (id=%d) '
        'para la compañía "%s".',
        ACCOUNT_CODE, ACCOUNT_NAME, new_account.id, company.name
    )
    return new_account


# ---------------------------------------------------------------------------
# Reparación de líneas huérfanas
# ---------------------------------------------------------------------------

def _fix_orphan_move_lines(cr, env, account, company):
    """
    Busca líneas de asiento (account.move.line) cuyo account_id ya no
    existe en account_account y las reasigna a la cuenta ISR A Favor.

    Odoo 16 tiene una constraint PostgreSQL que exige:
      display_type NOT IN ('line_section','line_note')
      OR (account_id IS NULL AND debit=0 AND credit=0 AND amount_currency=0)

    Por eso se filtra siempre por:
      - COALESCE(display_type,'') NOT IN ('line_section','line_note')
      - (debit != 0 OR credit != 0 OR amount_currency != 0)
    para tocar sólo líneas contables con movimiento real.
    """
    ACCOUNTING_FILTER = """
        COALESCE(display_type, '') NOT IN ('line_section', 'line_note')
        AND (debit != 0 OR credit != 0 OR amount_currency != 0)
    """

    # 1. Líneas contables con account_id = NULL (FK quedó vacía al borrar la cuenta)
    cr.execute("""
        SELECT COUNT(*)
        FROM account_move_line
        WHERE account_id IS NULL
          AND company_id = %s
          AND """ + ACCOUNTING_FILTER, (company.id,))
    null_count = cr.fetchone()[0]

    if null_count:
        cr.execute("""
            UPDATE account_move_line
            SET account_id = %s
            WHERE account_id IS NULL
              AND company_id = %s
              AND """ + ACCOUNTING_FILTER, (account.id, company.id))
        _logger.warning(
            'anfepi_account_fix: %d línea(s) con account_id NULL reasignada(s) '
            'a la cuenta %s "%s" en la compañía "%s". '
            'REVISAR los asientos afectados para confirmar que el mapeo es correcto.',
            null_count, ACCOUNT_CODE, ACCOUNT_NAME, company.name
        )

    # 2. Líneas contables con account_id apuntando a un id que ya no existe
    cr.execute("""
        SELECT COUNT(*)
        FROM account_move_line aml
        WHERE aml.company_id = %s
          AND aml.account_id IS NOT NULL
          AND COALESCE(aml.display_type, '') NOT IN ('line_section', 'line_note')
          AND NOT EXISTS (
              SELECT 1 FROM account_account aa WHERE aa.id = aml.account_id
          )
    """, (company.id,))
    dangling_count = cr.fetchone()[0]

    if dangling_count:
        cr.execute("""
            UPDATE account_move_line aml
            SET account_id = %s
            WHERE aml.company_id = %s
              AND aml.account_id IS NOT NULL
              AND COALESCE(aml.display_type, '') NOT IN ('line_section', 'line_note')
              AND NOT EXISTS (
                  SELECT 1 FROM account_account aa WHERE aa.id = aml.account_id
              )
        """, (account.id, company.id))
        _logger.warning(
            'anfepi_account_fix: %d línea(s) con account_id huérfano reasignada(s) '
            'a la cuenta %s "%s" en la compañía "%s". '
            'REVISAR los asientos afectados para confirmar que el mapeo es correcto.',
            dangling_count, ACCOUNT_CODE, ACCOUNT_NAME, company.name
        )

    if not null_count and not dangling_count:
        _logger.info(
            'anfepi_account_fix: No se encontraron líneas huérfanas '
            'en la compañía "%s".',
            company.name
        )


# ---------------------------------------------------------------------------
# Reparación e inserción de líneas faltantes en asientos descuadrados
# ---------------------------------------------------------------------------

def _fix_unbalanced_moves(cr, env, account, company):
    """
    Detecta asientos registrados (state=posted) cuyos débitos ≠ créditos.
    Para cada uno inserta una línea compensatoria en la cuenta 113.02.01
    ISR A Favor directamente vía SQL (sin pasar por el ORM ni el check de
    balance que bloquearía la operación).

    La diferencia puede ser:
      diff > 0  → suma de débitos supera créditos → falta línea de CRÉDITO
      diff < 0  → suma de créditos supera débitos → falta línea de DÉBITO
    """
    cr.execute("""
        SELECT
            am.id          AS move_id,
            am.name        AS move_name,
            am.ref         AS move_ref,
            am.date        AS move_date,
            am.journal_id  AS journal_id,
            rc.currency_id AS currency_id,
            ROUND(SUM(aml.debit) - SUM(aml.credit), 2) AS diff
        FROM account_move am
        JOIN account_move_line aml ON aml.move_id = am.id
        JOIN res_company rc ON rc.id = am.company_id
        WHERE am.state = 'posted'
          AND am.company_id = %s
        GROUP BY am.id, am.name, am.ref, am.date, am.journal_id, rc.currency_id
        HAVING ROUND(ABS(SUM(aml.debit) - SUM(aml.credit)), 2) > 0.01
        ORDER BY am.name
    """, (company.id,))

    rows = cr.fetchall()
    if not rows:
        _logger.info(
            'anfepi_account_fix: Todos los asientos registrados están '
            'cuadrados en la compañía "%s".', company.name
        )
        return

    fixed = 0
    for move_id, move_name, move_ref, move_date, journal_id, currency_id, diff in rows:
        # diff = total_debit - total_credit
        # Si diff < 0 → faltan débitos → insertamos línea con debit = abs(diff)
        # Si diff > 0 → faltan créditos → insertamos línea con credit = diff
        abs_diff = abs(diff)
        debit_val  = abs_diff if diff < 0 else 0.0
        credit_val = diff     if diff > 0 else 0.0
        balance_val = round(debit_val - credit_val, 2)

        cr.execute("""
            INSERT INTO account_move_line (
                move_id, company_id, account_id, journal_id,
                date, name,
                debit, credit, balance,
                amount_currency, currency_id,
                parent_state, sequence,
                display_type
            ) VALUES (
                %s, %s, %s, %s,
                %s, %s,
                %s, %s, %s,
                %s, %s,
                'posted', 999,
                'product'
            )
        """, (
            move_id, company.id, account.id, journal_id,
            move_date,
            'ISR A Favor (restaurado por anfepi_account_fix)',
            debit_val, credit_val, balance_val,
            balance_val, currency_id,
        ))

        _logger.warning(
            'anfepi_account_fix: Asiento "%s" (id=%d, ref=%s) estaba '
            'descuadrado (diferencia %.2f MXN). Se insertó línea '
            'compensatoria en cuenta %s "%s" '
            '(débito=%.2f, crédito=%.2f).',
            move_name, move_id, move_ref or '', diff,
            ACCOUNT_CODE, ACCOUNT_NAME,
            debit_val, credit_val
        )
        fixed += 1

    _logger.warning(
        'anfepi_account_fix: %d asiento(s) reparado(s) en la compañía "%s". '
        'REVISAR que los importes y fechas sean correctos.',
        fixed, company.name
    )
