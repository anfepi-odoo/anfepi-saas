# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


# ---------------------------------------------------------------------------
# Reutilización local del algoritmo de distribución proporcional exacta.
# Idéntico al implementado en mx.tax.settlement.payment para garantizar
# que lo que propone el wizard sea exactamente lo que genera el asiento.
# ---------------------------------------------------------------------------

def _distribute_with_rounding(amount, weights, currency):
    """
    Distribuye `amount` entre N elementos proporcional a `weights`.
    Redondea todas las porciones excepto la última, que absorbe el residuo.
    Garantiza: Σ(results) == amount. Todos los valores ≥ 0.
    """
    if not weights:
        return []
    total_weight = sum(weights)
    if total_weight <= 0 or amount <= 0:
        return [0.0] * len(weights)

    results = []
    allocated = 0.0
    last_idx = len(weights) - 1
    for i, w in enumerate(weights):
        if i == last_idx:
            results.append(currency.round(amount - allocated))
        else:
            portion = currency.round(amount * (w / total_weight))
            results.append(portion)
            allocated += portion
    return results


class MxTaxSettlementPayWizard(models.TransientModel):
    _name = 'mx.tax.settlement.pay.wizard'
    _description = 'Asistente de Registro de Pago al SAT'

    settlement_id = fields.Many2one(
        comodel_name='mx.tax.settlement',
        string='Liquidación',
        required=True,
        readonly=True,
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        related='settlement_id.company_id',
        readonly=True,
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        related='settlement_id.currency_id',
        readonly=True,
    )
    period_display = fields.Char(
        related='settlement_id.period_display',
        readonly=True,
        string='Período',
    )
    payment_date = fields.Date(
        string='Fecha de Pago',
        required=True,
        default=fields.Date.today,
    )
    amount_total = fields.Monetary(
        string='Monto Total a Pagar',
        required=True,
        currency_field='currency_id',
    )
    distribution_mode = fields.Selection(
        selection=[
            ('auto', 'Prorrateo Automático'),
            ('manual', 'Asignación Manual por Concepto'),
        ],
        string='Modo de Distribución',
        required=True,
        default='auto',
    )
    bank_account_id = fields.Many2one(
        comodel_name='res.partner.bank',
        string='Cuenta Bancaria',
        required=True,
        domain="[('company_id', '=', company_id)]",
    )
    bank_reference = fields.Char(
        string='Referencia Bancaria',
        required=True,
        help='Número de operación / folio de transferencia bancaria al SAT.',
    )

    # =========================================================
    # DEFAULTS
    # =========================================================

    sat_reference = fields.Char(
        string='Referencia SAT',
        help='Número de línea de captura o folio de declaración SAT. '
             'Se guardará en la liquidación al confirmar el pago.',
    )
    line_ids = fields.One2many(
        comodel_name='mx.tax.settlement.pay.wizard.line',
        inverse_name='wizard_id',
        string='Distribución por Concepto',
    )
    total_pending = fields.Monetary(
        related='settlement_id.total_pending',
        readonly=True,
        string='Total Pendiente',
        currency_field='currency_id',
    )
    amount_distributed = fields.Monetary(
        string='Distribuido',
        compute='_compute_distribution_status',
        currency_field='currency_id',
    )
    amount_diff = fields.Monetary(
        string='Diferencia',
        compute='_compute_distribution_status',
        currency_field='currency_id',
    )
    is_balanced = fields.Boolean(
        string='Cuadrado',
        compute='_compute_distribution_status',
    )

    # =========================================================
    # COMPUTE
    # =========================================================

    @api.depends('line_ids.amount_applied', 'amount_total')
    def _compute_distribution_status(self):
        for rec in self:
            currency = rec.currency_id or self.env.company.currency_id
            distributed = currency.round(
                sum(rec.line_ids.mapped('amount_applied'))
            )
            rec.amount_distributed = distributed
            rec.amount_diff = currency.round(rec.amount_total - distributed)
            rec.is_balanced = currency.is_zero(rec.amount_diff)

    # =========================================================
    # DEFAULTS Y ONCHANGE
    # =========================================================

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        settlement_id = self.env.context.get('default_settlement_id')
        if settlement_id:
            settlement = self.env['mx.tax.settlement'].browse(settlement_id)
            res['settlement_id'] = settlement_id
            res['amount_total'] = settlement.total_pending
            # Pre-crear líneas del wizard con líneas pendientes
            line_vals = []
            for sl in settlement.line_ids.filtered(
                lambda l: l.line_state in ('pending', 'partial') and not l.is_deferred
            ):
                line_vals.append({
                    'settlement_line_id': sl.id,
                    'amount_pending': sl.amount_pending,
                    'amount_applied': sl.amount_pending,
                })
            res['line_ids'] = [(0, 0, lv) for lv in line_vals]
        return res

    @api.onchange('distribution_mode', 'amount_total')
    def _onchange_distribution_mode(self):
        """Recalcula la distribución automática cuando cambia el modo o el monto."""
        if self.distribution_mode == 'auto' and self.amount_total > 0:
            self._apply_auto_distribution()

    def _apply_auto_distribution(self):
        """
        Distribuye el monto total proporcionalmente entre las líneas pendientes.

        Algoritmo: Floor + Last-Remainder (idéntico al del motor de asientos).
          1. Calcular pesos = amount_pending por línea (capados a amount_pending).
          2. Calcular proporciones exactas sin redondear.
          3. Redondear todas excepto la última.
          4. Última = amount_total - Σ(primeras N-1).

        Garantías:
          - Σ(amounts) == amount_total exactamente.
          - Ningún concepto recibe más de su pendiente individual.
          - Trazabilidad matemática auditada: igual resultado que el asiento.
        """
        currency = self.currency_id or self.env.company.currency_id
        pending_lines = self.line_ids.filtered(lambda l: l.amount_pending > 0)

        if not pending_lines or self.amount_total <= 0:
            return

        total_pending = sum(pending_lines.mapped('amount_pending'))
        if not total_pending:
            return

        # Si amount_total >= total_pending, cada línea recibe su pendiente completo
        if self.amount_total >= total_pending:
            for line in self.line_ids:
                line.amount_applied = line.amount_pending if line.amount_pending > 0 else 0.0
            return

        # amount_total < total_pending: distribuir proporcionalmente
        weights = [l.amount_pending for l in pending_lines]
        amounts = _distribute_with_rounding(self.amount_total, weights, currency)

        # Asignar resultados, cap por si el redondeo excede el pending (raro pero posible)
        for line, amount in zip(pending_lines, amounts):
            line.amount_applied = min(max(amount, 0.0), line.amount_pending)

        # Líneas sin pending quedan en 0
        covered_ids = pending_lines.mapped('settlement_line_id').ids
        for line in self.line_ids.filtered(
            lambda l: l.settlement_line_id.id not in covered_ids
        ):
            line.amount_applied = 0.0

    # =========================================================
    # VALIDACIONES
    # =========================================================

    def _validate(self):
        # Filtrar sólo líneas válidas (con concepto asignado y monto aplicado > 0)
        active_lines = self.line_ids.filtered(
            lambda l: l.settlement_line_id and l.amount_applied > 0
        )
        if not active_lines:
            raise UserError(
                'No hay conceptos con monto a aplicar. '
                'Asegúrese de que al menos un concepto tenga monto mayor a cero.'
            )

        if not self.is_balanced:
            raise UserError(
                f'La distribución no está cuadrada. '
                f'Diferencia: {self.amount_diff:,.2f}. '
                'La suma de los montos distribuidos debe igualar el monto total del pago.'
            )

        for line in self.line_ids:
            sl = line.settlement_line_id
            if not sl:
                continue
            # Forzar re-lectura desde BD para evitar valores en caché
            # del campo store=True que pueden estar desactualizados
            # dentro de la misma transacción ORM.
            sl.invalidate_recordset(['amount_pending', 'amount_to_pay'])
            # ── Validación: no superar amount_to_pay confirmado ───────────
            if line.amount_applied > sl.amount_to_pay:
                raise ValidationError(
                    f'El monto asignado al concepto "{line.tax_concept_name}" '
                    f'({line.amount_applied:,.2f}) supera el monto a pagar '
                    f'confirmado ({sl.amount_to_pay:,.2f}).\n'
                    'El pago excedería la obligación fiscal determinada. Operación bloqueada.'
                )

        # Verificar que la fecha de pago esté en período abierto
        settlement = self.settlement_id
        settlement._check_period_open(self.payment_date)

    # =========================================================
    # ACCIÓN DE CONFIRMACIÓN
    # =========================================================

    def action_confirm(self):
        """Registra el pago y genera el asiento contable consolidado."""
        self.ensure_one()
        self._validate()

        settlement = self.settlement_id

        # Crear el registro de pago
        payment_vals = {
            'settlement_id': settlement.id,
            'payment_date': self.payment_date,
            'amount_total': self.amount_total,
            'distribution_mode': self.distribution_mode,
            'bank_account_id': self.bank_account_id.id,
            'bank_reference': self.bank_reference,
            'distribution_line_ids': [],
        }

        dist_lines = []
        for line in self.line_ids.filtered(
            lambda l: l.settlement_line_id and l.amount_applied > 0
        ):
            sl = line.settlement_line_id
            # Calcular amount_pending_before directamente desde BD,
            # evitando caché ORM del campo store=True computed.
            self.env.cr.execute(
                "SELECT amount_to_pay FROM mx_tax_settlement_line WHERE id = %s",
                (sl.id,)
            )
            row = self.env.cr.fetchone()
            amount_to_pay_db = row[0] if row else sl.amount_to_pay

            # Sumar pagos posted previos desde BD
            self.env.cr.execute(
                """SELECT COALESCE(SUM(pl.amount_applied), 0)
                   FROM mx_tax_settlement_payment_line pl
                   JOIN mx_tax_settlement_payment p ON p.id = pl.payment_id
                   WHERE pl.settlement_line_id = %s AND p.state = 'posted'""",
                (sl.id,)
            )
            already_paid_db = self.env.cr.fetchone()[0]
            pending_before = float(amount_to_pay_db) - float(already_paid_db)

            dist_lines.append((0, 0, {
                'settlement_line_id': sl.id,
                'amount_pending_before': pending_before,
                'amount_applied': line.amount_applied,
            }))
        payment_vals['distribution_line_ids'] = dist_lines

        payment = self.env['mx.tax.settlement.payment'].create(payment_vals)
        payment.action_generate_move()

        # Guardar la Referencia SAT en la liquidación
        if self.sat_reference:
            settlement.sat_reference = self.sat_reference

        # Cerrar wizard y volver a la liquidación
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'mx.tax.settlement',
            'res_id': settlement.id,
            'view_mode': 'form',
            'target': 'current',
        }


