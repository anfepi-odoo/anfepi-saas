# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError


class MxTaxSettlementCancelWizard(models.TransientModel):
    _name = 'mx.tax.settlement.cancel.wizard'
    _description = 'Asistente de Cancelación de Liquidación Fiscal'

    settlement_id = fields.Many2one(
        comodel_name='mx.tax.settlement',
        string='Liquidación',
        required=True,
        readonly=True,
    )
    settlement_name = fields.Char(
        related='settlement_id.name',
        readonly=True,
        string='Folio',
    )
    period_display = fields.Char(
        related='settlement_id.period_display',
        readonly=True,
        string='Período',
    )
    total_paid = fields.Monetary(
        related='settlement_id.total_paid',
        readonly=True,
        string='Total Pagado',
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        related='settlement_id.currency_id',
        readonly=True,
    )
    cancel_reason = fields.Text(
        string='Motivo de Cancelación',
        required=True,
        help='Describa detalladamente el motivo de la cancelación (mínimo 20 caracteres).',
    )
    reversal_date = fields.Date(
        string='Fecha de Reversión',
        required=True,
        default=fields.Date.today,
        help='Fecha en la que se crearán los asientos de reversión formal.',
    )
    has_posted_payments = fields.Boolean(
        string='Tiene Pagos Publicados',
        compute='_compute_has_posted_payments',
    )
    move_names = fields.Char(
        string='Asientos a Revertir',
        compute='_compute_has_posted_payments',
    )

    @api.depends('settlement_id')
    def _compute_has_posted_payments(self):
        for rec in self:
            posted = rec.settlement_id.payment_ids.filtered(
                lambda p: p.state == 'posted' and p.move_id
            )
            rec.has_posted_payments = bool(posted)
            rec.move_names = ', '.join(
                posted.mapped('move_id.name')
            ) if posted else ''

    @api.constrains('cancel_reason')
    def _check_cancel_reason(self):
        for rec in self:
            if not rec.cancel_reason or len(rec.cancel_reason.strip()) < 20:
                raise UserError(
                    'El motivo de cancelación debe tener al menos 20 caracteres. '
                    'Proporcione una descripción detallada.'
                )

    def action_confirm_cancel(self):
        """Ejecuta la cancelación de la liquidación."""
        self.ensure_one()

        if not self.cancel_reason or len(self.cancel_reason.strip()) < 20:
            raise UserError(
                'El motivo de cancelación debe tener al menos 20 caracteres.'
            )

        self.settlement_id._do_cancel(
            self.cancel_reason.strip(),
            reversal_date=self.reversal_date,
        )

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'mx.tax.settlement',
            'res_id': self.settlement_id.id,
            'view_mode': 'form',
            'target': 'current',
        }
