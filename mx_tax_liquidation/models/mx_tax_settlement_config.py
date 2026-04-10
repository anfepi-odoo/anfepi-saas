# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class MxTaxSettlementConfig(models.Model):
    _name = 'mx.tax.settlement.config'
    _description = 'Configuración de Liquidación Fiscal por Empresa'
    _rec_name = 'tax_concept_id'
    _order = 'company_id, tax_concept_id'

    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Empresa',
        required=True,
        index=True,
        default=lambda self: self.env.company,
        ondelete='cascade',
    )
    tax_concept_id = fields.Many2one(
        comodel_name='mx.tax.concept',
        string='Concepto Fiscal',
        required=True,
        ondelete='restrict',
    )
    tax_type = fields.Selection(
        related='tax_concept_id.tax_type',
        store=True,
        readonly=True,
    )
    requires_reclassification = fields.Boolean(
        related='tax_concept_id.requires_reclassification',
        store=True,
        readonly=True,
    )
    liability_account_ids = fields.Many2many(
        comodel_name='account.account',
        relation='mx_tax_settlement_config_liability_account_rel',
        column1='config_id',
        column2='account_id',
        string='Cuentas de Pasivo a Liquidar',
        required=True,
        domain="[('company_ids', 'in', [company_id]), ('active', '=', True)]",
        help='Cuentas de pasivo cuyo saldo acreedor representa la obligación a pagar al SAT.',
    )
    compensation_account_ids = fields.Many2many(
        comodel_name='account.account',
        relation='mx_tax_settlement_config_compensation_account_rel',
        column1='config_id',
        column2='account_id',
        string='Disminuciones a Aplicar',
        domain="[('company_ids', 'in', [company_id]), ('active', '=', True)]",
        help=(
            'Cuentas de naturaleza deudora (activo) cuyos saldos REDUCEN la obligación '
            'a pagar. Cubre dos mecanismos fiscales distintos:\n'
            '\n'
            'ACREDITAMIENTO: Deduce impuesto pagado en compras del mismo impuesto '
            'cobrado en ventas (ej. IVA Acreditable 118.01.01 vs IVA Trasladado). '
            'Es el mecanismo ordinario del IVA — no requiere trámite SAT.\n'
            '\n'
            'DISMINUCIÓN POR ANTICIPOS / RETENCIONES: Reduce ISR propio con pagos '
            'provisionales anteriores o retenciones del mismo impuesto '
            '(ej. ISR Retenido 113.02.01 vs ISR Propio).\n'
            '\n'
            'REGLA: Solo aplica dentro del mismo tipo de impuesto. '
            'IVA solo acredita contra IVA; ISR solo contra ISR.'
        ),
    )
    reclassification_source_account_id = fields.Many2one(
        comodel_name='account.account',
        string='Cuenta IVA Retenido (No Pagado)',
        domain="[('company_ids', 'in', [company_id]), ('active', '=', True)]",
        help='Cuenta origen antes del pago al SAT. Se cancela al liquidar.',
    )
    iva_pending_account_id = fields.Many2one(
        comodel_name='account.account',
        string='IVA Acreditable Pendiente (Retención)',
        domain="[('company_ids', 'in', [company_id]), ('active', '=', True)]",
        help=(
            'Cuenta donde se acumula el IVA retenido acreditable que aún no puede '
            'deducirse (LIVA Art. 5). Se libera al pagar la retención al SAT.'
        ),
    )
    iva_acreditable_account_id = fields.Many2one(
        comodel_name='account.account',
        string='IVA Acreditable Definitivo',
        domain="[('company_ids', 'in', [company_id]), ('active', '=', True)]",
        help=(
            'Cuenta de IVA acreditable ya cobrado / definitivo. '
            'Al pagar la retención al SAT se traslada desde iva_pending_account_id.'
        ),
    )
    difference_threshold_pct = fields.Float(
        string='Umbral de Diferencia (%)',
        default=0.05,
        help=(
            'Porcentaje máximo de diferencia entre el monto determinado '
            'y el monto a pagar sin requerir justificación escrita.'
        ),
    )
    require_attachment = fields.Boolean(
        string='Requerir Acuse SAT Adjunto',
        default=True,
        help='Si está activo, no se puede cerrar la liquidación sin adjuntar el acuse del SAT.',
    )
    settlement_journal_id = fields.Many2one(
        comodel_name='account.journal',
        string='Diario de Liquidaciones',
        domain="[('company_id', '=', company_id), ('type', '=', 'general')]",
        help='Diario contable donde se publicarán los asientos de liquidación.',
    )
    active = fields.Boolean(
        string='Activo',
        default=True,
    )

    # Odoo 19: _sql_constraints reemplazado por models.Constraint
    _company_concept_unique = models.Constraint(
        'UNIQUE(company_id, tax_concept_id)',
        'Solo puede existir una configuración por empresa y concepto fiscal.',
    )

    @api.constrains(
        'requires_reclassification',
        'reclassification_source_account_id',
    )
    def _check_reclassification_accounts(self):
        for rec in self:
            if rec.requires_reclassification and not rec.reclassification_source_account_id:
                raise ValidationError(
                    f'El concepto "{rec.tax_concept_id.name}" requiere reclasificación. '
                    'Debe especificar la cuenta de IVA retenido (no pagado).'
                )

    @api.constrains('liability_account_ids')
    def _check_liability_accounts(self):
        for rec in self:
            if not rec.liability_account_ids:
                raise ValidationError(
                    f'La configuración del concepto "{rec.tax_concept_id.name}" '
                    'debe tener al menos una cuenta de pasivo a liquidar.'
                )