class MxTaxSettlementPayWizardLine(models.TransientModel):
    _name = 'mx.tax.settlement.pay.wizard.line'
    _description = 'Línea de Distribución — Asistente de Pago'
    _order = 'wizard_id, settlement_line_id'

    wizard_id = fields.Many2one(
        comodel_name='mx.tax.settlement.pay.wizard',
        string='Asistente',
        required=True,
        ondelete='cascade',
    )
    settlement_line_id = fields.Many2one(
        comodel_name='mx.tax.settlement.line',
        string='Línea de Liquidación',
        required=False,
        ondelete='restrict',
    )
    tax_concept_name = fields.Char(
        string='Concepto',
        related='settlement_line_id.tax_concept_id.name',
        readonly=True,
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        related='wizard_id.currency_id',
        readonly=True,
    )
    amount_pending = fields.Monetary(
        string='Pendiente',
        readonly=True,
        currency_field='currency_id',
    )
    amount_applied = fields.Monetary(
        string='Monto a Aplicar',
        currency_field='currency_id',
    )
    is_fully_covered = fields.Boolean(
        string='Cubierto',
        compute='_compute_is_fully_covered',
    )

    @api.depends('amount_applied', 'amount_pending')
    def _compute_is_fully_covered(self):
        for rec in self:
            currency = rec.currency_id or self.env.company.currency_id
            rec.is_fully_covered = currency.is_zero(
                rec.amount_pending - rec.amount_applied
            )
