# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """
    Pre-migración para el upgrade a Odoo 19.

    Alinea tax_tag_invert con move_type en líneas con tags DIOT,
    de forma que el check pre-remove-tax-tag-invert.py de Odoo 19 pase.

    Regla: tax_tag_invert debe ser TRUE solo en facturas de crédito
    (in_refund / out_refund) y FALSE en todas las demás.

    Este fix es IDEMPOTENTE: si ya se ejecutó diot_upgrade_fix.sql
    en producción, el UPDATE no modifica nada (0 rows). Si por alguna
    razón el staging viene con datos incorrectos, los corrige aquí.
    """
    cr.execute("""
        UPDATE account_move_line aml
        SET tax_tag_invert = (am.move_type IN ('in_refund', 'out_refund'))
        FROM account_move am
        WHERE am.id = aml.move_id
          AND EXISTS (
              SELECT 1
              FROM account_account_tag_account_move_line_rel rel
              JOIN account_account_tag aat ON aat.id = rel.account_account_tag_id
              WHERE rel.account_move_line_id = aml.id
                AND aat.name::text ILIKE '%%DIOT%%'
          )
          AND aml.tax_tag_invert IS DISTINCT FROM
              (am.move_type IN ('in_refund', 'out_refund'))
    """)
    _logger.info(
        'anfepi_account_fix pre-migrate 19.0.1.0.0: '
        'DIOT tax_tag_invert corregido en %d lineas.',
        cr.rowcount,
    )
