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
            _report_unbalanced_moves(cr, env, account, company)


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

    Estas líneas quedan cuando se elimina un registro de account_account
    sin eliminar en cascada las move.lines (dependiendo del motor de BD
    y la versión de Odoo, la FK puede quedar como NULL o con valor inválido).
    """
    # 1. Líneas con account_id = NULL (el registro fue eliminado y la FK
    #    quedó en NULL porque la columna lo permite).
    cr.execute("""
        SELECT COUNT(*)
        FROM account_move_line
        WHERE account_id IS NULL
          AND company_id = %s
    """, (company.id,))
    null_count = cr.fetchone()[0]

    if null_count:
        cr.execute("""
            UPDATE account_move_line
            SET account_id = %s
            WHERE account_id IS NULL
              AND company_id = %s
        """, (account.id, company.id))
        _logger.warning(
            'anfepi_account_fix: %d línea(s) con account_id NULL reasignada(s) '
            'a la cuenta %s "%s" en la compañía "%s". '
            'REVISAR los asientos afectados para confirmar que el mapeo es correcto.',
            null_count, ACCOUNT_CODE, ACCOUNT_NAME, company.name
        )

    # 2. Líneas con account_id apuntando a un id que ya no existe
    #    (FK sin constraint de BD o constraint deferida).
    cr.execute("""
        SELECT COUNT(*)
        FROM account_move_line aml
        WHERE aml.company_id = %s
          AND aml.account_id IS NOT NULL
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
# Reporte de asientos descuadrados
# ---------------------------------------------------------------------------

def _report_unbalanced_moves(cr, env, account, company):
    """
    Identifica asientos registrados (state=posted) que aún estén
    descuadrados (suma débitos ≠ suma créditos) y los registra en el log
    para revisión manual posterior.
    """
    cr.execute("""
        SELECT
            am.name,
            am.id,
            am.ref,
            ROUND(SUM(aml.debit) - SUM(aml.credit), 2) AS diff
        FROM account_move am
        JOIN account_move_line aml ON aml.move_id = am.id
        WHERE am.state = 'posted'
          AND am.company_id = %s
        GROUP BY am.id, am.name, am.ref
        HAVING ROUND(ABS(SUM(aml.debit) - SUM(aml.credit)), 2) > 0.01
        ORDER BY am.name
    """, (company.id,))

    rows = cr.fetchall()
    if rows:
        _logger.error(
            'anfepi_account_fix: Los siguientes asientos registrados siguen '
            'DESCUADRADOS en la compañía "%s" y requieren corrección manual:',
            company.name
        )
        for name, move_id, ref, diff in rows:
            _logger.error(
                '  → %s (id=%d, ref=%s) | diferencia: %.2f MXN',
                name, move_id, ref or '', diff
            )
    else:
        _logger.info(
            'anfepi_account_fix: Todos los asientos registrados están '
            'cuadrados en la compañía "%s".', company.name
        )
