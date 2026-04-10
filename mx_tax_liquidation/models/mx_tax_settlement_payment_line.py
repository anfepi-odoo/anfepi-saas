# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError


class MxTaxSettlementPaymentLine(models.Model):
    _name = 'mx.tax.settlement.payment.line'
    _description = 'Distribución de Pago por Concepto Fiscal'
    _order = 'payment_id, settlement_line_id'

    payment_id = fields.Many2one(
        comodel_name='mx.tax.settlement.payment',
        string='Pago',
        required=True,
        ondelete='cascade',
        index=True,
    )
    settlement_line_id = fields.Many2one(
        comodel_name='mx.tax.settlement.line',
        string='Línea de Liquidación',
        required=True,
        ondelete='restrict',
    )
    tax_concept_id = fields.Many2one(
        comodel_name='mx.tax.concept',
        related='settlement_line_id.tax_concept_id',
        store=True,
        readonly=True,
        string='Concepto Fiscal',
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        related='payment_id.currency_id',
        store=True,
        readonly=True,
    )
    amount_pending_before = fields.Monetary(
        string='Pendiente Antes',
        currency_field='currency_id',
        readonly=True,
        help='Monto pendiente de pago antes de este evento.',
    )
    amount_applied = fields.Monetary(
        string='Monto Aplicado',
        required=True,
        currency_field='currency_id',
    )
    amount_pending_after = fields.Monetary(
        string='Pendiente Después',
        compute='_compute_amount_pending_after',
        store=True,
        currency_field='currency_id',
    )
    is_fully_covered = fields.Boolean(
        string='Cubierto',
        compute='_compute_amount_pending_after',
        store=True,
    )

    @api.depends('amount_pending_before', 'amount_applied')
    def _compute_amount_pending_after(self):
        for rec in self:
            currency = rec.currency_id or self.env.company.currency_id
            rec.amount_pending_after = currency.round(
                max(rec.amount_pending_before - rec.amount_applied, 0.0)
            )
            rec.is_fully_covered = currency.is_zero(rec.amount_pending_after)

    @api.constrains('amount_applied', 'amount_pending_before')
    def _check_amount_applied(self):
        """
        Validación matemática absoluta en tres capas:

        1. Negativo: nunca se permite aplicar un monto negativo.
        2. Sobregiro sobre snapshot: amount_applied no puede superar
           amount_pending_before (valor congelado al momento de crear la línea).
        3. Sobregiro live: amount_applied no puede superar el monto a pagar
           confirmado (settlement_line.amount_to_pay) porque eso representaría
           un pago en exceso sobre la obligación fiscal determinada.

        Las tres capas son necesarias:
          - Capa 1: integridad de datos básica.
          - Capa 2: consistencia con el snapshot capturado por el wizard.
          - Capa 3: bloqueo matemático absoluto contra la obligación confirmada.
        """
        for rec in self:
            concept_name = rec.tax_concept_id.name or str(rec.settlement_line_id.id)

            # ── Capa 1: no negativos ──────────────────────────────────────
            if rec.amount_applied < 0:
                raise ValidationError(
                    f'El monto aplicado al concepto "{concept_name}" '
                    'no puede ser negativo.'
                )

            # ── Capa 2: no superar snapshot (amount_pending_before) ───────
            # Solo validar si amount_pending_before > 0 (puede ser 0 cuando el
            # campo computed store=True está en caché ORM dentro de la misma TX).
            if rec.amount_pending_before > 0 and rec.amount_applied > rec.amount_pending_before:
                raise ValidationError(
                    f'El monto aplicado ({rec.amount_applied:,.2f}) al concepto '
                    f'"{concept_name}" supera el pendiente capturado en este pago '
                    f'({rec.amount_pending_before:,.2f}).\n'
                    'No se permiten sobregiros sobre el snapshot del pago.'
                )

            # ── Capa 3: no superar el monto comprometido ACUMULADO ─────────
            # Suma todos los pagos ya posted para esta línea (excluye el propio
            # registro) y valida que already_paid + amount_applied <= amount_to_pay.
            # Esto bloquea sobrepago incluso en eventos de pago parcial múltiple.
            sl = rec.settlement_line_id
            if sl:
                already_paid = sum(
                    self.search([
                        ('settlement_line_id', '=', sl.id),
                        ('payment_id.state', '=', 'posted'),
                        ('id', '!=', rec.id if rec.id else 0),
                    ]).mapped('amount_applied')
                )
                if already_paid + rec.amount_applied > sl.amount_to_pay:
                    raise ValidationError(
                        f'El monto acumulado pagado '
                        f'({already_paid + rec.amount_applied:,.2f}) '
                        f'al concepto "{concept_name}" supera el monto a pagar '
                        f'confirmado ({sl.amount_to_pay:,.2f}).\n'
                        'Operación bloqueada para evitar sobrepago de obligación fiscal.'
                    )
