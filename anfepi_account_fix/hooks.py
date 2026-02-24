# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)

ACCOUNT_CODE = '113.02.01'
ACCOUNT_NAME = 'ISR A Favor'
ACCOUNT_TYPE = 'asset_current'


def post_init_hook(cr, registry):
    """
    Crea la cuenta contable 113.02.01 ISR A Favor para cada compañía
    que use la localización mexicana y no tenga ya definida esa cuenta.
    """
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})

    # Buscar compañías que usen la localización mexicana
    mx_chart = env.ref('l10n_mx.mx_coa', raise_if_not_found=False)

    if mx_chart:
        # Compañías que usan el plan de cuentas mexicano
        companies = env['res.company'].search([
            ('chart_template_id', '=', mx_chart.id)
        ])
    else:
        # Fallback: todas las compañías activas
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
        _create_isr_account(env, company)


def _create_isr_account(env, company):
    """Crea la cuenta 113.02.01 ISR A Favor para la compañía indicada."""
    # Verificar si la cuenta ya existe
    existing = env['account.account'].search([
        ('code', '=', ACCOUNT_CODE),
        ('company_id', '=', company.id),
    ], limit=1)

    if existing:
        _logger.info(
            'anfepi_account_fix: La cuenta %s ya existe para la compañía "%s" (id=%d). '
            'No se realizaron cambios.',
            ACCOUNT_CODE, company.name, company.id
        )
        return

    # Buscar el grupo contable al que pertenece la cuenta
    # En l10n_mx la cuenta 113.02.01 cae dentro del grupo 113
    group = env['account.group'].search([
        ('code_prefix_start', '<=', ACCOUNT_CODE),
        ('code_prefix_end', '>=', ACCOUNT_CODE),
        ('company_id', '=', company.id),
    ], limit=1, order='code_prefix_start desc')

    # Si no hay grupo coincidente, intentar buscar el grupo padre 113
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
        _logger.info(
            'anfepi_account_fix: Usando grupo contable "%s" (id=%d) para la cuenta %s.',
            group.name, group.id, ACCOUNT_CODE
        )
    else:
        _logger.warning(
            'anfepi_account_fix: No se encontró un grupo contable para %s '
            'en la compañía "%s". La cuenta se creará sin grupo.',
            ACCOUNT_CODE, company.name
        )

    new_account = env['account.account'].create(vals)
    _logger.info(
        'anfepi_account_fix: Cuenta "%s %s" creada exitosamente (id=%d) '
        'para la compañía "%s".',
        ACCOUNT_CODE, ACCOUNT_NAME, new_account.id, company.name
    )
