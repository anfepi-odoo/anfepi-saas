# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """
    Fix DIOT tax_tag_invert durante upgrade del módulo en Odoo 18.

    Este script corre durante el upgrade del módulo (cuando ya estaba instalado).
    El post_init_hook cubre el caso de instalación nueva.
    """
    cr.execute("""
        UPDATE account_move_line
        SET tax_tag_invert = FALSE
        WHERE tax_tag_invert = TRUE
          AND EXISTS (
            SELECT 1
            FROM account_account_tag_account_move_line_rel r
            JOIN account_account_tag aat ON aat.id = r.account_account_tag_id
            WHERE r.account_move_line_id = account_move_line.id
              AND aat.name::text LIKE '%DIOT%'
          )
    """)
    _logger.info(
        'anfepi_account_fix migration 18.0.1.0.0: '
        'DIOT tax_tag_invert fix aplicado (%d filas)',
        cr.rowcount,
    )
