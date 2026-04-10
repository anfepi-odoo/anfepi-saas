# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class MxTaxConcept(models.Model):
    _name = 'mx.tax.concept'
    _description = 'Concepto Fiscal SAT'
    _order = 'sequence, name'

    name = fields.Char(
        string='Nombre',
        required=True,
        translate=True,
    )
    code = fields.Char(
        string='Código',
        required=True,
        index=True,
        copy=False,
        help='Identificador único del concepto fiscal. Ej: IVA_PAGAR, RET_SAL',
    )
    sequence = fields.Integer(
        string='Secuencia',
        default=10,
        help='Orden en el asiento consolidado.',
    )
    tax_type = fields.Selection(
        selection=[
            ('iva', 'IVA'),
            ('isr', 'ISR'),
            ('retencion', 'Retención'),
        ],
        string='Tipo de Impuesto',
        required=True,
    )
    nature = fields.Selection(
        selection=[
            ('liability', 'Pasivo (acreedora)'),
            ('asset', 'Activo (deudora)'),
        ],
        string='Naturaleza',
        required=True,
        help=(
            'Liability: el saldo acreedor es la obligación a pagar.\n'
            'Asset: el saldo deudor representa un crédito a favor.'
        ),
    )
    requires_reclassification = fields.Boolean(
        string='Requiere Reclasificación',
        default=False,
        help=(
            'Activar para conceptos de retención donde Odoo registra el impuesto '
            'en una cuenta transitoria al pagar la factura del proveedor y, al liquidar '
            'al SAT, debe reclasificarse a la cuenta de pasivo exigible.\n'
            'Aplica a: IVA retenido (fletes, honorarios), ISR honorarios retenido, '
            'ISR arrendamiento retenido, etc.\n'
            'Al pagar al SAT, el asiento cancela la cuenta origen (transitoria) y abona el banco.'
        ),
    )
    description = fields.Text(
        string='Descripción',
    )
    active = fields.Boolean(
        string='Activo',
        default=True,
    )

    # Odoo 19: _sql_constraints reemplazado por models.Constraint
    _code_unique = models.Constraint('UNIQUE(code)', 'El código del concepto fiscal debe ser único.')

    @api.constrains('code')
    def _check_code_format(self):
        for rec in self:
            if not rec.code or not rec.code.replace('_', '').isalnum():
                raise ValidationError(
                    'El código del concepto solo puede contener letras, números y guiones bajos.'
                )
