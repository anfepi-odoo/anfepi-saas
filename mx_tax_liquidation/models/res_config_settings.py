# -*- coding: utf-8 -*-
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    tax_settlement_journal_id = fields.Many2one(
        comodel_name='account.journal',
        string='Diario de Liquidaciones Fiscales',
        related='company_id.tax_settlement_journal_id',
        readonly=False,
        domain="[('company_id', '=', company_id), ('type', '=', 'general')]",
        help='Diario contable por defecto para los asientos de liquidación fiscal.',
    )
    tax_settlement_diff_threshold = fields.Float(
        string='Umbral de Diferencia (%)',
        related='company_id.tax_settlement_diff_threshold',
        readonly=False,
        help=(
            'Porcentaje máximo de diferencia entre monto determinado y monto a pagar '
            'sin requerir justificación escrita. Por defecto: 5%.'
        ),
    )
    tax_settlement_require_attachment = fields.Boolean(
        string='Requerir Acuse SAT',
        related='company_id.tax_settlement_require_attachment',
        readonly=False,
        help='Si está activo, no es posible cerrar la liquidación sin adjuntar el acuse del SAT.',
    )


class ResCompany(models.Model):
    _inherit = 'res.company'

    tax_settlement_journal_id = fields.Many2one(
        comodel_name='account.journal',
        string='Diario de Liquidaciones Fiscales',
        domain="[('company_id', '=', id), ('type', '=', 'general')]",
    )
    tax_settlement_diff_threshold = fields.Float(
        string='Umbral de Diferencia (%)',
        default=5.0,
    )
    tax_settlement_require_attachment = fields.Boolean(
        string='Requerir Acuse SAT',
        default=True,
    )
