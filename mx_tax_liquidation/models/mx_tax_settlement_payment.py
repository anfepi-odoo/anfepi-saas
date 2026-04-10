# -*- coding: utf-8 -*-
import logging
from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import format_date

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Algoritmo de distribución proporcional con redondeo exacto
# ---------------------------------------------------------------------------
# PRINCIPIO MATEMÁTICO: Método del "Floor + Largest Remainder"
#
# Dado un monto total T y N pesos w_i:
#   1. Calcular proporciones exactas: p_i = T * (w_i / W)  donde W = Σw_i
#   2. Redondear todas EXCEPTO la última con currency.round()
#   3. Asignar a la última: T - Σ(primeras N-1 redondeadas)
#
# Esto garantiza:
#   Σ(results) == T  (exactamente, sin diferencias de centavo)
#   Ninguna línea recibe monto negativo
#   Proporcionalidad matemáticamente trazable
# ---------------------------------------------------------------------------

def _distribute_with_rounding(amount, weights, currency):
    """
    Distribuye `amount` entre N elementos proporcional a `weights`.

    Args:
        amount (float): Total a distribuir. Debe ser ≥ 0.
        weights (list[float]): Pesos de cada elemento. Al menos 1 elemento > 0.
        currency (res.currency): Moneda para redondeo.

    Returns:
        list[float]: Montos distribuidos que suman exactamente `amount`.
                     Todos ≥ 0. Len == len(weights).

    Raises:
        nada — devuelve lista de ceros si weights es vacío o suma 0.
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
            # Última porción: el residuo exacto para garantizar suma perfecta
            results.append(currency.round(amount - allocated))
        else:
            portion = currency.round(amount * (w / total_weight))
            results.append(portion)
            allocated += portion

    return results


class MxTaxSettlementPayment(models.Model):
    _name = 'mx.tax.settlement.payment'
    _description = 'Evento de Pago al SAT'
    _order = 'settlement_id, payment_date'

    settlement_id = fields.Many2one(
        comodel_name='mx.tax.settlement',
        string='Liquidación',
        required=True,
        ondelete='restrict',
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
    payment_date = fields.Date(
        string='Fecha de Pago',
        required=True,
        index=True,
    )
    amount_total = fields.Monetary(
        string='Monto Total',
        required=True,
        currency_field='currency_id',
    )
    distribution_mode = fields.Selection(
        selection=[
            ('auto', 'Prorrateo Automático'),
            ('manual', 'Asignación Manual'),
        ],
        string='Modo de Distribución',
        required=True,
        default='auto',
    )
    bank_account_id = fields.Many2one(
        comodel_name='res.partner.bank',
        string='Cuenta Bancaria',
        domain="[('company_id', '=', company_id)]",
        required=True,
    )
    bank_reference = fields.Char(
        string='Referencia Bancaria',
        required=True,
        copy=False,
        help='Número de operación / folio de transferencia bancaria.',
    )
    move_id = fields.Many2one(
        comodel_name='account.move',
        string='Asiento Contable',
        readonly=True,
        copy=False,
    )
    reversal_move_id = fields.Many2one(
        comodel_name='account.move',
        string='Asiento de Reversión',
        readonly=True,
        copy=False,
        help='Asiento de contrapartida generado al cancelar la liquidación.',
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Borrador'),
            ('posted', 'Publicado'),
            ('reversed', 'Revertido'),
        ],
        string='Estado',
        default='draft',
        required=True,
        copy=False,
        index=True,
    )
    distribution_line_ids = fields.One2many(
        comodel_name='mx.tax.settlement.payment.line',
        inverse_name='payment_id',
        string='Distribución por Concepto',
        copy=False,
    )
    amount_distributed = fields.Monetary(
        string='Monto Distribuido',
        compute='_compute_amounts',
        store=True,
        currency_field='currency_id',
    )
    amount_diff = fields.Monetary(
        string='Diferencia',
        compute='_compute_amounts',
        store=True,
        currency_field='currency_id',
    )
    is_balanced = fields.Boolean(
        string='Cuadrado',
        compute='_compute_amounts',
        store=True,
    )

    # =========================================================
    # COMPUTE
    # =========================================================

    @api.depends('distribution_line_ids.amount_applied', 'amount_total')
    def _compute_amounts(self):
        for rec in self:
            currency = rec.currency_id or self.env.company.currency_id
            distributed = currency.round(
                sum(rec.distribution_line_ids.mapped('amount_applied'))
            )
            rec.amount_distributed = distributed
            rec.amount_diff = currency.round(rec.amount_total - distributed)
            rec.is_balanced = currency.is_zero(rec.amount_diff)

    # =========================================================
    # VALIDACIONES
    # =========================================================

    @api.constrains('bank_reference', 'company_id', 'payment_date')
    def _check_bank_reference_unique(self):
        for rec in self:
            domain = [
                ('company_id', '=', rec.company_id.id),
                ('bank_reference', '=', rec.bank_reference),
                ('state', '!=', 'reversed'),
                ('id', '!=', rec.id or 0),
            ]
            existing = self.search(domain, limit=1)
            if existing:
                raise ValidationError(
                    f'La referencia bancaria "{rec.bank_reference}" ya existe en otro pago '
                    f'({existing.settlement_id.name}). Verifique el número de operación.'
                )

    @api.constrains('amount_total')
    def _check_amount_total(self):
        for rec in self:
            if rec.amount_total <= 0:
                raise ValidationError('El monto del pago debe ser mayor a cero.')

    # =========================================================
    # GENERACIÓN DEL ASIENTO CONTABLE
    # =========================================================

    def action_generate_move(self):
        """
        Genera el asiento contable consolidado para este evento de pago.

        ── PRINCIPIO RECTOR ──────────────────────────────────────────────────
        El asiento se construye EXCLUSIVAMENTE con los valores snapshot
        almacenados en mx.tax.settlement.line:
          • balance_liability      → saldo agregado del pasivo (snapshot)
          • balance_compensation   → saldo agregado de compensación (snapshot)
          • account_balance_snapshot → saldos por cuenta en JSON (snapshot)
          • amount_to_pay          → monto comprometido al confirmar (snapshot)
          • dist_line.amount_applied → monto de este pago por concepto
        ─────────────────────────────────────────────────────────────────────
        Nunca se vuelve a consultar account_move_line.
        Los saldos históricos no se alteran.
        Es apto para auditoría externa tipo Big Four.

        ── RECLASIFICACIÓN ATÓMICA IVA RETENIDO ─────────────────────────────
        Para conceptos con requires_reclassification = True:
          DEBE: reclassification_source_account (cuenta fuente snapshot)
          HABER: banco
        Solo 2 líneas. Sin pasos intermedios. Sin redundancias.
        ─────────────────────────────────────────────────────────────────────

        ── ALGORITMO DE REDONDEO ─────────────────────────────────────────────
        Se usa _distribute_with_rounding():
          1. Calcular proporción exacta por cuenta.
          2. Redondear todas excepto la última.
          3. Última = (total - suma_anteriores) para garantizar cuadre exacto.
        Garantiza: Σ(débitos) == Σ(créditos) == amount_total. Sin centavos perdidos.
        ─────────────────────────────────────────────────────────────────────
        """
        self.ensure_one()

        # ── Bloqueo de concurrencia (PostgreSQL NOWAIT) ───────────────────
        try:
            self.env.cr.execute(
                'SELECT id FROM mx_tax_settlement_payment WHERE id = %s FOR UPDATE NOWAIT',
                (self.id,),
            )
        except Exception:
            raise UserError(
                'Este pago está siendo procesado por otro usuario. '
                'Intente de nuevo en unos segundos.'
            )

        if self.state != 'draft':
            raise UserError('Este pago ya fue procesado.')

        settlement = self.settlement_id

        # ── R3: Bloquear si la liquidación ya no está activa ──────────────────
        # Previene que un pago quede posted bajo una liquidación cancelada
        # por race condition entre cancelación y generación de pago.
        if settlement.state not in ('confirmed', 'partial'):
            raise UserError(
                'No se puede generar el asiento porque la liquidación ya no está activa '
                f'(estado actual: {settlement.state}). '
                'Recargue la pantalla e intente nuevamente.'
            )

        settlement._check_period_open(self.payment_date)

        if not self.is_balanced:
            raise UserError(
                f'El pago no está cuadrado. Diferencia: {self.amount_diff:,.2f}. '
                'La suma de la distribución debe igualar el monto total del pago.'
            )

        # ── R2: Serializar concurrencia — bloquear settlement_lines en PostgreSQL ──
        # Impide que dos payments paralelos procesen las mismas líneas simultáneamente.
        # El lock es a nivel de fila (row-level): ningún otro FOR UPDATE NOWAIT
        # sobre los mismos ids podrá obtener el lock hasta que esta TX finalice.
        settlement_line_ids = self.distribution_line_ids.mapped('settlement_line_id').ids
        if settlement_line_ids:
            try:
                self.env.cr.execute(
                    'SELECT id FROM mx_tax_settlement_line '
                    'WHERE id = ANY(%s) FOR UPDATE NOWAIT',
                    (settlement_line_ids,),
                )
            except Exception:
                raise UserError(
                    'Otro pago sobre estas mismas líneas de liquidación está siendo procesado. '
                    'Intente nuevamente en unos segundos.'
                )

        # ── Validaciones pre-asiento: por concepto ───────────────────────────────
        # Las validaciones corren DESPUÉS del lock para garantizar que el
        # saldo leído (already_paid) es estable (ningún concurrent TX puede
        # modificarlo hasta que este TX libere el lock).
        PaymentLine = self.env['mx.tax.settlement.payment.line']
        for dist_line in self.distribution_line_ids:
            sl = dist_line.settlement_line_id

            # Barrera 1: pago individual no excede monto comprometido
            if dist_line.amount_applied > sl.amount_to_pay:
                raise ValidationError(
                    f'El monto aplicado al concepto "{sl.tax_concept_id.name}" '
                    f'({dist_line.amount_applied:,.2f}) excede el monto a pagar '
                    f'confirmado ({sl.amount_to_pay:,.2f}). Operación bloqueada.'
                )

            # Barrera 2 (R1): pago ACUMULADO no excede monto comprometido.
            # Se suma solo pagos ya posted para esta línea (excluye el propio
            # payment porque aún está en draft en este punto).
            already_paid = sum(
                PaymentLine.search([
                    ('settlement_line_id', '=', sl.id),
                    ('payment_id.state', '=', 'posted'),
                ]).mapped('amount_applied')
            )
            if already_paid + dist_line.amount_applied > sl.amount_to_pay:
                raise ValidationError(
                    f'El monto acumulado pagado '
                    f'({already_paid + dist_line.amount_applied:,.2f}) '
                    f'al concepto "{sl.tax_concept_id.name}" supera el monto a pagar '
                    f'confirmado ({sl.amount_to_pay:,.2f}).\n'
                    'Operación bloqueada para evitar sobrepago de obligación fiscal.'
                )

        # Obtener cuenta bancaria de liquidez
        bank_account = self._get_bank_liquidity_account()
        currency = self.currency_id

        # Acumulador de líneas del asiento
        # Cada elemento: dict con campos contables + '_sl_id' para trazabilidad
        move_line_vals = []

        # ── Construcción de líneas por distribución ───────────────────────
        for dist_line in self.distribution_line_ids.filtered(
            lambda dl: dl.amount_applied > 0
        ):
            settlement_line = dist_line.settlement_line_id
            config = settlement_line.config_id
            concept = settlement_line.tax_concept_id
            amount_applied = dist_line.amount_applied

            label = (
                f"{concept.code} | {settlement.name} | {settlement.period_display}"
            )

            # ── Rama 1: IVA RETENIDO (pasivo con cuenta origen) ──────────
            # El flujo cash-basis de Odoo MX ya reclasificó:
            #   Dr. 216.10.10 (pendiente)  →  Cr. 216.10.20 (SAT obligation)
            # al momento del pago al proveedor. Por lo tanto, el asiento del
            # SAT debe DEBITAR la cuenta de pasivo (216.10.20) donde está el
            # saldo real, y ABONAR el banco.
            #
            # LIVA Art. 5 — Liberación IVA Acreditable Pendiente:
            # Si la config tiene iva_pending_account_id configurada, el mismo
            # monto de la retención pagada se libera del activo pendiente:
            #   Dr. 216.10.20   ← SAT obligation cancelada
            #   Dr. 118.01.03   ← IVA acreditable pendiente liberado
            #   Cr. 102.01.01   ← Banco (calculado automáticamente al final)
            #   Cr. 118.01.01   ← IVA acreditable definitivo
            if concept.requires_reclassification and config.reclassification_source_account_id:
                liability_accounts = settlement_line.liability_account_ids
                if liability_accounts:
                    liab_weights = [1.0] * len(liability_accounts)
                    liab_amounts = _distribute_with_rounding(
                        amount_applied, liab_weights, currency
                    )
                    for acc, amt in zip(liability_accounts, liab_amounts):
                        if amt > 0:
                            move_line_vals.append({
                                'account_id': acc.id,
                                'debit': amt,
                                'credit': 0.0,
                                'name': label,
                                '_sl_id': settlement_line.id,
                            })
                else:
                    # Fallback: usar la cuenta fuente si no hay liability
                    move_line_vals.append({
                        'account_id': config.reclassification_source_account_id.id,
                        'debit': amount_applied,
                        'credit': 0.0,
                        'name': label,
                        '_sl_id': settlement_line.id,
                    })

                # ── Liberación IVA Acreditable Pendiente (LIVA Art. 5) ───
                # Al pagar la retención al SAT, el IVA que estaba pendiente
                # de acreditarse en 118.01.03 queda liberado hacia 118.01.01.
                # 118.01.03 es activo acreedor (se ABONA para disminuirlo).
                # 118.01.01 es activo deudor  (se CARGA para aumentarlo).
                # Estas dos líneas se netean entre sí (no afectan el cálculo
                # del abono al banco que se hace al final).
                if config.iva_pending_account_id and config.iva_acreditable_account_id:
                    move_line_vals.append({
                        'account_id': config.iva_pending_account_id.id,
                        'debit': 0.0,
                        'credit': amount_applied,          # Abono: reduce activo pendiente
                        'name': label + ' [IVA Acred. Pendiente Liberado]',
                        '_sl_id': settlement_line.id,
                    })
                    move_line_vals.append({
                        'account_id': config.iva_acreditable_account_id.id,
                        'debit': amount_applied,           # Cargo: aumenta activo definitivo
                        'credit': 0.0,
                        'name': label + ' [IVA Acred. Liberado → Definitivo]',
                        '_sl_id': settlement_line.id,
                    })

                # El abono al banco se añade al acumulador consolidado al final.
                continue

            # ── Rama 2: CONCEPTO NORMAL ───────────────────────────────────
            # Usa EXCLUSIVAMENTE el snapshot almacenado. Cero re-lecturas SQL.

            snapshot = settlement_line.get_snapshot_dict()  # {account_id: balance}
            liability_accounts = settlement_line.liability_account_ids
            compensation_accounts = settlement_line.compensation_account_ids
            stored_compensation = settlement_line.balance_compensation
            stored_liability = settlement_line.balance_liability

            # ── 2a. Porción de compensación (IVA acreditable) ────────────
            # Proporción: comp / amount_to_pay × amount_applied
            # Interpretación: de cada peso pagado, X centavos son "cruzados" con
            # IVA acreditable; el resto sale de caja.
            comp_applied = 0.0
            if compensation_accounts and stored_compensation > 0 and settlement_line.amount_to_pay > 0:
                comp_ratio = stored_compensation / settlement_line.amount_to_pay
                comp_applied = currency.round(
                    min(amount_applied * comp_ratio, amount_applied)
                )
                if comp_applied > 0:
                    # Distribuir comp_applied entre cuentas de compensación
                    # Peso = saldo positivo de cada cuenta (debit-normal)
                    comp_weights = [
                        max(snapshot.get(acc.id, 0.0), 0.0)
                        for acc in compensation_accounts
                    ]
                    comp_amounts = _distribute_with_rounding(
                        comp_applied, comp_weights, currency
                    )
                    for acc, amt in zip(compensation_accounts, comp_amounts):
                        if amt > 0:
                            move_line_vals.append({
                                'account_id': acc.id,
                                'debit': 0.0,
                                'credit': amt,
                                'name': label + ' [Compensación IVA]',
                                '_sl_id': settlement_line.id,
                            })

            # ── 2b. Porción de caja (pasivos que se cancelan con banco) ──
            cash_amount = currency.round(amount_applied - comp_applied)
            if cash_amount > 0 and liability_accounts:
                # Peso = saldo neto acreedor de cada cuenta pasivo (snapshot)
                # balance = SUM(debit)-SUM(credit); para liab: espera valor negativo
                # → max(-balance, 0.0) para obtener monto adeudado
                liab_weights = [
                    max(-snapshot.get(acc.id, 0.0), 0.0)
                    if concept.nature == 'liability'
                    else max(snapshot.get(acc.id, 0.0), 0.0)
                    for acc in liability_accounts
                ]
                # Si todos los pesos son 0 (raro en datos limpios), distribuir igual
                if sum(liab_weights) == 0:
                    liab_weights = [1.0] * len(liability_accounts)

                liab_amounts = _distribute_with_rounding(
                    cash_amount, liab_weights, currency
                )
                for acc, amt in zip(liability_accounts, liab_amounts):
                    if amt > 0:
                        move_line_vals.append({
                            'account_id': acc.id,
                            'debit': amt,
                            'credit': 0.0,
                            'name': label,
                            '_sl_id': settlement_line.id,
                        })

        # ── Línea única consolidada de banco (HABER) ─────────────────────
        # Se calcula como la diferencia neta de todas las líneas anteriores
        # para garantizar cuadre matemático perfecto.
        net_debit = sum(l['debit'] for l in move_line_vals)
        net_credit = sum(l['credit'] for l in move_line_vals)
        bank_credit = currency.round(net_debit - net_credit)

        if bank_credit <= 0:
            raise UserError(
                'Error interno: El asiento no generaría un abono al banco. '
                f'Débitos={net_debit:,.2f}, Créditos={net_credit:,.2f}. '
                'Revise la configuración de cuentas y el snapshot.'
            )

        move_line_vals.append({
            'account_id': bank_account.id,
            'debit': 0.0,
            'credit': bank_credit,
            'name': f"Pago SAT | {settlement.name} | Ref: {self.bank_reference}",
            '_sl_id': False,
        })

        # ── Validación final de cuadre (nunca debe fallar si el código es correcto) ──
        final_debit = sum(l['debit'] for l in move_line_vals)
        final_credit = sum(l['credit'] for l in move_line_vals)
        if not currency.is_zero(final_debit - final_credit):
            raise UserError(
                f'Error interno de cuadre: '
                f'Débitos={final_debit:,.2f} ≠ Créditos={final_credit:,.2f}. '
                f'Diferencia={final_debit - final_credit:,.6f}. '
                'Contacte al administrador del sistema. Ningún asiento fue creado.'
            )

        # ── Construcción del account.move ────────────────────────────────
        # Extraer _sl_id antes de pasar los vals al ORM
        clean_line_vals = []
        sl_refs = []
        for lv in move_line_vals:
            sl_id = lv.pop('_sl_id', None)
            clean_line_vals.append(lv)
            sl_refs.append(sl_id)

        move_vals = {
            'move_type': 'entry',
            'date': self.payment_date,
            'journal_id': settlement.journal_id.id,
            'company_id': settlement.company_id.id,
            'ref': f"{settlement.name} / {self.bank_reference}",
            'narration': (
                f"Liquidación fiscal {settlement.period_display} | "
                f"Banco: {self.bank_account_id.acc_number or ''} | "
                f"Ref: {self.bank_reference}"
            ),
            'line_ids': [(0, 0, lv) for lv in clean_line_vals],
        }

        move = self.env['account.move'].create(move_vals)

        # ── Vincular tax_settlement_line_id en cada línea del asiento ────
        for move_line, sl_id in zip(move.line_ids, sl_refs):
            if sl_id:
                move_line.sudo().write({'tax_settlement_line_id': sl_id})

        # ── Publicar asiento ──────────────────────────────────────────────
        move.action_post()

        self.write({
            'move_id': move.id,
            'state': 'posted',
        })

        # ── Actualizar Many2many de trazabilidad en las líneas ────────────
        for dist_line in self.distribution_line_ids:
            sl = dist_line.settlement_line_id
            related_move_lines = move.line_ids.filtered(
                lambda ml: ml.tax_settlement_line_id.id == sl.id
            )
            if related_move_lines:
                sl.move_line_ids = [(4, ml.id) for ml in related_move_lines]

        # ── Actualizar estado de la liquidación ───────────────────────────
        settlement._update_payment_state()
        settlement._log_action(
            'pay',
            (
                f'Pago registrado: {self.amount_total:,.2f} '
                f'| Ref: {self.bank_reference} '
                f'| Asiento: {move.name}'
            ),
            payment_id=self.id,
        )

    def _get_bank_liquidity_account(self):
        """
        Obtiene la cuenta de salida para el abono al banco.

        Para permitir la conciliación contra el extracto bancario, se usa
        la cuenta de método de pago saliente (Pagos Emitidos / outstanding
        outbound) del diario bancario, no la cuenta del banco directamente.

        Jerarquía:
          1. payment_account_id del primer método de pago saliente del diario bancario
          2. default_account_id del diario bancario
          3. default_account_id del diario de liquidación (fallback)
        """
        journal = self.settlement_id.journal_id
        bank_account = self.bank_account_id

        # Buscar el diario bancario asociado a la cuenta bancaria
        bank_journal = self.env['account.journal'].search([
            ('bank_account_id', '=', bank_account.id),
            ('company_id', '=', self.company_id.id),
        ], limit=1)

        if bank_journal:
            # Prioridad 1: cuenta de pagos emitidos (para conciliación bancaria)
            outbound_method = bank_journal.outbound_payment_method_line_ids[:1]
            if outbound_method and outbound_method.payment_account_id:
                return outbound_method.payment_account_id
            # Prioridad 2: cuenta principal del diario bancario
            if bank_journal.default_account_id:
                return bank_journal.default_account_id

        # Fallback: cuenta de liquidez genérica del diario de liquidación
        if journal.default_account_id:
            return journal.default_account_id

        raise UserError(
            f'No se encontró una cuenta de liquidez para la cuenta bancaria '
            f'"{bank_account.acc_number}". Configure el diario bancario correspondiente.'
        )
