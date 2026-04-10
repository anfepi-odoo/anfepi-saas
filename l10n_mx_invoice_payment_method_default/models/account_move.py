# -*- coding: utf-8 -*-
from odoo import models, fields, api
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'

    # -------------------------------------------------------------------------
    # CAMPO: quitar domain restrictivo de l10n_mx_edi que oculta "99 Por Definir"
    # -------------------------------------------------------------------------
    # En Odoo v19, l10n_mx_edi declara l10n_mx_edi_payment_method_id con un domain
    # que filtra la opción "99 Por Definir" cuando la política no es PPD.
    # Al redeclararla aquí con domain=[] anulamos esa restricción a nivel ORM.
    # La validación PPD↔99 y PUE↔!99 la gestiona nuestro código Python.
    l10n_mx_edi_payment_method_id = fields.Many2one(
        comodel_name='l10n_mx_edi.payment.method',
        domain=[],
        # active_test=False: muestra el registro '99 Por Definir' aunque tenga
        # active=False en la BD (Odoo v19 lo desactiva por defecto)
        context={'active_test': False},
        string='Forma de pago',
    )

    # -------------------------------------------------------------------------
    # HELPER
    # -------------------------------------------------------------------------

    def _get_policy_from_term(self, term):
        """
        Determina PPD o PUE desde el término de pago. Orden de prioridad:

        1. Campo l10n_mx_edi_payment_policy en account.payment.term
           (campo del módulo MX en el TÉRMINO, no en la factura).
           Cubre casos como "Pago inmediato PPD" (0 días pero PPD).

        2. Días de crédito: si alguna línea tiene días > 0 → PPD.

        3. Default: PUE (pago inmediato sin crédito).

        NOTA: l10n_mx_edi_payment_policy en account.MOVE (no en el term)
        es un campo Selection MANUAL desde v19. Este módulo lo escribe
        explícitamente en create(), write() y onchange().
        """
        if not term:
            return 'PUE'

        # 1. Campo oficial del módulo MX en el TÉRMINO de pago
        term_policy = getattr(term, 'l10n_mx_edi_payment_policy', None)
        if term_policy in ('PPD', 'PUE'):
            return term_policy

        # 2. Días de crédito (days en v18/v19, nb_days en v17)
        def _days(line):
            return getattr(line, 'days', 0) or getattr(line, 'nb_days', 0)
        if term.line_ids and any(_days(line) > 0 for line in term.line_ids):
            return 'PPD'

        return 'PUE'

    def _sync_policy_and_method(self, policy, forma_99, forma_03):
        """
        Aplica la policy y ajusta la forma de pago en self (un solo move).
        Se usa tanto en create() como en write() para centralizar la lógica.
        Solo actúa sobre out_invoice en borrador.
        Retorna True si hubo cambios que requieren persistencia (para write()).
        """
        if self.move_type != 'out_invoice':
            return False

        update = {}

        # --- Política de pago (campo manual desde v19) ---
        if self.l10n_mx_edi_payment_policy != policy:
            update['l10n_mx_edi_payment_policy'] = policy

        # --- Forma de pago ---
        current_code = self.l10n_mx_edi_payment_method_id.code if self.l10n_mx_edi_payment_method_id else ''

        if policy == 'PPD':
            if current_code != '99' and forma_99:
                update['l10n_mx_edi_payment_method_id'] = forma_99.id
        else:  # PUE
            if current_code == '99':
                client_method = self.partner_id.l10n_mx_edi_payment_method_id
                if client_method and client_method.code != '99':
                    update['l10n_mx_edi_payment_method_id'] = client_method.id
                elif forma_03:
                    update['l10n_mx_edi_payment_method_id'] = forma_03.id
            elif not current_code:
                # Sin forma aún: asignar cliente o 03
                client_method = self.partner_id.l10n_mx_edi_payment_method_id
                if client_method and client_method.code != '99':
                    update['l10n_mx_edi_payment_method_id'] = client_method.id
                elif forma_03:
                    update['l10n_mx_edi_payment_method_id'] = forma_03.id

        if update:
            _logger.info(
                "Factura %s: sincronizando policy=%s, cambios=%s",
                self.name or self.id, policy, list(update.keys())
            )
        return update

    def _get_payment_forms(self):
        """
        Carga formas 99 y 03. Usa active_test=False para encontrar el registro
        code=99 aunque Odoo v19 lo tenga marcado como active=False.
        """
        Method = self.env['l10n_mx_edi.payment.method'].with_context(active_test=False)
        forma_99 = Method.search([('code', '=', '99')], limit=1)
        forma_03 = Method.search([('code', '=', '03')], limit=1)
        return forma_99, forma_03

    # -------------------------------------------------------------------------
    # CREATE
    # -------------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        """
        Override create: establece política PPD/PUE Y forma de pago correcta.

        CAMBIO v19: l10n_mx_edi_payment_policy ya no es computed — hay que
        escribirlo explícitamente tanto en create() como en write().
        """
        moves = super().create(vals_list)
        forma_99, forma_03 = self._get_payment_forms()

        for move in moves:
            if move.move_type != 'out_invoice' or not move.partner_id:
                continue

            policy = self._get_policy_from_term(move.invoice_payment_term_id)
            update = move._sync_policy_and_method(policy, forma_99, forma_03)
            if update:
                # Escribir directamente en BD (sin pasar por write() override de nuevo)
                move.with_context(_skip_policy_sync=True).write(update)

        return moves

    # -------------------------------------------------------------------------
    # ONCHANGE (interfaz de usuario)
    # -------------------------------------------------------------------------

    @api.onchange('partner_id')
    def _onchange_partner_payment_method(self):
        """Al cambiar el cliente, heredar su forma de pago si es compatible."""
        if self.move_type != 'out_invoice' or not self.partner_id:
            return

        policy = self._get_policy_from_term(self.invoice_payment_term_id)
        # Actualizar el campo visible de política
        self.l10n_mx_edi_payment_policy = policy

        forma_99, forma_03 = self._get_payment_forms()
        client_method = self.partner_id.l10n_mx_edi_payment_method_id

        if policy == 'PPD':
            if forma_99:
                self.l10n_mx_edi_payment_method_id = forma_99
        else:
            if client_method and client_method.code != '99':
                self.l10n_mx_edi_payment_method_id = client_method
            elif forma_03:
                self.l10n_mx_edi_payment_method_id = forma_03

    @api.onchange('invoice_payment_term_id')
    def _onchange_payment_term_adjust_method(self):
        """
        Al cambiar el término de pago, actualizar TANTO la política PPD/PUE
        COMO la forma de pago.

        CRÍTICO v19: l10n_mx_edi_payment_policy ya no es computed.
        Este onchange es ahora el responsable de actualizar el campo visible
        cuando el usuario cambia el término de pago en la pantalla.
        """
        if self.move_type != 'out_invoice':
            return

        policy = self._get_policy_from_term(self.invoice_payment_term_id)

        # v19: escribir explícitamente la política
        self.l10n_mx_edi_payment_policy = policy

        forma_99, forma_03 = self._get_payment_forms()
        current_code = self.l10n_mx_edi_payment_method_id.code if self.l10n_mx_edi_payment_method_id else ''

        if policy == 'PPD':
            if current_code != '99' and forma_99:
                self.l10n_mx_edi_payment_method_id = forma_99
                _logger.info("%s: término PPD → política PPD, forma 99", self.name)
        else:
            if current_code == '99':
                client_method = self.partner_id.l10n_mx_edi_payment_method_id
                if client_method and client_method.code != '99':
                    self.l10n_mx_edi_payment_method_id = client_method
                elif forma_03:
                    self.l10n_mx_edi_payment_method_id = forma_03
                    _logger.info("%s: término PUE → política PUE, forma 03", self.name)

    @api.onchange('invoice_date')
    def _onchange_invoice_date_policy(self):
        """
        Al cambiar la fecha de factura, recalcular la política PPD/PUE.

        Algunos términos de pago tienen líneas relativas a la fecha: si la fecha
        cambia, el vencimiento cambia y la política puede cambiar también.
        """
        if self.move_type != 'out_invoice' or not self.invoice_payment_term_id:
            return

        policy = self._get_policy_from_term(self.invoice_payment_term_id)
        if self.l10n_mx_edi_payment_policy != policy:
            self.l10n_mx_edi_payment_policy = policy
            forma_99, forma_03 = self._get_payment_forms()
            current_code = self.l10n_mx_edi_payment_method_id.code if self.l10n_mx_edi_payment_method_id else ''
            if policy == 'PPD' and current_code != '99' and forma_99:
                self.l10n_mx_edi_payment_method_id = forma_99
            elif policy == 'PUE' and current_code == '99' and forma_03:
                self.l10n_mx_edi_payment_method_id = forma_03

    @api.onchange('l10n_mx_edi_payment_policy')
    def _onchange_payment_policy_adjust_method(self):
        """
        Reacciona cuando el usuario cambia manualmente el campo política PPD/PUE.

        CAMBIO v19: ahora SÍ se dispara (campo Selection manual), así el usuario
        puede cambiar la política y automáticamente se ajusta la forma de pago.
        """
        if self.move_type != 'out_invoice' or not self.l10n_mx_edi_payment_policy:
            return

        forma_99, forma_03 = self._get_payment_forms()
        current_code = self.l10n_mx_edi_payment_method_id.code if self.l10n_mx_edi_payment_method_id else ''

        if self.l10n_mx_edi_payment_policy == 'PPD':
            if current_code != '99' and forma_99:
                self.l10n_mx_edi_payment_method_id = forma_99

        elif self.l10n_mx_edi_payment_policy == 'PUE':
            if current_code == '99':
                client_method = self.partner_id.l10n_mx_edi_payment_method_id
                if client_method and client_method.code != '99':
                    self.l10n_mx_edi_payment_method_id = client_method
                elif forma_03:
                    self.l10n_mx_edi_payment_method_id = forma_03

    # -------------------------------------------------------------------------
    # WRITE
    # -------------------------------------------------------------------------

    def write(self, vals):
        """
        Override write:
        1. Si cambia el término o fecha → recalcular y guardar política PPD/PUE
           Y ajustar forma de pago (CRÍTICO v19: campo ya no es computed).
        2. Si se modifica la forma de pago manualmente → validar consistencia
           con la política actual.

        Se usa _skip_policy_sync en el contexto para evitar recursión.
        """
        # Evitar recursión cuando este mismo método hace un write interno
        if self.env.context.get('_skip_policy_sync'):
            return super().write(vals)

        result = super().write(vals)

        # ── Bloque 1: sincronizar política cuando cambia el término o la fecha ──
        term_or_date_changed = (
            'invoice_payment_term_id' in vals or 'invoice_date' in vals
        )
        if term_or_date_changed:
            forma_99, forma_03 = self._get_payment_forms()
            for move in self:
                if move.move_type != 'out_invoice' or move.state != 'draft':
                    continue
                policy = self._get_policy_from_term(move.invoice_payment_term_id)
                update = move._sync_policy_and_method(policy, forma_99, forma_03)
                if update:
                    move.with_context(_skip_policy_sync=True).write(update)

        # ── Bloque 2: validar si se cambió manualmente la forma de pago ──
        if 'l10n_mx_edi_payment_method_id' not in vals:
            return result

        new_method_id = vals.get('l10n_mx_edi_payment_method_id')
        if not new_method_id:
            return result

        new_method = self.env['l10n_mx_edi.payment.method'].browse(new_method_id)
        method_code = new_method.code if new_method else ''

        for move in self:
            if move.move_type != 'out_invoice' or move.state != 'draft':
                continue

            # En v19 la política es el valor guardado en el campo (ya actualizado)
            policy = move.l10n_mx_edi_payment_policy

            if not policy:
                _logger.info(
                    "write() validación omitida: %s sin policy (sin fecha/término)",
                    move.name
                )
                continue

            _logger.info(
                "write() validación: move=%s, policy=%s, method_code=%s",
                move.name, policy, method_code
            )

            if policy == 'PUE' and method_code == '99':
                raise UserError(
                    "⚠️ RESTRICCIÓN FISCAL SAT\n\n"
                    "Política de Pago: PUE (Pago en Una Exhibición)\n"
                    "Forma de Pago: 99 (Por Definir)\n\n"
                    "❌ Esta combinación NO es válida ante el SAT.\n\n"
                    "SOLUCIÓN:\n"
                    "• Cambie la Forma de Pago a una específica:\n"
                    "  - 01 - Efectivo\n"
                    "  - 03 - Transferencia Electrónica (recomendado)\n"
                    "  - 04 - Tarjeta de Crédito\n"
                    "  - 28 - Tarjeta de Débito\n\n"
                    "O cambie la Política de Pago a PPD si el pago será diferido."
                )

            if policy == 'PPD' and method_code != '99':
                raise UserError(
                    "⚠️ RESTRICCIÓN FISCAL SAT\n\n"
                    "Política de Pago: PPD (Pago en Parcialidades o Diferido)\n"
                    f"Forma de Pago: {method_code} - {new_method.name}\n\n"
                    "❌ PPD DEBE usar forma de pago '99 - Por Definir'\n\n"
                    "RAZÓN:\n"
                    "En pagos diferidos, la forma exacta no se conoce al\n"
                    "emitir la factura. El SAT requiere '99 - Por Definir'.\n\n"
                    "SOLUCIÓN:\n"
                    "• Cambie la Forma de Pago a '99 - Por Definir'\n\n"
                    "O si el pago es inmediato, cambie la Política a PUE."
                )

        return result
