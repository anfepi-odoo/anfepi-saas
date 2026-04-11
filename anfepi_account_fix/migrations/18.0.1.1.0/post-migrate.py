# -*- coding: utf-8 -*-
import logging
from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

ACCOUNT_CODE = '113.02.01'
ACCOUNT_NAME = 'ISR A Favor'


def migrate(cr, version):
    """
    Renombra la cuenta 113.02.01 a 'ISR A Favor' usando el ORM.
    En Odoo 18 el campo code es company_dependent (JSONB) — SQL directo no funciona.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    accounts = env['account.account'].search([('code', '=', ACCOUNT_CODE)])
    for account in accounts:
        if account.name != ACCOUNT_NAME:
            _logger.info(
                'anfepi_account_fix 18.0.1.1.0: cuenta %s en compañía "%s" '
                'tenía nombre "%s" — renombrando a "%s".',
                ACCOUNT_CODE, account.company_ids[:1].name,
                account.name, ACCOUNT_NAME,
            )
            account.write({'name': ACCOUNT_NAME})
