# -*- coding: utf-8 -*-
import logging
from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

ACCOUNT_CODE = '113.02.01'
ACCOUNT_NAME = 'ISR A Favor'


def migrate(cr, version):
    """
    Renombra la cuenta 113.02.01 a 'ISR A Favor' usando el ORM para que
    el campo name (traducible/JSONB en Odoo 18) se actualice correctamente.
    El SQL directo no funciona en v18 porque name se almacena como JSONB.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    accounts = env['account.account'].search([('code', '=', ACCOUNT_CODE)])
    fixed = 0
    for account in accounts:
        if account.name != ACCOUNT_NAME:
            _logger.info(
                'anfepi_account_fix 18.0.1.2.0: cuenta %s en compañía "%s" '
                'tenía nombre "%s" — renombrando a "%s".',
                ACCOUNT_CODE, account.company_ids[:1].name,
                account.name, ACCOUNT_NAME,
            )
            account.write({'name': ACCOUNT_NAME})
            fixed += 1
    if fixed:
        _logger.info(
            'anfepi_account_fix 18.0.1.2.0: %d cuenta(s) renombradas a "%s".',
            fixed, ACCOUNT_NAME,
        )
    else:
        _logger.info(
            'anfepi_account_fix 18.0.1.2.0: cuenta %s ya tiene el nombre '
            'correcto en todas las compañías.',
            ACCOUNT_CODE,
        )
