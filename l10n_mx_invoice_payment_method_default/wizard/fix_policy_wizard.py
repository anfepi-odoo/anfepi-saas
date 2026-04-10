# -*- coding: utf-8 -*-
"""
Wizard para corregir masivamente la Política de Pago (PPD/PUE) en facturas
de cliente cuyo campo l10n_mx_edi_payment_policy quedó incorrecto después
de la actualización a Odoo v19 (donde el campo pasó de computed a Selection).

Fuente de verdad
----------------
1. XML CFDI timbrado (campo MetodoPago): fuente más confiable, refleja exactamente
   lo que se envió al SAT. Se usa cuando el XML está disponible.
2. Término de pago (invoice_payment_term_id): fallback cuando el XML no está
   disponible (facturas en borrador o sin CFDI adjunto).

Casos cubiertos
---------------
* Facturas publicadas con CFDI: lee MetodoPago del XML → corrige solo el campo
  l10n_mx_edi_payment_policy (no toca forma de pago, el XML ya fue emitido).
* Facturas publicadas sin CFDI: usa el término de pago como fallback.
* Facturas en borrador: usa el término de pago y también corrige la forma (99/03).
"""
import base64
import logging
from lxml import etree
from odoo import models, fields, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Namespaces CFDI soportados
_CFDI_NS = {
    '4': 'http://www.sat.gob.mx/cfd/4',
    '3': 'http://www.sat.gob.mx/cfd/3',
}


