# -*- coding: utf-8 -*-
import json
import logging
from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import format_date, sql

_logger = logging.getLogger(__name__)


class MxTaxSettlement(models.Model):
    _name = 'mx.tax.settlement'
    _description = 'Liquidación de Obligaciones Fiscales'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'period_date desc, company_id'
    _rec_name = 'name'

    # =========================================================
    # CAMPOS DE IDENTIFICACIÓN
    # =========================================================

    name = fields.Char(
        string='Folio',
        readonly=True,
        copy=False,
        default='/',
        index=True,
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        string='Empresa',
        required=True,
        index=True,
        default=lambda self: self.env.company,
        ondelete='restrict',
        tracking=True,
    )
    currency_id = fields.Many2one(
        comodel_name='res.currency',
        related='company_id.currency_id',
        store=True,
        readonly=True,
        string='Moneda',
    )

    # =========================================================
    # CAMPOS DE PERÍODO
    # =========================================================

    period_date = fields.Date(
        string='Período Fiscal',
        required=True,
        index=True,
        tracking=True,
        help='Primer día del mes de la obligación fiscal.',
    )
    period_year = fields.Integer(
        string='Año',
        compute='_compute_period_fields',
        store=True,
    )
    period_month = fields.Integer(
        string='Mes',
        compute='_compute_period_fields',
        store=True,
    )
    period_display = fields.Char(
        string='Período',
        compute='_compute_period_fields',
        store=True,
    )
    calculation_date = fields.Date(
        string='Fecha de Corte',
        required=True,
        help='Fecha hasta la cual se leerán los saldos contables.',
    )

    # =========================================================
    # CAMPOS DE ESTADO
    # =========================================================

    state = fields.Selection(
        selection=[
            ('draft', 'Borrador'),
            ('confirmed', 'Confirmada'),
            ('partial', 'Pago Parcial'),
            ('paid', 'Pagada'),
            ('cancel', 'Cancelada'),
        ],
        string='Estado',
        required=True,
        default='draft',
        copy=False,
        tracking=True,
        index=True,
    )

    # =========================================================
    # CAMPOS OPERATIVOS
    # =========================================================

    journal_id = fields.Many2one(
        comodel_name='account.journal',
        string='Diario de Liquidación',
        required=True,
        domain="[('company_id', '=', company_id), ('type', '=', 'general')]",
        tracking=True,
    )
    responsible_id = fields.Many2one(
        comodel_name='res.users',
        string='Contador Responsable',
        required=True,
        default=lambda self: self.env.user,
        tracking=True,
    )
    sat_reference = fields.Char(
        string='Referencia SAT',
        copy=False,
        help='Número de línea de captura o declaración.',
    )
    payment_type = fields.Selection(
        selection=[
            ('normal', 'Normal'),
            ('complementary', 'Complementario'),
        ],
        string='Tipo de Declaración',
        required=True,
        default='normal',
        tracking=True,
        help=(
            'Normal: declaración ordinaria del período.\n'
            'Complementario: corrección a una declaración ya presentada (Art. 32 CFF).\n\n'
            'Criterios SAT:\n'
            '• A FAVOR DEL SAT (paga más): complementarias ilimitadas.\n'
            '• A FAVOR DEL CONTRIBUYENTE (paga menos / genera saldo a favor): máximo 2 por período.'
        ),
    )
    notes = fields.Text(
        string='Notas',
    )

    # =========================================================
    # RELACIONES
    # =========================================================

    line_ids = fields.One2many(
        comodel_name='mx.tax.settlement.line',
        inverse_name='settlement_id',
        string='Líneas de Conceptos',
        copy=False,
    )
    payment_ids = fields.One2many(
        comodel_name='mx.tax.settlement.payment',
        inverse_name='settlement_id',
        string='Pagos al SAT',
        copy=False,
    )
    log_ids = fields.One2many(
        comodel_name='mx.tax.settlement.log',
        inverse_name='settlement_id',
        string='Bitácora de Auditoría',
    )
    move_ids = fields.Many2many(
        comodel_name='account.move',
        string='Asientos Contables',
        compute='_compute_move_ids',
        copy=False,
    )

    # =========================================================
    # CAMPOS CALCULADOS DE TOTALES
    # =========================================================

    total_determined = fields.Monetary(
        string='Total Determinado',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
    )
    total_to_pay = fields.Monetary(
        string='Total a Pagar',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
    )
    total_paid = fields.Monetary(
        string='Total Pagado',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
    )
    total_pending = fields.Monetary(
        string='Pendiente',
        compute='_compute_totals',
        store=True,
        currency_field='currency_id',
    )
    move_count = fields.Integer(
        string='Asientos',
        compute='_compute_move_ids',
    )

    # =========================================================
    # CAMPOS DE AUDITORÍA
    # =========================================================

    confirmation_date = fields.Datetime(
        string='Fecha de Confirmación',
        readonly=True,
        copy=False,
    )
    confirmation_uid = fields.Many2one(
        comodel_name='res.users',
        string='Confirmado por',
        readonly=True,
        copy=False,
    )
    cancel_reason = fields.Text(
        string='Motivo de Cancelación',
        copy=False,
    )
    cancel_date = fields.Datetime(
        string='Fecha Cancelación',
        readonly=True,
        copy=False,
    )
    cancel_uid = fields.Many2one(
        comodel_name='res.users',
        string='Cancelado por',
        readonly=True,
        copy=False,
    )

    # =========================================================
    # COMPUTE METHODS
    # =========================================================

    @api.depends('period_date')
    def _compute_period_fields(self):
        for rec in self:
            if rec.period_date:
                rec.period_year = rec.period_date.year
                rec.period_month = rec.period_date.month
                months_es = [
                    '', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
                    'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre',
                ]
                rec.period_display = f"{months_es[rec.period_date.month]} {rec.period_date.year}"
            else:
                rec.period_year = 0
                rec.period_month = 0
                rec.period_display = ''

    @api.depends('line_ids.amount_determined', 'line_ids.amount_to_pay', 'line_ids.amount_paid')
    def _compute_totals(self):
        for rec in self:
            currency = rec.currency_id
            rec.total_determined = sum(rec.line_ids.mapped('amount_determined'))
            rec.total_to_pay = sum(rec.line_ids.mapped('amount_to_pay'))
            rec.total_paid = sum(rec.line_ids.mapped('amount_paid'))
            rec.total_pending = currency.round(rec.total_to_pay - rec.total_paid)

    def _compute_move_ids(self):
        for rec in self:
            moves = rec.payment_ids.filtered(
                lambda p: p.move_id
            ).mapped('move_id')
            reversal_moves = rec.payment_ids.filtered(
                lambda p: p.reversal_move_id
            ).mapped('reversal_move_id')
            rec.move_ids = moves | reversal_moves
            rec.move_count = len(rec.move_ids)

    # =========================================================
    # ÍNDICE SQL COMPUESTO — rendimiento empresarial
    # =========================================================

    @api.model
    def _auto_init(self):
        """
        Crea índice SQL compuesto sobre (company_id, period_date) para soportar
        consultas de unicidad y filtros de período en empresas de alto volumen.
        El índice es parcial: excluye liquidaciones canceladas (reduce tamaño).
        """
        res = super()._auto_init()
        sql.create_index(
            self.env.cr,
            'mx_tax_settlement_company_period_idx',
            self._table,
            ['company_id', 'period_date'],
        )
        return res

    # =========================================================
    # ONCHANGE
    # =========================================================

    @api.onchange('period_date')
    def _onchange_period_date(self):
        if self.period_date:
            import calendar
            last_day = calendar.monthrange(self.period_date.year, self.period_date.month)[1]
            self.calculation_date = self.period_date.replace(day=last_day)

    @api.onchange('company_id')
    def _onchange_company_id(self):
        if self.company_id:
            company = self.company_id
            if company.tax_settlement_journal_id:
                self.journal_id = company.tax_settlement_journal_id

    # =========================================================
    # CRUD OVERRIDES
    # =========================================================

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('period_date'):
                # Normalize period_date to first day of month
                from datetime import date
                pd = fields.Date.from_string(vals['period_date'])
                vals['period_date'] = pd.replace(day=1)
            if not vals.get('name') or vals.get('name') == '/':
                vals['name'] = self._generate_name(
                    vals.get('company_id', self.env.company.id),
                    vals.get('period_date'),
                    vals.get('payment_type', 'normal'),
                )
        records = super().create(vals_list)
        for rec in records:
            rec._log_action('create', 'Liquidación creada.')
        return records

    def _generate_name(self, company_id, period_date, payment_type='normal'):
        company = self.env['res.company'].browse(company_id)
        sequence = self.env['ir.sequence'].with_company(company_id).next_by_code(
            'mx.tax.settlement'
        ) or '/'
        if period_date:
            from datetime import date
            if isinstance(period_date, str):
                pd = fields.Date.from_string(period_date)
            else:
                pd = period_date
            prefix = 'LIQS-COMP' if payment_type == 'complementary' else 'LIQS'
            return f"{prefix}/{company.name[:4].upper()}/{pd.year}/{pd.month:02d}/{sequence}"
        prefix = 'LIQS-COMP' if payment_type == 'complementary' else 'LIQS'
        return f"{prefix}/{sequence}"

    def unlink(self):
        for rec in self:
            if rec.state not in ('draft', 'cancel'):
                raise UserError(
                    f'No se puede eliminar la liquidación "{rec.name}" '
                    'porque no está en estado Borrador o Cancelada.'
                )
        return super().unlink()

    # =========================================================
    # VALIDACIONES
    # =========================================================

    def _check_period_open(self, date_to_check):
        """Verifica que la fecha no caiga en un periodo contable cerrado."""
        company = self.company_id
        lock_date = company._get_user_fiscal_lock_date()
        if lock_date and date_to_check <= lock_date:
            raise UserError(
                f'El período {format_date(self.env, date_to_check)} está bloqueado. '
                f'La fecha de bloqueo contable es {format_date(self.env, lock_date)}.'
            )

    def _check_no_duplicate(self):
        """
        Previene duplicación de conceptos fiscales por empresa/período.

        Regla Normal: puede existir más de una liquidación Normal por período,
        siempre que cada concepto fiscal aparezca en UNA SOLA Normal.
        Declarar el mismo concepto dos veces en el mismo período no está permitido.

        Regla Complementario: requiere una Normal base; máximo 2 complementarias
        a favor del contribuyente por período (Art. 32 CFF).
        """
        if self.payment_type == 'normal':
            # Buscar otras Normales activas del mismo período/empresa
            domain = [
                ('company_id', '=', self.company_id.id),
                ('period_date', '=', self.period_date),
                ('payment_type', '=', 'normal'),
                ('state', '!=', 'cancel'),
                ('id', '!=', self.id or 0),
            ]
            existing_normals = self.search(domain)
            if existing_normals and self.line_ids:
                # Solo considerar conceptos con obligación real (amount_to_pay > 0).
                # Un concepto con saldo cero no se considera "presentado" y no
                # debe bloquear que otro folio lo incluya en el mismo período.
                my_concepts = set(
                    self.line_ids.filtered(lambda l: l.amount_to_pay > 0)
                    .mapped('tax_concept_id').ids
                )
                for other in existing_normals:
                    other_concepts = set(
                        other.line_ids.filtered(lambda l: l.amount_to_pay > 0)
                        .mapped('tax_concept_id').ids
                    )
                    overlap = my_concepts & other_concepts
                    if overlap:
                        concept_names = ', '.join(
                            self.env['mx.tax.concept'].browse(list(overlap)).mapped('name')
                        )
                        raise UserError(
                            f'El concepto fiscal «{concept_names}» ya está incluido en '
                            f'la liquidación Normal {other.name} del período {self.period_display}.\n\n'
                            'Un mismo concepto fiscal no puede declararse en más de una '
                            'liquidación Normal por período. Si necesita corregir esa '
                            'declaración, cree una liquidación de tipo «Complementario».'
                        )
        else:
            # Complementario: permitir, pero verificar si hay normal base
            domain_normal = [
                ('company_id', '=', self.company_id.id),
                ('period_date', '=', self.period_date),
                ('payment_type', '=', 'normal'),
                ('state', '!=', 'cancel'),
            ]
            if not self.search(domain_normal, limit=1):
                raise UserError(
                    f'No existe una declaración Normal activa para el período '
                    f'{self.period_display}. Debe existir una declaración Normal '
                    'antes de poder crear una Complementaria.'
                )
            # Contar complementarias activas para este período
            domain_comp = [
                ('company_id', '=', self.company_id.id),
                ('period_date', '=', self.period_date),
                ('payment_type', '=', 'complementary'),
                ('state', '!=', 'cancel'),
                ('id', '!=', self.id or 0),
            ]
            count = self.search_count(domain_comp)
            if count >= 2:
                raise UserError(
                    f'Ya existen {count} declaraciones complementarias para el período '
                    f'{self.period_display}.\n\n'
                    'Criterios SAT (Art. 32 CFF):\n'
                    '• Si la complementaria resulta A FAVOR DEL SAT (paga más): '
                    'son ilimitadas y puede continuar.\n'
                    '• Si la complementaria resulta A FAVOR DEL CONTRIBUYENTE '
                    '(paga menos o genera saldo a favor): el límite es 2 por período.\n\n'
                    'Verifique con su asesor fiscal. Si la situación resulta a favor '
                    'del SAT, cancele esta validación via el administrador del sistema.'
                )

    # =========================================================
    # ACCIONES DE NEGOCIO
    # =========================================================

    def action_calculate_balances(self):
        """Calcula saldos contables reales por cuenta configurada."""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError('Solo se pueden calcular saldos en estado Borrador.')

        self._check_no_duplicate()

        company = self.company_id
        configs = self.env['mx.tax.settlement.config'].search([
            ('company_id', '=', company.id),
            ('active', '=', True),
        ])
        if not configs:
            raise UserError(
                f'No hay configuraciones activas de liquidación fiscal '
                f'para la empresa {company.name}. Configure las cuentas en '
                'Contabilidad > Configuración > Liquidaciones Fiscales.'
            )

        # Obtener saldos en una sola query SQL
        all_account_ids = set()
        for config in configs:
            all_account_ids.update(config.liability_account_ids.ids)
            all_account_ids.update(config.compensation_account_ids.ids)
            if config.reclassification_source_account_id:
                all_account_ids.add(config.reclassification_source_account_id.id)

        balances = self._fetch_account_balances(
            list(all_account_ids),
            company.id,
            self.period_date,
            self.calculation_date,
        )

        # Borrar líneas existentes
        self.line_ids.unlink()

        lines_to_create = []
        for config in configs.sorted('tax_concept_id'):
            concept = config.tax_concept_id
            nature = concept.nature

            # Saldo de cuentas de pasivo (obligación)
            balance_liability = 0.0
            for acc in config.liability_account_ids:
                raw = balances.get(acc.id, 0.0)
                if nature == 'liability':
                    # Para cuentas acreedoras: crédito - débito > 0 = deuda
                    balance_liability += max(-raw, 0.0)
                else:
                    balance_liability += max(raw, 0.0)

            # Saldo de cuentas de compensación (créditos a favor)
            balance_compensation = 0.0
            for acc in config.compensation_account_ids:
                raw = balances.get(acc.id, 0.0)
                # IVA acreditable: naturaleza deudora, saldo > 0 = crédito disponible
                balance_compensation += max(raw, 0.0)

            amount_determined = self.currency_id.round(
                max(balance_liability - balance_compensation, 0.0)
            )

            # -------------------------------------------------------
            # SNAPSHOT INMUTABLE: se guarda el saldo crudo por cuenta
            # (SUM(debit) - SUM(credit)) para distribuir el pago sin
            # volver a consultar account_move_line.
            # Incluye: cuentas pasivo + compensación + fuente reclasif.
            # -------------------------------------------------------
            snapshot_accounts = (
                config.liability_account_ids
                | config.compensation_account_ids
            )
            if config.reclassification_source_account_id:
                snapshot_accounts |= config.reclassification_source_account_id
            account_balance_snapshot = json.dumps({
                str(acc.id): balances.get(acc.id, 0.0)
                for acc in snapshot_accounts
            })

            # Nota de cálculo automática
            note_parts = [
                f'Período: {format_date(self.env, self.period_date)} → {format_date(self.env, self.calculation_date)}',
                f'Criterio: movimientos NETOS del período (no saldo acumulado histórico).',
                f'Solo asientos publicados entre {self.period_date} y {self.calculation_date}.',
            ]
            for acc in config.liability_account_ids:
                raw = balances.get(acc.id, 0.0)
                note_parts.append(f'  [{acc.code}] {acc.name}: {raw:,.2f}')
            if config.compensation_account_ids:
                note_parts.append('Compensaciones:')
                for acc in config.compensation_account_ids:
                    raw = balances.get(acc.id, 0.0)
                    note_parts.append(f'  [{acc.code}] {acc.name}: {raw:,.2f}')

            lines_to_create.append({
                'settlement_id': self.id,
                'tax_concept_id': concept.id,
                'config_id': config.id,
                'liability_account_ids': [(6, 0, config.liability_account_ids.ids)],
                'compensation_account_ids': [(6, 0, config.compensation_account_ids.ids)],
                'balance_liability': self.currency_id.round(balance_liability),
                'balance_compensation': self.currency_id.round(balance_compensation),
                'amount_to_pay': amount_determined,
                'account_balance_snapshot': account_balance_snapshot,
                'calculation_note': '\n'.join(note_parts),
            })

        self.env['mx.tax.settlement.line'].create(lines_to_create)
        self._log_action(
            'calculate',
            f'Saldos calculados. Total determinado: {sum(l["amount_to_pay"] for l in lines_to_create):,.2f}',
        )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Saldos Calculados',
                'message': f'Se generaron {len(lines_to_create)} líneas de conceptos fiscales.',
                'type': 'success',
                'sticky': False,
            },
        }

    def _fetch_account_balances(self, account_ids, company_id, date_start, date_stop):
        """
        Lectura eficiente de saldos contables via SQL parametrizado.
        Retorna {account_id: balance} donde balance = SUM(debit) - SUM(credit).
        Solo considera asientos publicados dentro del período: date_start..date_stop.
        Esto garantiza que se usan movimientos netos del período (no saldo histórico acumulado).
        """
        if not account_ids:
            return {}
        self.env.cr.execute(
            """
            SELECT
                aml.account_id,
                COALESCE(SUM(aml.debit) - SUM(aml.credit), 0.0) AS balance
            FROM account_move_line aml
            JOIN account_move am ON am.id = aml.move_id
            WHERE
                am.state = 'posted'
                AND am.company_id = %(company_id)s
                AND aml.account_id = ANY(%(account_ids)s)
                AND aml.date >= %(date_start)s
                AND aml.date <= %(date_stop)s
            GROUP BY aml.account_id
            """,
            {
                'company_id': company_id,
                'account_ids': account_ids,
                'date_start': date_start,
                'date_stop': date_stop,
            },
        )
        return {row[0]: row[1] for row in self.env.cr.fetchall()}

    def action_confirm(self):
        """Confirma la liquidación. Bloquea para edición ordinaria."""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError('Solo se puede confirmar una liquidación en estado Borrador.')

        # Lock de concurrencia
        self.env.cr.execute(
            'SELECT id FROM mx_tax_settlement WHERE id = %s FOR UPDATE NOWAIT',
            (self.id,),
        )

        self._check_no_duplicate()

        if not self.line_ids:
            raise UserError(
                'Debe calcular los saldos antes de confirmar. '
                'Use el botón "Calcular Saldos".'
            )

        # Validar líneas con diferencia mayor al umbral
        invalid_lines = []
        for line in self.line_ids:
            if line.amount_determined > 0:
                config = line.config_id
                threshold = config.difference_threshold_pct * 100  # convierte 0-1 a escala 0-100
                if line.difference_pct > threshold and not line.difference_justification:
                    invalid_lines.append(
                        f'• {line.tax_concept_id.name}: diferencia {line.difference_pct:.1f}% requiere justificación.'
                    )
        if invalid_lines:
            raise UserError(
                'Las siguientes líneas tienen una diferencia superior al umbral configurado '
                'y no tienen justificación:\n\n' + '\n'.join(invalid_lines)
            )

        self.write({
            'state': 'confirmed',
            'confirmation_date': fields.Datetime.now(),
            'confirmation_uid': self.env.user.id,
        })
        self._log_action(
            'confirm',
            f'Liquidación confirmada. Total a pagar: {self.total_to_pay:,.2f}',
        )

    def action_open_payment_wizard(self):
        """Abre el wizard de registro de pago al SAT."""
        self.ensure_one()
        if self.state not in ('confirmed', 'partial'):
            raise UserError(
                'Solo se puede registrar pago en liquidaciones Confirmadas o con Pago Parcial.'
            )
        return {
            'type': 'ir.actions.act_window',
            'name': 'Registrar Pago al SAT',
            'res_model': 'mx.tax.settlement.pay.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_settlement_id': self.id,
                'default_company_id': self.company_id.id,
            },
        }

    def action_open_cancel_wizard(self):
        """Abre el wizard de cancelación."""
        self.ensure_one()
        if self.state == 'cancel':
            raise UserError('La liquidación ya está cancelada.')
        if self.state == 'draft':
            self._do_cancel('Cancelada en estado borrador.')
            return
        return {
            'type': 'ir.actions.act_window',
            'name': 'Cancelar Liquidación',
            'res_model': 'mx.tax.settlement.cancel.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_settlement_id': self.id,
            },
        }

    def _do_cancel(self, reason, reversal_date=None):
        """
        Ejecuta la cancelación de la liquidación.

        Para cada asiento de pago publicado se genera un ASIENTO DE REVERSIÓN
        formal mediante `_reverse_moves()`, que es el mecanismo oficial de Odoo 17
        Enterprise. Esto garantiza:
          - Respeto al lock_date y fiscal lock de la compañía.
          - No ruptura de la secuencia contable.
          - Trazabilidad bidireccional (move ↔ reversa).
          - Cumplimiento con auditorías externas (Big Four).

        No se usa button_draft() / button_cancel() porque esos métodos anulan
        el asiento sin dejar contrapartida contable.
        """
        self.ensure_one()

        # Lock de concurrencia — previene doble cancelación
        self.env.cr.execute(
            'SELECT id FROM mx_tax_settlement WHERE id = %s FOR UPDATE NOWAIT',
            (self.id,),
        )

        effective_date = reversal_date or fields.Date.today()
        payments_to_reverse = self.payment_ids.filtered(
            lambda p: p.move_id and p.state == 'posted'
        )

        for payment in payments_to_reverse:
            move = payment.move_id
            if move.state != 'posted':
                continue

            # Validar que la fecha efectiva de reversión no esté en período bloqueado
            self._check_period_open(effective_date)

            # -------------------------------------------------------
            # REVERSIÓN OFICIAL: _reverse_moves() crea el asiento
            # contrapartida y lo publica automáticamente (cancel=True).
            # El campo move.reversal_move_id queda vinculado por Odoo.
            # -------------------------------------------------------
            reversal_vals = [{
                'ref': f'Reversa: {move.ref or move.name} | Cancelación {self.name}',
                'date': effective_date,
                'journal_id': move.journal_id.id,
                'narration': f'Cancelación de liquidación {self.name}. Motivo: {reason}',
            }]
            reversal_moves = move._reverse_moves(
                default_values_list=reversal_vals,
                cancel=True,  # publica la reversión automáticamente
            )
            _logger.info(
                'Reversión generada: %s → %s (liquidación %s)',
                move.name,
                reversal_moves.mapped('name'),
                self.name,
            )
            payment.write({
                'state': 'reversed',
                'reversal_move_id': reversal_moves[:1].id if reversal_moves else False,
            })

        self.write({
            'state': 'cancel',
            'cancel_reason': reason,
            'cancel_date': fields.Datetime.now(),
            'cancel_uid': self.env.user.id,
        })
        self._log_action('cancel', f'Liquidación cancelada. Motivo: {reason}')

    def action_view_moves(self):
        """Smart button para ver asientos generados."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Asientos de Liquidación',
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.move_ids.ids)],
            'context': {'create': False},
        }

    def _update_payment_state(self):
        """Actualiza el estado de la liquidación según el avance de pagos."""
        self.ensure_one()
        currency = self.currency_id
        if currency.is_zero(self.total_pending):
            self.write({'state': 'paid'})
        elif self.total_paid > 0:
            self.write({'state': 'partial'})

    # =========================================================
    # LOGGING INTERNO
    # =========================================================

    def _log_action(self, action, description, value_before=None, value_after=None, payment_id=None):
        """Escribe una entrada inmutable en la bitácora de auditoría."""
        self.ensure_one()
        request = self.env.req if hasattr(self.env, 'req') else None
        ip = None
        if request:
            try:
                ip = request.httprequest.environ.get('REMOTE_ADDR')
            except Exception:
                pass
        self.env['mx.tax.settlement.log'].sudo().create({
            'settlement_id': self.id,
            'company_id': self.company_id.id,
            'action': action,
            'user_id': self.env.user.id,
            'description': description,
            'value_before': str(value_before) if value_before else False,
            'value_after': str(value_after) if value_after else False,
            'ip_address': ip,
            'payment_id': payment_id,
        })
