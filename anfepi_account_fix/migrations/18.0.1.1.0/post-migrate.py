# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)

ACCOUNT_CODE = '113.02.01'
ACCOUNT_NAME = 'ISR A Favor'


def migrate(cr, version):
    """
    Renombra la cuenta 113.02.01 a 'ISR A Favor' en caso de que exista
    con un nombre incorrecto (ej. 'ISR Retenido') por haber sido creada
    originalmente por la localización mexicana de Odoo.
    """
    cr.execute("""
        UPDATE account_account
        SET name = %s
        WHERE code = %s
          AND name != %s
    """, (ACCOUNT_NAME, ACCOUNT_CODE, ACCOUNT_NAME))
    if cr.rowcount:
        _logger.warning(
            'anfepi_account_fix migration 18.0.1.1.0: '
            'Cuenta %s renombrada a "%s" (%d fila(s) actualizadas).',
            ACCOUNT_CODE, ACCOUNT_NAME, cr.rowcount,
        )
    else:
        _logger.info(
            'anfepi_account_fix migration 18.0.1.1.0: '
            'Cuenta %s ya tenía el nombre correcto, sin cambios.',
            ACCOUNT_CODE,
        )