class FixPolicyWizard(models.TransientModel):
    _name = 'l10n_mx.fix.policy.wizard'
    _description = 'Corregir Política PPD/PUE en Facturas Históricas v19'

    # ── Filtros ──────────────────────────────────────────────────────────────
    fix_draft = fields.Boolean(
        string='Corregir borradores',
        default=True,
        help='Corrige política Y forma de pago en facturas en estado Borrador '
             '(fuente: término de pago).'
    )
    fix_posted = fields.Boolean(
        string='Corregir publicadas (posted)',
        default=True,
        help='Corrige SOLO la política PPD/PUE en facturas ya publicadas/firmadas. '
             'La forma de pago NO se modifica (el XML ya fue emitido).'
    )
    only_wrong = fields.Boolean(
        string='Solo las que estén incorrectas',
        default=True,
        help='Si está activo, solo procesa las facturas donde la política actual '
             'no coincide con la que corresponde al XML o al término de pago.'
    )

    # ── Resultados (solo lectura) ─────────────────────────────────────────────
    count_draft = fields.Integer(string='Borradores a corregir', readonly=True)
    count_posted = fields.Integer(string='Publicadas a corregir', readonly=True)
    count_from_xml = fields.Integer(string='Leídas desde XML CFDI', readonly=True)
    count_from_term = fields.Integer(string='Leídas desde término de pago', readonly=True)
    count_fixed = fields.Integer(string='Registros corregidos', readonly=True)
    count_errors = fields.Integer(string='Errores', readonly=True)
    state = fields.Selection(
        [('draft', 'Pendiente'), ('done', 'Completado')],
        default='draft',
        readonly=True,
    )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _policy_from_cfdi(self, move):
        """
        Lee MetodoPago directamente del XML CFDI timbrado.
        Retorna 'PPD', 'PUE' o None si no hay XML disponible.

        Busca en:
        1. move.l10n_mx_edi_document_ids → attachment más reciente con estado válido
        2. Attachments del move con nombre *.xml como fallback
        """
        # ── Método 1: documentos EDI (Odoo 17+/19) ───────────────────────────
        edi_docs = getattr(move, 'l10n_mx_edi_document_ids', None)
        if edi_docs:
            # Buscar el documento firmado más reciente
            valid_states = ('invoice_sent', 'invoice_sent_failed', 'invoice_cancel',
                            'invoice_cancel_requested', 'sent')
            for doc in edi_docs.sorted('id', reverse=True):
                doc_state = getattr(doc, 'state', '') or ''
                attachment = getattr(doc, 'attachment_id', None)
                if attachment and attachment.datas:
                    policy = self._parse_metodo_pago(attachment.datas)
                    if policy:
                        return policy, 'xml'

        # ── Método 2: adjuntos con .xml en el nombre ──────────────────────────
        xml_attachments = self.env['ir.attachment'].search([
            ('res_model', '=', 'account.move'),
            ('res_id', '=', move.id),
            ('name', 'like', '.xml'),
        ], order='id desc', limit=5)

        for att in xml_attachments:
            if att.datas:
                policy = self._parse_metodo_pago(att.datas)
                if policy:
                    return policy, 'xml'

        # ── Sin XML: usar término de pago como fallback ───────────────────────
        policy = self.env['account.move']._get_policy_from_term(
            move.invoice_payment_term_id
        )
        return policy, 'term'

    def _parse_metodo_pago(self, datas_b64):
        """
        Parsea un XML CFDI (base64) y extrae el atributo MetodoPago.
        Retorna 'PPD', 'PUE' o None.
        """
        try:
            xml_bytes = base64.b64decode(datas_b64)
            root = etree.fromstring(xml_bytes)
            # El atributo puede estar con o sin namespace
            metodo = root.get('MetodoPago')
            if metodo in ('PPD', 'PUE'):
                return metodo
            # Intentar con namespace explícito
            for ver, ns in _CFDI_NS.items():
                metodo = root.get(f'{{{ns}}}MetodoPago')
                if metodo in ('PPD', 'PUE'):
                    return metodo
        except Exception as e:
            _logger.debug("_parse_metodo_pago: no se pudo parsear XML: %s", e)
        return None

    def _get_candidate_moves(self):
        states = []
        if self.fix_draft:
            states.append('draft')
        if self.fix_posted:
            states.append('posted')
        if not states:
            raise UserError(_('Debes seleccionar al menos un estado a corregir.'))
        return self.env['account.move'].search(
            [('move_type', '=', 'out_invoice'), ('state', 'in', states)],
            order='id'
        )

    # ── Acciones ──────────────────────────────────────────────────────────────

    def action_preview(self):
        """Calcula cuántas facturas serán afectadas sin modificar nada."""
        moves = self._get_candidate_moves()
        draft_count = posted_count = xml_count = term_count = 0

        for move in moves:
            expected_policy, source = self._policy_from_cfdi(move)
            current = move.l10n_mx_edi_payment_policy

            if self.only_wrong and current == expected_policy:
                continue

            if source == 'xml':
                xml_count += 1
            else:
                term_count += 1

            if move.state == 'draft':
                draft_count += 1
            else:
                posted_count += 1

        self.count_draft = draft_count
        self.count_posted = posted_count
        self.count_from_xml = xml_count
        self.count_from_term = term_count

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_fix(self):
        """
        Corrección masiva:
        - posted: lee MetodoPago del XML CFDI → actualiza solo l10n_mx_edi_payment_policy
        - draft:  usa término de pago → actualiza política Y forma de pago (99/03)
        """
        moves = self._get_candidate_moves()
        forma_99 = self.env['l10n_mx_edi.payment.method'].search(
            [('code', '=', '99')], limit=1)
        forma_03 = self.env['l10n_mx_edi.payment.method'].search(
            [('code', '=', '03')], limit=1)

        fixed = errors = xml_count = term_count = 0

        for move in moves:
            expected_policy, source = self._policy_from_cfdi(move)
            current_policy = move.l10n_mx_edi_payment_policy

            if self.only_wrong and current_policy == expected_policy:
                continue

            update = {}

            # ── Política de pago ──────────────────────────────────────────────
            if current_policy != expected_policy:
                update['l10n_mx_edi_payment_policy'] = expected_policy

            # ── Forma de pago (solo borradores) ───────────────────────────────
            if move.state == 'draft':
                current_code = (
                    move.l10n_mx_edi_payment_method_id.code
                    if move.l10n_mx_edi_payment_method_id else ''
                )
                if expected_policy == 'PPD' and current_code != '99' and forma_99:
                    update['l10n_mx_edi_payment_method_id'] = forma_99.id
                elif expected_policy == 'PUE' and current_code == '99' and forma_03:
                    update['l10n_mx_edi_payment_method_id'] = forma_03.id

            if update:
                try:
                    move.sudo().with_context(_skip_policy_sync=True).write(update)
                    fixed += 1
                    if source == 'xml':
                        xml_count += 1
                    else:
                        term_count += 1
                    _logger.info(
                        "FixPolicy: %s [%s] fuente=%s policy %s→%s cambios=%s",
                        move.name, move.state, source,
                        current_policy, expected_policy, list(update.keys())
                    )
                except Exception as exc:
                    errors += 1
                    _logger.warning(
                        "FixPolicy: no se pudo corregir %s: %s", move.name, exc
                    )

        self.count_fixed = fixed
        self.count_errors = errors
        self.count_from_xml = xml_count
        self.count_from_term = term_count
        self.state = 'done'

        _logger.info(
            "FixPolicyWizard completado: %d corregidas (%d desde XML, %d desde término), "
            "%d errores.", fixed, xml_count, term_count, errors
        )

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
