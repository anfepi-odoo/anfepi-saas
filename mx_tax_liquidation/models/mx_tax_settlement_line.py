# -*- coding: utf-8 -*-
import json
import logging

from odoo import api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)

# Campos protegidos por el snapshot: no modificables después de confirmar.
# Estas constantes se usan tanto en write() como en la documentación técnica.
_SNAPSHOT_FIELDS = frozenset({
    'balance_liability',
    'balance_compensation',
    'account_balance_snapshot',
    'amount_to_pay',
    'liability_account_ids',
    'compensation_account_ids',
})


class MxTaxSettlementLine(models.Model):
    _name = 'mx.tax.settlement.line'
    _description = 'Línea de Liquidación por Concepto Fiscal'
    _order = 'settlement_id, concept_sequence'

    settlement_id = fields.Many2one(
        comodel_name='mx.tax.settlement',
        string='Liquidación',
        required=True,
        ondelete='cascade',
        index=True,
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        related='settlement_id.company_id',
        store=True,
        readonly=True,
        index=True,
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        related='settlement_id.currency_id',
        store=True,
        readonly=True,
    )
    tax_concept_id = fields.Many2one(
        comodel_name='mx.tax.concept',
        string='Concepto Fiscal',
        required=True,
        ondelete='restrict',
    )
    concept_sequence = fields.Integer(
        string='Secuencia',
        related='tax_concept_id.sequence',
        store=True,
        readonly=True,
    )
    config_id = fields.Many2one(
        comodel_name='mx.tax.settlement.config',
        string='Configuración',
        required=True,
        ondelete='restrict',
    )
    requires_reclassification = fields.Boolean(
        related='tax_concept_id.requires_reclassification',
        store=True,
        readonly=True,
    )

    # =========================================================
    # CUENTAS COPIADAS DESDE LA CONFIGURACIÓN AL CALCULAR
    # =========================================================

    liability_account_ids = fields.Many2many(
        comodel_name='account.account',
        relation='mx_settlement_line_liability_account_rel',
        column1='line_id',
        column2='account_id',
        string='Cuentas de Pasivo',
        readonly=True,
    )
    compensation_account_ids = fields.Many2many(
        comodel_name='account.account',
        relation='mx_settlement_line_compensation_account_rel',
        column1='line_id',
        column2='account_id',
        string='Cuentas de Compensación',
        readonly=True,
    )

    # =========================================================
    # CAMPOS DE SALDO
    # =========================================================

    balance_liability = fields.Monetary(
        string='Saldo Pasivo',
        currency_field='currency_id',
        help='Saldo contable detectado en cuentas de pasivo fiscal.',
    )
    balance_compensation = fields.Monetary(
        string='Saldo Compensación',
        currency_field='currency_id',
        help='Saldo contable de cuentas compensatorias (IVA acreditable, etc.).',
    )
    amount_determined = fields.Monetary(
        string='Monto Determinado',
        compute='_compute_amount_determined',
        store=True,
        currency_field='currency_id',
        help='Monto neto a pagar determinado = Pasivo − Compensación. Nunca negativo.',
    )
    amount_to_pay = fields.Monetary(
        string='Monto a Pagar',
        currency_field='currency_id',
        help='Monto que el contador declarará y pagará al SAT. Editable.',
    )
    amount_paid = fields.Monetary(
        string='Monto Pagado',
        compute='_compute_amount_paid',
        store=True,
        currency_field='currency_id',
    )
    amount_pending = fields.Monetary(
        string='Pendiente',
        compute='_compute_amount_paid',
        store=True,
        currency_field='currency_id',
    )
    amount_difference = fields.Monetary(
        string='Diferencia',
        compute='_compute_difference',
        store=True,
        currency_field='currency_id',
        help='Diferencia entre monto determinado y monto a pagar.',
    )
    difference_pct = fields.Float(
        string='Diferencia %',
        compute='_compute_difference',
        store=True,
        digits=(5, 2),
    )
    difference_justification = fields.Text(
        string='Justificación de Diferencia',
        help='Requerida si la diferencia supera el umbral configurado.',
    )

    # =========================================================
    # ESTADO
    # =========================================================

    line_state = fields.Selection(
        selection=[
            ('pending', 'Pendiente'),
            ('partial', 'Pago Parcial'),
            ('paid', 'Pagado'),
            ('deferred', 'Diferida'),
            ('zero', 'Sin Obligación'),
            ('favor', 'Saldo a Favor'),
        ],
        string='Estado',
        compute='_compute_line_state',
        store=True,
    )
    is_deferred = fields.Boolean(
        string='Diferida',
        default=False,
        help='Marcar línea como diferida intencionalmente (no aplica este período).',
    )

    # =========================================================
    # TRAZABILIDAD
    # =========================================================

    move_line_ids = fields.Many2many(
        comodel_name='account.move.line',
        string='Líneas de Asiento',
        copy=False,
    )
    calculation_note = fields.Text(
        string='Nota de Cálculo',
        readonly=True,
        help='Detalle de cuentas y saldos leídos automáticamente.',
    )

    # =========================================================
    # SNAPSHOT INMUTABLE DE SALDOS POR CUENTA
    # =========================================================

    account_balance_snapshot = fields.Text(
        string='Snapshot de Saldos por Cuenta',
        readonly=True,
        copy=False,
        help=(
            'JSON interno: {str(account_id): SUM(debit)-SUM(credit)}. '
            'Congelado al calcular. Nunca se recalcula durante el pago. '
            'Formato: {"1234": -50000.0, "1235": -30000.0}'
        ),
    )
    is_snapshot_locked = fields.Boolean(
        string='Snapshot Bloqueado',
        compute='_compute_is_snapshot_locked',
        store=True,
        copy=False,
        help='True cuando la liquidación no está en Borrador. '
             'Impide modificar cualquier campo de saldo auditado.',
    )

    @api.depends('settlement_id.state')
    def _compute_is_snapshot_locked(self):
        for rec in self:
            rec.is_snapshot_locked = rec.settlement_id.state != 'draft'

    # =========================================================
    # COMPUTE METHODS
    # =========================================================

    @api.depends('balance_liability', 'balance_compensation')
    def _compute_amount_determined(self):
        for rec in self:
            currency = rec.currency_id or self.env.company.currency_id
            raw = rec.balance_liability - rec.balance_compensation
            # Permitir valores negativos: indica saldo a FAVOR (crédito > obligación).
            # El A Pagar nunca puede ser negativo (se controla en el wizard),
            # pero el Determinado sí puede serlo para informar al contador.
            rec.amount_determined = currency.round(raw)

    @api.depends('settlement_id.payment_ids.distribution_line_ids.amount_applied',
                 'settlement_id.payment_ids.state',
                 'amount_to_pay')
    def _compute_amount_paid(self):
        for rec in self:
            currency = rec.currency_id or self.env.company.currency_id
            paid = sum(
                dl.amount_applied
                for dl in rec.settlement_id.payment_ids.filtered(
                    lambda p: p.state == 'posted'
                ).mapped('distribution_line_ids').filtered(
                    lambda dl: dl.settlement_line_id.id == rec.id
                )
            )
            rec.amount_paid = currency.round(paid)
            rec.amount_pending = currency.round(max(rec.amount_to_pay - paid, 0.0))

    @api.depends('amount_determined', 'amount_to_pay')
    def _compute_difference(self):
        for rec in self:
            currency = rec.currency_id or self.env.company.currency_id
            rec.amount_difference = currency.round(rec.amount_determined - rec.amount_to_pay)
            if rec.amount_determined and rec.amount_determined > 0:
                rec.difference_pct = abs(rec.amount_difference) / rec.amount_determined * 100
            else:
                rec.difference_pct = 0.0

    @api.depends('is_deferred', 'amount_to_pay', 'amount_paid', 'amount_determined')
    def _compute_line_state(self):
        for rec in self:
            currency = rec.currency_id or self.env.company.currency_id
            # Calcular pending directamente aquí (no usar rec.amount_pending que es
            # un campo computed hermano y puede estar estancado si amount_to_pay
            # cambió sin disparar su propio depends).
            pending = currency.round(max(rec.amount_to_pay - rec.amount_paid, 0.0))
            if rec.is_deferred:
                rec.line_state = 'deferred'
            elif rec.amount_determined < 0 and currency.is_zero(rec.amount_to_pay):
                # Compensación supera obligación: saldo neto a favor de la empresa
                rec.line_state = 'favor'
            elif currency.is_zero(rec.amount_determined) and currency.is_zero(rec.amount_to_pay):
                rec.line_state = 'zero'
            elif currency.is_zero(pending):
                rec.line_state = 'paid'
            elif rec.amount_paid > 0:
                rec.line_state = 'partial'
            else:
                rec.line_state = 'pending'

    # =========================================================
    # VALIDACIONES
    # =========================================================

    @api.constrains('amount_to_pay')
    def _check_amount_to_pay(self):
        for rec in self:
            if rec.amount_to_pay < 0:
                raise ValidationError(
                    f'El monto a pagar del concepto "{rec.tax_concept_id.name}" '
                    'no puede ser negativo.'
                )

    # =========================================================
    # BLINDAJE DE SNAPSHOT: bloqueo de escritura sobre campos
    # auditados después de la confirmación.
    # =========================================================

    def write(self, vals):
        """
        Bloquea la escritura sobre los campos de snapshot cuando la liquidación
        ya fue confirmada (is_snapshot_locked = True).

        Los campos afectados son exactamente los que componen el cálculo fiscal:
        balance_liability, balance_compensation, account_balance_snapshot,
        amount_to_pay, liability_account_ids, compensation_account_ids.

        Los campos de seguimiento (line_state, amount_paid, amount_pending,
        difference_pct) son computed-stored y se escriben por el ORM: se
        permiten siempre para no romper el motor de cómputo.
        """
        locked_writes = _SNAPSHOT_FIELDS & set(vals.keys())
        if locked_writes:
            # Solo validar si hay algo que verificar (optimización)
            for rec in self:
                if rec.is_snapshot_locked:
                    fields_str = ', '.join(sorted(locked_writes))
                    raise ValidationError(
                        f'La línea "{rec.tax_concept_id.name}" pertenece a la '
                        f'liquidación "{rec.settlement_id.name}" que ya fue confirmada.\n'
                        f'Los campos de snapshot ({fields_str}) no pueden modificarse.\n'
                        'Para corregir saldos, cancele la liquidación y cree una nueva.'
                    )
        return super().write(vals)

    # =========================================================
    # HELPERS PARA PAYMENT ENGINE
    # =========================================================

    def get_snapshot_dict(self):
        """
        Deserializa el snapshot de saldos por cuenta.
        Retorna {int(account_id): float(balance)} donde balance = SUM(debit) - SUM(credit).

        Para cuentas de PASIVO (credit-normal): balance esperado es negativo.
          → usar max(-balance, 0.0) como peso de distribución.
        Para cuentas de COMPENSACIÓN (debit-normal): balance esperado es positivo.
          → usar max(balance, 0.0) como peso de distribución.
        """
        self.ensure_one()
        raw = self.account_balance_snapshot
        if not raw:
            return {}
        try:
            return {int(k): float(v) for k, v in json.loads(raw).items()}
        except (json.JSONDecodeError, TypeError, ValueError):
            _logger.error(
                'mx.tax.settlement.line id=%s: account_balance_snapshot malformado: %r',
                self.id, raw,
            )
            return {}
