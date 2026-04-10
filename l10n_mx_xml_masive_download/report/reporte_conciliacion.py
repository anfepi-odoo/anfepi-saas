# -*- coding: utf-8 -*-

from odoo import models, fields, api
from datetime import datetime
import logging

_logger = logging.getLogger(__name__)


class SatConciliationReport(models.Model):
    _name = 'sat.conciliation.report'
    _description = 'Reporte de Conciliación SAT vs Odoo'
    _order = 'sequence, id'

    sequence = fields.Integer(string='Secuencia', default=10)
    concepto = fields.Char(string='Concepto')
    company_id = fields.Many2one('res.company', string='Compañía', default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', string='Moneda', default=lambda self: self.env.company.currency_id)
    sat_xml_ids = fields.Many2many('account.edi.downloaded.xml.sat', string='XMLs del SAT', copy=False)
    odoo_invoice_ids = fields.Many2many('account.move', string='Facturas Odoo', copy=False)
    odoo_payment_ids = fields.Many2many('account.payment', string='Pagos Odoo', copy=False)
    sat_xml_count = fields.Integer(string='# XMLs SAT', compute='_compute_xml_counts')
    odoo_invoice_count = fields.Integer(string='# Facturas Odoo', compute='_compute_xml_counts')
    odoo_payment_count = fields.Integer(string='# Pagos Odoo', compute='_compute_xml_counts')
    display_name_custom = fields.Char(string='Descripción Personalizada')
    start_date = fields.Date(string='Fecha Inicial')
    end_date = fields.Date(string='Fecha Final')
    document_type = fields.Char(string='Tipo de Documento')
    section_type = fields.Selection([
        ('header_emitidos', 'Encabezado Emitidos'),
        ('emitidos_factura', 'Facturas Emitidas'),
        ('emitidos_nc', 'Notas de Crédito Emitidas'),
        ('emitidos_pago', 'Pagos Emitidos'),
        ('ignored_detail', 'Ignorados'),
        ('separator', 'Separador'),
        ('recibidos_factura', 'Facturas Recibidas'),
        ('recibidos_nc', 'Notas de Crédito Recibidas'),
        ('recibidos_pago', 'Pagos Recibidos'),
        ('header_recibidos', 'Encabezado Recibidos'),
        ('total_emitidos', 'Total Emitidos'),
        ('total_recibidos', 'Total Recibidos'),
        ('resumen', 'Resumen Ejecutivo'),
    ], string='Tipo de Sección')
    qty_sat = fields.Integer(string='# XML SAT', default=0)
    amount_sat = fields.Monetary(string='$ SAT', currency_field='currency_id', default=0.0)
    qty_odoo = fields.Integer(string='# XML Odoo', default=0)
    amount_odoo = fields.Monetary(string='$ Odoo', currency_field='currency_id', default=0.0)
    qty_ignored = fields.Integer(string='# Ignorados', default=0)
    amount_ignored = fields.Monetary(string='$ Ignorados', currency_field='currency_id', default=0.0)
    diff_qty = fields.Integer(string='Dif. XML', compute='_compute_differences', store=True)
    diff_amount = fields.Monetary(string='Dif. Importe', currency_field='currency_id',
                                  compute='_compute_differences', store=True)
    diff_percentage = fields.Float(string='Dif. %', compute='_compute_differences', store=True, digits='Percentage')
    missing_sat_count = fields.Integer(string='# SAT sin Odoo', compute='_compute_differences', store=True)
    missing_sat_amount = fields.Monetary(string='$ SAT sin Odoo', currency_field='currency_id',
                                         compute='_compute_differences', store=True)
    extra_odoo_count = fields.Integer(string='# Odoo sin SAT', compute='_compute_differences', store=True)
    extra_odoo_amount = fields.Monetary(string='$ Odoo sin SAT', currency_field='currency_id',
                                        compute='_compute_differences', store=True)
    is_header = fields.Boolean(string='Es Encabezado', default=False)
    is_total = fields.Boolean(string='Es Total', default=False)
    is_separator = fields.Boolean(string='Es Separador', default=False)
    is_subtotal = fields.Boolean(string='Es Subtotal', default=False)

    @api.depends('sat_xml_ids', 'odoo_invoice_ids', 'odoo_payment_ids')
    def _compute_xml_counts(self):
        for record in self:
            record.sat_xml_count = len(record.sat_xml_ids)
            record.odoo_invoice_count = len(record.odoo_invoice_ids)
            record.odoo_payment_count = len(record.odoo_payment_ids)

    INVOICE_SECTIONS = ('emitidos_factura', 'emitidos_nc', 'recibidos_factura', 'recibidos_nc')
    PAYMENT_SECTIONS = ('emitidos_pago', 'recibidos_pago')

    @api.depends('qty_sat', 'qty_odoo', 'amount_sat', 'amount_odoo', 'sat_xml_ids', 'odoo_invoice_ids', 'odoo_payment_ids')
    def _compute_differences(self):
        for record in self:
            diff_qty = (record.qty_sat or 0) - (record.qty_odoo or 0)
            diff_amount = (record.amount_sat or 0.0) - (record.amount_odoo or 0.0)
            missing = self.env['account.edi.downloaded.xml.sat']
            extra = self.env['account.move']
            missing_amount = 0.0
            extra_amount = 0.0

            if record.section_type in self.INVOICE_SECTIONS:
                missing, extra = record._get_invoice_mismatch()
                missing_amount = sum(x.amount_total for x in missing)
                extra_amount = sum(extra.mapped('amount_total'))
            elif record.section_type in self.PAYMENT_SECTIONS:
                missing, extra = record._get_payment_mismatch()
                missing_amount = sum(x.amount_total for x in missing)
                extra_amount = sum(extra.mapped('amount'))

            if missing or extra:
                diff_qty = len(missing) - len(extra)
                diff_amount = missing_amount - extra_amount

            record.diff_qty = diff_qty
            record.diff_amount = diff_amount
            base_amount = record.amount_sat or record.amount_odoo or abs(diff_amount)
            record.diff_percentage = diff_amount / base_amount if base_amount else 0.0
            record.missing_sat_count = len(missing)
            record.missing_sat_amount = missing_amount
            record.extra_odoo_count = len(extra)
            record.extra_odoo_amount = extra_amount

    def action_view_differences(self):
        """Acción para ver detalles de las diferencias."""
        self.ensure_one()
        if self.diff_qty == 0:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Sin Diferencias',
                    'message': f'No hay diferencias entre SAT y Odoo para {self.concepto}',
                    'type': 'success',
                    'sticky': False,
                }
            }

        if self.section_type in self.INVOICE_SECTIONS + self.PAYMENT_SECTIONS:
            if self.diff_qty > 0:
                return self.action_view_missing_sat()
            return self.action_view_extra_odoo()

        return self.action_view_sat_xmls()

    def action_view_missing_sat(self):
        """Mostrar los XML del SAT que aún no existen en Odoo."""
        self.ensure_one()
        if self.section_type in self.INVOICE_SECTIONS:
            missing, _extra = self._get_invoice_mismatch()
        elif self.section_type in self.PAYMENT_SECTIONS:
            missing, _extra = self._get_payment_mismatch()
        else:
            missing = self.env['account.edi.downloaded.xml.sat']

        if not hasattr(missing, 'ids'):
            missing_model = self.env['account.edi.downloaded.xml.sat']
            missing_ids = []
            for item in missing:
                if hasattr(item, 'id'):
                    missing_ids.append(item.id)
                else:
                    missing_ids.append(item)
            missing = missing_model.browse(missing_ids)

        if not missing:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Sin pendientes',
                    'message': 'Todos los XML del SAT ya están vinculados en Odoo.',
                    'type': 'info',
                    'sticky': False,
                }
            }

        return {
            'type': 'ir.actions.act_window',
            'name': f'SAT sin Odoo - {self.concepto}',
            'res_model': 'account.edi.downloaded.xml.sat',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', missing.ids)],
            'context': {'create': False},
        }

    def action_view_extra_odoo(self):
        """Mostrar documentos que existen en Odoo pero no en SAT."""
        self.ensure_one()
        res_model = 'account.move'
        if self.section_type in self.INVOICE_SECTIONS:
            _missing, extra = self._get_invoice_mismatch()
        elif self.section_type in self.PAYMENT_SECTIONS:
            _missing, extra = self._get_payment_mismatch()
            res_model = 'account.payment'
        else:
            extra = self.env['account.move']

        if not hasattr(extra, 'ids'):
            model = self.env[res_model]
            extra_ids = []
            for item in extra:
                if hasattr(item, 'id'):
                    extra_ids.append(item.id)
                else:
                    extra_ids.append(item)
            extra = model.browse(extra_ids)

        if not extra:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Sin pendientes',
                    'message': 'No hay documentos en Odoo sin XML correspondiente.',
                    'type': 'info',
                    'sticky': False,
                }
            }

        return {
            'type': 'ir.actions.act_window',
            'name': f'Odoo sin SAT - {self.concepto}',
            'res_model': res_model,
            'view_mode': 'tree,form',
            'domain': [('id', 'in', extra.ids)],
            'context': {'create': False},
        }

    def generate_report(self, start_date, end_date, company_id=None):
        """Genera el reporte completo."""
        if not company_id:
            company_id = self.env.company.id

        self.search([('company_id', '=', company_id)]).sudo().unlink()

        sequence = 10

        self.create({
            'sequence': sequence,
            'concepto': '═══ XML EMITIDOS ═══',
            'is_header': True,
            'start_date': start_date,
            'end_date': end_date,
            'company_id': company_id,
        })
        sequence += 10

        data_facturas_cliente = self._get_emitidos_data(start_date, end_date, 'I', 'out_invoice', company_id)
        self.create({
            'sequence': sequence,
            'section_type': 'emitidos_factura',
            'concepto': 'Facturas de Cliente (Ingreso)',
            'document_type': 'Factura',
            'qty_sat': data_facturas_cliente['qty_sat'],
            'amount_sat': data_facturas_cliente['amount_sat'],
            'qty_odoo': data_facturas_cliente['qty_odoo'],
            'amount_odoo': data_facturas_cliente['amount_odoo'],
            'qty_ignored': data_facturas_cliente['qty_ignored'],
            'amount_ignored': data_facturas_cliente['amount_ignored'],
            'sat_xml_ids': [(6, 0, data_facturas_cliente['sat_xmls'].ids)],
            'odoo_invoice_ids': [(6, 0, data_facturas_cliente['odoo_invoices'].ids)],
            'company_id': company_id,
            'start_date': start_date,
            'end_date': end_date,
        })
        sequence += 10

        data_nc_cliente = self._get_emitidos_data(start_date, end_date, 'E', 'out_refund', company_id)
        self.create({
            'sequence': sequence,
            'section_type': 'emitidos_nc',
            'concepto': 'Notas de Crédito Cliente (Egreso)',
            'document_type': 'Nota de Crédito',
            'qty_sat': data_nc_cliente['qty_sat'],
            'amount_sat': data_nc_cliente['amount_sat'],
            'qty_odoo': data_nc_cliente['qty_odoo'],
            'amount_odoo': data_nc_cliente['amount_odoo'],
            'qty_ignored': data_nc_cliente['qty_ignored'],
            'amount_ignored': data_nc_cliente['amount_ignored'],
            'sat_xml_ids': [(6, 0, data_nc_cliente['sat_xmls'].ids)],
            'odoo_invoice_ids': [(6, 0, data_nc_cliente['odoo_invoices'].ids)],
            'company_id': company_id,
            'start_date': start_date,
            'end_date': end_date,
        })
        sequence += 10

        data_pago_emitidos = self._get_emitidos_pago_data(start_date, end_date, company_id)
        self.create({
            'sequence': sequence,
            'section_type': 'emitidos_pago',
            'concepto': 'Complemento de Pago Emitidos',
            'document_type': 'Pago',
            'qty_sat': data_pago_emitidos['qty_sat'],
            'amount_sat': data_pago_emitidos['amount_sat'],
            'qty_odoo': data_pago_emitidos['qty_odoo'],
            'amount_odoo': data_pago_emitidos['amount_odoo'],
            'qty_ignored': data_pago_emitidos['qty_ignored'],
            'amount_ignored': data_pago_emitidos['amount_ignored'],
            'sat_xml_ids': [(6, 0, data_pago_emitidos['sat_xmls'].ids)],
            'odoo_payment_ids': [(6, 0, data_pago_emitidos['odoo_payments'].ids)],
            'company_id': company_id,
            'start_date': start_date,
            'end_date': end_date,
        })
        sequence += 10

        total_ignored_emitidos_qty = data_facturas_cliente['qty_ignored'] + data_nc_cliente['qty_ignored'] + data_pago_emitidos['qty_ignored']
        total_ignored_emitidos_amount = data_facturas_cliente['amount_ignored'] + data_nc_cliente['amount_ignored'] + data_pago_emitidos['amount_ignored']
        self.create({
            'sequence': sequence,
            'section_type': 'ignored_detail',
            'concepto': '⚠️ IGNORADOS EMITIDOS (Excluidos del reporte)',
            'qty_sat': 0,
            'qty_odoo': 0,
            'qty_ignored': total_ignored_emitidos_qty,
            'amount_sat': 0.0,
            'amount_odoo': 0.0,
            'amount_ignored': total_ignored_emitidos_amount,
            'company_id': company_id,
            'start_date': start_date,
            'end_date': end_date,
            'is_separator': True,
        })
        sequence += 10

        data_facturas_proveedor = self._get_recibidos_data(start_date, end_date, 'I', 'in_invoice', company_id)
        self.create({
            'sequence': sequence,
            'section_type': 'recibidos_factura',
            'concepto': 'Facturas de Proveedor (Ingreso)',
            'document_type': 'Factura',
            'qty_sat': data_facturas_proveedor['qty_sat'],
            'amount_sat': data_facturas_proveedor['amount_sat'],
            'qty_odoo': data_facturas_proveedor['qty_odoo'],
            'amount_odoo': data_facturas_proveedor['amount_odoo'],
            'qty_ignored': data_facturas_proveedor['qty_ignored'],
            'amount_ignored': data_facturas_proveedor['amount_ignored'],
            'sat_xml_ids': [(6, 0, data_facturas_proveedor['sat_xmls'].ids)],
            'odoo_invoice_ids': [(6, 0, data_facturas_proveedor['odoo_invoices'].ids)],
            'company_id': company_id,
            'start_date': start_date,
            'end_date': end_date,
        })
        sequence += 10

        data_nc_proveedor = self._get_recibidos_data(start_date, end_date, 'E', 'in_refund', company_id)
        self.create({
            'sequence': sequence,
            'section_type': 'recibidos_nc',
            'concepto': 'Notas de Crédito Proveedor (Egreso)',
            'document_type': 'Nota de Crédito',
            'qty_sat': data_nc_proveedor['qty_sat'],
            'amount_sat': data_nc_proveedor['amount_sat'],
            'qty_odoo': data_nc_proveedor['qty_odoo'],
            'amount_odoo': data_nc_proveedor['amount_odoo'],
            'qty_ignored': data_nc_proveedor['qty_ignored'],
            'amount_ignored': data_nc_proveedor['amount_ignored'],
            'sat_xml_ids': [(6, 0, data_nc_proveedor['sat_xmls'].ids)],
            'odoo_invoice_ids': [(6, 0, data_nc_proveedor['odoo_invoices'].ids)],
            'company_id': company_id,
            'start_date': start_date,
            'end_date': end_date,
        })
        sequence += 10

        data_pago_recibidos = self._get_recibidos_pago_data(start_date, end_date, company_id)
        self.create({
            'sequence': sequence,
            'section_type': 'recibidos_pago',
            'concepto': 'Complemento de Pago Recibidos',
            'document_type': 'Pago',
            'qty_sat': data_pago_recibidos['qty_sat'],
            'amount_sat': data_pago_recibidos['amount_sat'],
            'qty_odoo': data_pago_recibidos['qty_odoo'],
            'amount_odoo': data_pago_recibidos['amount_odoo'],
            'qty_ignored': data_pago_recibidos['qty_ignored'],
            'amount_ignored': data_pago_recibidos['amount_ignored'],
            'sat_xml_ids': [(6, 0, data_pago_recibidos['sat_xmls'].ids)],
            'odoo_payment_ids': [(6, 0, data_pago_recibidos['odoo_payments'].ids)],
            'company_id': company_id,
            'start_date': start_date,
            'end_date': end_date,
        })
        sequence += 10

        total_ignored_recibidos_qty = data_facturas_proveedor['qty_ignored'] + data_nc_proveedor['qty_ignored'] + data_pago_recibidos['qty_ignored']
        total_ignored_recibidos_amount = data_facturas_proveedor['amount_ignored'] + data_nc_proveedor['amount_ignored'] + data_pago_recibidos['amount_ignored']
        self.create({
            'sequence': sequence,
            'section_type': 'ignored_detail',
            'concepto': '⚠️ IGNORADOS RECIBIDOS (Excluidos del reporte)',
            'qty_sat': 0,
            'qty_odoo': 0,
            'qty_ignored': total_ignored_recibidos_qty,
            'amount_sat': 0.0,
            'amount_odoo': 0.0,
            'amount_ignored': total_ignored_recibidos_amount,
            'company_id': company_id,
            'start_date': start_date,
            'end_date': end_date,
            'is_separator': True,
        })

        start_date_str = start_date.strftime("%d/%m/%Y") if isinstance(start_date, datetime) else fields.Date.to_date(start_date).strftime("%d/%m/%Y")
        end_date_str = end_date.strftime("%d/%m/%Y") if isinstance(end_date, datetime) else fields.Date.to_date(end_date).strftime("%d/%m/%Y")

        return {
            'type': 'ir.actions.act_window',
            'name': f'Conciliación SAT vs Odoo ({start_date_str} - {end_date_str})',
            'res_model': 'sat.conciliation.report',
            'view_mode': 'tree,form,pivot',
            'target': 'current',
            'domain': [('company_id', '=', company_id)],
            'context': {'create': False, 'edit': False, 'delete': False, 'default_company_id': company_id},
        }

    def _get_invoice_mismatch(self):
        """Devuelve (XML SAT sin factura, facturas sin XML)."""
        self.ensure_one()
        xml_env = self.env['account.edi.downloaded.xml.sat']
        sat_valid = self.sat_xml_ids.filtered(lambda x: x.state not in ['ignored', 'cancel'] and x.name)
        unique_ids = []
        seen = set()
        for xml in sat_valid:
            if xml.name and xml.name not in seen:
                seen.add(xml.name)
                unique_ids.append(xml.id)
        sat_unique = xml_env.browse(unique_ids)
        sat_uuids = set(sat_unique.mapped('name'))

        odoo_invoices = self.odoo_invoice_ids.filtered(lambda x: x.l10n_mx_edi_cfdi_uuid)
        odoo_uuids = set(odoo_invoices.mapped('l10n_mx_edi_cfdi_uuid'))

        missing_uuids = sat_uuids - odoo_uuids
        extra_uuids = odoo_uuids - sat_uuids

        missing = sat_unique.filtered(lambda x: x.name in missing_uuids)
        extra = odoo_invoices.filtered(lambda x: x.l10n_mx_edi_cfdi_uuid in extra_uuids)
        return missing, extra

    def _get_payment_mismatch(self):
        """Devuelve (pagos SAT sin complemento en Odoo, pagos en Odoo sin XML)."""
        self.ensure_one()
        xml_env = self.env['account.edi.downloaded.xml.sat']
        sat_valid = self.sat_xml_ids.filtered(lambda x: x.state not in ['ignored', 'cancel'] and x.name)
        unique_ids = []
        seen = set()
        for xml in sat_valid:
            if xml.name and xml.name not in seen:
                seen.add(xml.name)
                unique_ids.append(xml.id)
        sat_unique = xml_env.browse(unique_ids)
        sat_uuids = set(sat_unique.mapped('name'))

        self.odoo_payment_ids.mapped('attachment_ids.datas')
        payment_map = {}
        extra_ids = []
        for payment in self.odoo_payment_ids:
            uuid = self._extract_payment_uuid(payment)
            if uuid:
                if uuid not in payment_map:
                    payment_map[uuid] = payment
                if uuid not in sat_uuids:
                    extra_ids.append(payment.id)
            else:
                extra_ids.append(payment.id)
        odoo_uuids = set(payment_map.keys())
        missing_uuids = sat_uuids - odoo_uuids

        missing = sat_unique.filtered(lambda x: x.name in missing_uuids)
        extra = self.env['account.payment'].browse(extra_ids)
        return missing, extra

    def _get_emitidos_data(self, start_date, end_date, document_type, move_type, company_id):
        sat_xmls = self.env['account.edi.downloaded.xml.sat'].search([
            ('cfdi_type', '=', 'emitidos'),
            ('document_type', '=', document_type),
            ('document_date', '>=', start_date),
            ('document_date', '<=', end_date),
            ('state', 'not in', ['cancel', 'ignored']),
            ('company_id', '=', company_id),
        ])

        qty_sat = len(sat_xmls)
        amount_sat = sum(sat_xmls.mapped('amount_total'))
        qty_ignored = 0
        amount_ignored = 0.0

        odoo_moves = self.env['account.move'].search([
            ('move_type', '=', move_type),
            ('invoice_date', '>=', start_date),
            ('invoice_date', '<=', end_date),
            ('state', '=', 'posted'),
            ('l10n_mx_edi_cfdi_uuid', '!=', False),
            ('company_id', '=', company_id),
        ])

        unique_uuids = set(odoo_moves.mapped('l10n_mx_edi_cfdi_uuid'))
        qty_odoo = len(unique_uuids)
        amount_odoo = sum(odoo_moves.mapped('amount_total'))

        return {
            'qty_sat': qty_sat,
            'amount_sat': amount_sat,
            'qty_odoo': qty_odoo,
            'amount_odoo': amount_odoo,
            'qty_ignored': qty_ignored,
            'amount_ignored': amount_ignored,
            'sat_xmls': sat_xmls,
            'odoo_invoices': odoo_moves,
        }

    def _get_emitidos_pago_data(self, start_date, end_date, company_id):
        sat_xmls = self.env['account.edi.downloaded.xml.sat'].search([
            ('cfdi_type', '=', 'emitidos'),
            ('document_type', '=', 'P'),
            ('document_date', '>=', start_date),
            ('document_date', '<=', end_date),
            ('state', 'not in', ['cancel', 'ignored']),
            ('company_id', '=', company_id),
        ])

        qty_sat = len(sat_xmls)
        amount_sat = sum(sat_xmls.mapped('amount_total'))
        qty_ignored = 0
        amount_ignored = 0.0

        all_payments = self.env['account.payment'].search([
            ('payment_type', '=', 'inbound'),
            ('partner_type', '=', 'customer'),
            ('date', '>=', start_date),
            ('date', '<=', end_date),
            ('state', 'not in', ['cancel', 'draft']),
            ('company_id', '=', company_id),
        ])

        odoo_payments = all_payments.filtered(
            lambda p: p.attachment_ids.filtered(lambda a: a.mimetype == 'application/xml')
        )

        qty_odoo = len(odoo_payments)
        amount_odoo = sum(odoo_payments.mapped('amount'))

        return {
            'qty_sat': qty_sat,
            'amount_sat': amount_sat,
            'qty_odoo': qty_odoo,
            'amount_odoo': amount_odoo,
            'qty_ignored': qty_ignored,
            'amount_ignored': amount_ignored,
            'sat_xmls': sat_xmls,
            'odoo_payments': odoo_payments,
        }

    def _get_recibidos_data(self, start_date, end_date, document_type, move_type, company_id):
        sat_xmls = self.env['account.edi.downloaded.xml.sat'].search([
            ('cfdi_type', '=', 'recibidos'),
            ('document_type', '=', document_type),
            ('document_date', '>=', start_date),
            ('document_date', '<=', end_date),
            ('state', 'not in', ['cancel', 'ignored']),
            ('company_id', '=', company_id),
        ])

        qty_sat = len(sat_xmls)
        amount_sat = sum(sat_xmls.mapped('amount_total'))
        qty_ignored = 0
        amount_ignored = 0.0

        odoo_moves = self.env['account.move'].search([
            ('move_type', '=', move_type),
            ('invoice_date', '>=', start_date),
            ('invoice_date', '<=', end_date),
            ('state', '=', 'posted'),
            ('company_id', '=', company_id),
        ])

        unique_uuids = set(odoo_moves.mapped('l10n_mx_edi_cfdi_uuid'))
        qty_odoo = len(unique_uuids)
        amount_odoo = sum(odoo_moves.mapped('amount_total'))

        return {
            'qty_sat': qty_sat,
            'amount_sat': amount_sat,
            'qty_odoo': qty_odoo,
            'amount_odoo': amount_odoo,
            'qty_ignored': qty_ignored,
            'amount_ignored': amount_ignored,
            'sat_xmls': sat_xmls,
            'odoo_invoices': odoo_moves,
        }

    def _get_recibidos_pago_data(self, start_date, end_date, company_id):
        sat_xmls = self.env['account.edi.downloaded.xml.sat'].search([
            ('cfdi_type', '=', 'recibidos'),
            ('document_type', '=', 'P'),
            ('document_date', '>=', start_date),
            ('document_date', '<=', end_date),
            ('state', 'not in', ['cancel', 'ignored']),
            ('company_id', '=', company_id),
        ])

        qty_sat = len(sat_xmls)
        amount_sat = sum(sat_xmls.mapped('amount_total'))
        qty_ignored = 0
        amount_ignored = 0.0

        all_payments = self.env['account.payment'].search([
            ('payment_type', '=', 'outbound'),
            ('partner_type', '=', 'supplier'),
            ('date', '>=', start_date),
            ('date', '<=', end_date),
            ('state', 'not in', ['cancel', 'draft']),
            ('company_id', '=', company_id),
        ])

        odoo_payments = all_payments.filtered(
            lambda p: p.attachment_ids.filtered(lambda a: a.mimetype == 'application/xml')
        )

        qty_odoo = len(odoo_payments)
        amount_odoo = sum(odoo_payments.mapped('amount'))

        return {
            'qty_sat': qty_sat,
            'amount_sat': amount_sat,
            'qty_odoo': qty_odoo,
            'amount_odoo': amount_odoo,
            'qty_ignored': qty_ignored,
            'amount_ignored': amount_ignored,
            'sat_xmls': sat_xmls,
            'odoo_payments': odoo_payments,
        }

    def action_view_sat_xmls(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'XMLs del SAT - {self.document_type or self.concepto}',
            'res_model': 'account.edi.downloaded.xml.sat',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', self.sat_xml_ids.ids)],
            'context': {'create': False},
        }

    def _extract_payment_uuid(self, payment):
        try:
            from lxml import etree
            import base64

            xml_attachments = payment.attachment_ids.filtered(lambda a: a.mimetype == 'application/xml')
            for attachment in xml_attachments:
                try:
                    xml_content = base64.b64decode(attachment.datas)
                    root = etree.fromstring(xml_content)
                    ns = {'tfd': 'http://www.sat.gob.mx/TimbreFiscalDigital'}
                    tfd = root.find('.//tfd:TimbreFiscalDigital', namespaces=ns)
                    if tfd is not None:
                        uuid = tfd.get('UUID')
                        if uuid:
                            return uuid
                except (etree.XMLSyntaxError, ValueError) as err:
                    _logger.debug("Attachment %s is not valid XML: %s", attachment.name, err)
        except (KeyError, AttributeError) as err:
            _logger.warning("Error extracting payment UUID from %s: %s", payment.name, err)
        return None

    def action_view_odoo_invoices(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Facturas Odoo - {self.document_type or self.concepto}',
            'res_model': 'account.move',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', self.odoo_invoice_ids.ids)],
            'context': {'create': False},
        }

    def action_view_odoo_payments(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Pagos Odoo - {self.document_type or self.concepto}',
            'res_model': 'account.payment',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', self.odoo_payment_ids.ids)],
            'context': {'create': False},
        }

    def action_view_odoo_documents(self):
        """Abre facturas o pagos según el tipo de sección."""
        self.ensure_one()
        if self.section_type in self.PAYMENT_SECTIONS:
            return self.action_view_odoo_payments()
        return self.action_view_odoo_invoices()

    def generateReport(self, start_date, end_date, company_id=None):
        from datetime import date
        if not start_date:
            start_date = date(date.today().year, 1, 1)
        if not end_date:
            end_date = date.today()
        if not company_id:
            company_id = self.env.company.id
        return self.generate_report(start_date, end_date, company_id)

    def _get_invoice_mismatch(self):
        """Regresa los XML faltantes y las facturas extra."""
        sat_valid = self.sat_xml_ids.filtered(lambda x: x.state not in ['ignored', 'cancel'] and x.name)
        sat_map = {}
        for xml in sat_valid:
            sat_map.setdefault(xml.name, []).append(xml)

        odoo_invoices = self.odoo_invoice_ids.filtered(lambda x: x.l10n_mx_edi_cfdi_uuid)
        odoo_map = {inv.l10n_mx_edi_cfdi_uuid: inv for inv in odoo_invoices}

        missing = [records[0] for uuid, records in sat_map.items() if uuid not in odoo_map]
        extra = odoo_invoices.filtered(lambda inv: inv.l10n_mx_edi_cfdi_uuid not in sat_map)
        return missing, extra

    def _get_payment_mismatch(self):
        """Regresa los pagos XML faltantes y los pagos extra en Odoo."""
        sat_valid = self.sat_xml_ids.filtered(lambda x: x.state not in ['ignored', 'cancel'] and x.name)
        sat_map = {}
        for xml in sat_valid:
            sat_map.setdefault(xml.name, []).append(xml)

        self.odoo_payment_ids.mapped('attachment_ids.datas')
        payment_map = {}
        extra_ids = []
        for payment in self.odoo_payment_ids:
            uuid = self._extract_payment_uuid(payment)
            if uuid:
                payment_map[uuid] = payment
                if uuid not in sat_map:
                    extra_ids.append(payment.id)
        missing = [records[0] for uuid, records in sat_map.items() if uuid not in payment_map]
        extra = self.env['account.payment'].browse(extra_ids)
        return missing, extra
