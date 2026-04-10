# -*- coding: utf-8 -*-
from odoo import fields, models


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    tax_settlement_line_id = fields.Many2one(
        comodel_name='mx.tax.settlement.line',
        string='Línea de Liquidación Fiscal',
        index=True,
        copy=False,
        ondelete='set null',
        help='Referencia a la línea de liquidación fiscal que originó este movimiento contable.',
    )
