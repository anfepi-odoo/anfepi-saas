# -*- coding: utf-8 -*-
from odoo import fields, models, api
from datetime import date

class ReporteConciliacion(models.Model):
    _name = 'sat.conciliation.report'
    _description = "Reporte de Conciliación SAT vs Odoo"
    _order = 'sequence, id'
 
    sequence = fields.Integer(string='Secuencia', default=10)
    section_type = fields.Selection([
        ('header_emitidos', 'Encabezado Emitidos'),
        ('data_emitidos', 'Datos Emitidos'),
        ('ignored_emitidos', 'Ignorados Emitidos'),
        ('total_emitidos', 'Total Emitidos'),
        ('separator', 'Separador'),
        ('header_recibidos', 'Encabezado Recibidos'),
        ('data_recibidos', 'Datos Recibidos'),
        ('ignored_recibidos', 'Ignorados Recibidos'),
        ('total_recibidos', 'Total Recibidos'),
        ('resumen', 'Resumen Ejecutivo'),
    ], string='Tipo de Sección')
    
    # Información del concepto
    concepto = fields.Char(string='Concepto', index=True)
    document_type = fields.Char(string='Tipo de Documento')
    
    # Columnas SAT
    qty_sat = fields.Integer(string="# XML SAT")
    amount_sat = fields.Monetary(string="$ SAT", currency_field='currency_id')
    
    # Columnas Odoo
    qty_odoo = fields.Integer(string="# XML Odoo")
    amount_odoo = fields.Monetary(string="$ Odoo", currency_field='currency_id')
    
    # Columnas Ignorados
    qty_ignored = fields.Integer(string="# Ignorados")
    amount_ignored = fields.Monetary(string="$ Ignorados", currency_field='currency_id')
    
    # Columnas Diferencias (Calculadas)
    diff_qty = fields.Integer(string="Dif. XML", compute='_compute_diferencias', store=True)
    diff_amount = fields.Monetary(string="Dif. Importe $", currency_field='currency_id', compute='_compute_diferencias', store=True)
    diff_percentage = fields.Float(string="Dif. %", compute='_compute_diferencias', store=True, digits=(5, 2))
    
    # Estado de conciliación
    status = fields.Selection([
        ('ok', 'Conciliado'),
        ('difference', 'Con Diferencias'),
        ('missing', 'Faltantes en Odoo'),
        ('extra', 'Extras en Odoo'),
    ], string='Estado', compute='_compute_status', store=True)
    
    # Campos de filtro
    start_date = fields.Date(string='Fecha Inicio', default=lambda self: date(date.today().year, 1, 1))
    end_date = fields.Date(string='Fecha Fin', default=fields.Date.today)
    currency_id = fields.Many2one('res.currency', string='Moneda', default=lambda self: self.env.company.currency_id)
    company_id = fields.Many2one('res.company', string='Compañía', default=lambda self: self.env.company)
    
    # Campos computados para estilos y formato
    is_header = fields.Boolean(compute='_compute_is_header', store=False)
    is_total = fields.Boolean(compute='_compute_is_total', store=False)
    is_separator = fields.Boolean(compute='_compute_is_separator', store=False)
    is_subtotal = fields.Boolean(compute='_compute_is_subtotal', store=False)
    display_name_custom = fields.Char(string='Descripción', compute='_compute_display_name_custom', store=False)
    
    # Campos para drill-down a XMLs
    sat_xml_ids = fields.Many2many('account.edi.downloaded.xml.sat', 'conciliation_sat_xml_rel', 
                                    'conciliation_id', 'xml_id', string='XMLs del SAT')
    odoo_invoice_ids = fields.Many2many('account.move', 'conciliation_odoo_invoice_rel', 
                                         'conciliation_id', 'invoice_id', string='Facturas Odoo')
    odoo_payment_ids = fields.Many2many('account.payment', 'conciliation_odoo_payment_rel', 
                                         'conciliation_id', 'payment_id', string='Pagos Odoo')
    
    # Contadores para botones inteligentes
    sat_xml_count = fields.Integer(compute='_compute_xml_counts', string='# XMLs SAT')
    odoo_invoice_count = fields.Integer(compute='_compute_xml_counts', string='# Facturas Odoo')
    odoo_payment_count = fields.Integer(compute='_compute_xml_counts', string='# Pagos Odoo')
    
    @api.depends('sat_xml_ids', 'odoo_invoice_ids', 'odoo_payment_ids')
    def _compute_xml_counts(self):
        for record in self:
            record.sat_xml_count = len(record.sat_xml_ids)
            record.odoo_invoice_count = len(record.odoo_invoice_ids)
            record.odoo_payment_count = len(record.odoo_payment_ids)

    @api.depends('qty_sat', 'qty_odoo', 'qty_ignored', 'amount_sat', 'amount_odoo', 'amount_ignored')
    def _compute_diferencias(self):
        for record in self:
            # Calcular diferencias
            record.diff_qty = record.qty_odoo - record.qty_sat
            record.diff_amount = record.amount_odoo - record.amount_sat
            
            # Calcular porcentaje de diferencia (como decimal para widget percentage)
            if record.amount_sat != 0:
                # Caso normal: SAT tiene cifra, calcular % sobre SAT
                record.diff_percentage = (record.amount_odoo - record.amount_sat) / abs(record.amount_sat)
            elif record.amount_odoo != 0:
                # Caso especial: SAT = 0 pero Odoo tiene cifra = 100% de diferencia
                record.diff_percentage = 1.0
            else:
                # Ambos son 0, no hay diferencia
                record.diff_percentage = 0.0
    
    @api.depends('diff_qty', 'diff_amount')
    def _compute_status(self):
        for record in self:
            if record.section_type in ['header_emitidos', 'header_recibidos', 'separator', 'total_emitidos', 'total_recibidos', 'resumen']:
                record.status = False
            elif record.diff_qty == 0 and abs(record.diff_amount) < 0.01:
                record.status = 'ok'
            elif record.diff_qty < 0:
                record.status = 'missing'
            elif record.diff_qty > 0:
                record.status = 'extra'
            else:
                record.status = 'difference'

    @api.depends('section_type')
    def _compute_is_header(self):
        for record in self:
            record.is_header = record.section_type in ['header_emitidos', 'header_recibidos', 'resumen']
    
    @api.depends('section_type')
    def _compute_is_total(self):
        for record in self:
            record.is_total = record.section_type in ['total_emitidos', 'total_recibidos']
    
    @api.depends('section_type')
    def _compute_is_separator(self):
        for record in self:
            record.is_separator = record.section_type == 'separator'
    
    @api.depends('section_type')
    def _compute_is_subtotal(self):
        for record in self:
            record.is_subtotal = record.section_type in ['ignored_emitidos', 'ignored_recibidos']
    
    @api.depends('concepto', 'document_type', 'section_type')
    def _compute_display_name_custom(self):
        for record in self:
            if record.section_type in ['header_emitidos', 'header_recibidos']:
                record.display_name_custom = record.concepto or ''
            elif record.section_type in ['total_emitidos', 'total_recibidos']:
                record.display_name_custom = '► ' + (record.concepto or '')
            elif record.section_type == 'separator':
                record.display_name_custom = ''
            else:
                record.display_name_custom = '   ' + (record.document_type or record.concepto or '')

    def generate_report(self, start_date, end_date):
        """Genera el reporte de conciliación con todas las secciones"""
        if not start_date:
            start_date = date(date.today().year, 1, 1)
        if not end_date:
            end_date = date.today()   

        # Limpiar reporte anterior
        self.search([]).unlink()  
        
        report_lines = []
        sequence = 1

        # =====================================================================
        # SECCIÓN: XML EMITIDOS
        # =====================================================================
        
        # Header Emitidos
        report_lines.append({
            'sequence': sequence,
            'section_type': 'header_emitidos',
            'concepto': '═══ XML EMITIDOS ═══',
            'document_type': '',
            'start_date': start_date,
            'end_date': end_date,
        })
        sequence += 1

        # 1. Facturas de Cliente (Ingreso)
        emitidos_data = self._get_emitidos_data(start_date, end_date, 'I', 'out_invoice')
        report_lines.append({
            'sequence': sequence,
            'section_type': 'data_emitidos',
            'document_type': 'Facturas de Cliente (Ingreso)',
            'qty_sat': emitidos_data['qty_sat'],
            'amount_sat': emitidos_data['amount_sat'],
            'qty_odoo': emitidos_data['qty_odoo'],
            'amount_odoo': emitidos_data['amount_odoo'],
            'qty_ignored': emitidos_data['qty_ignored'],
            'amount_ignored': emitidos_data['amount_ignored'],
            'sat_xml_ids': [(6, 0, emitidos_data.get('sat_xml_ids', []))],
            'odoo_invoice_ids': [(6, 0, emitidos_data.get('odoo_invoice_ids', []))],
            'start_date': start_date,
            'end_date': end_date,
        })
        sequence += 1

        # 2. Notas de Crédito (Egreso)
        emitidos_nc = self._get_emitidos_data(start_date, end_date, 'E', 'out_refund')
        report_lines.append({
            'sequence': sequence,
            'section_type': 'data_emitidos',
            'document_type': 'Notas de Crédito Cliente (Egreso)',
            'qty_sat': emitidos_nc['qty_sat'],
            'amount_sat': emitidos_nc['amount_sat'],
            'qty_odoo': emitidos_nc['qty_odoo'],
            'amount_odoo': emitidos_nc['amount_odoo'],
            'qty_ignored': emitidos_nc['qty_ignored'],
            'amount_ignored': emitidos_nc['amount_ignored'],
            'sat_xml_ids': [(6, 0, emitidos_nc.get('sat_xml_ids', []))],
            'odoo_invoice_ids': [(6, 0, emitidos_nc.get('odoo_invoice_ids', []))],
            'start_date': start_date,
            'end_date': end_date,
        })
        sequence += 1

        # 3. Complemento de Pago Emitidos
        emitidos_pago = self._get_emitidos_pago_data(start_date, end_date)
        report_lines.append({
            'sequence': sequence,
            'section_type': 'data_emitidos',
            'document_type': 'Complemento de Pago Emitidos',
            'qty_sat': emitidos_pago['qty_sat'],
            'amount_sat': emitidos_pago['amount_sat'],
            'qty_odoo': emitidos_pago['qty_odoo'],
            'amount_odoo': emitidos_pago['amount_odoo'],
            'qty_ignored': emitidos_pago['qty_ignored'],
            'amount_ignored': emitidos_pago['amount_ignored'],
            'sat_xml_ids': [(6, 0, emitidos_pago.get('sat_xml_ids', []))],
            'odoo_payment_ids': [(6, 0, emitidos_pago.get('odoo_payment_ids', []))],
            'start_date': start_date,
            'end_date': end_date,
        })
        sequence += 1

        # Total Emitidos (excluyendo ignorados)
        total_sat_emitidos = (emitidos_data['qty_sat'] - emitidos_data['qty_ignored'] + 
                              emitidos_nc['qty_sat'] - emitidos_nc['qty_ignored'] + 
                              emitidos_pago['qty_sat'] - emitidos_pago['qty_ignored'])
        total_importe_sat_emitidos = (emitidos_data['amount_sat'] - emitidos_data['amount_ignored'] + 
                                      emitidos_nc['amount_sat'] - emitidos_nc['amount_ignored'] + 
                                      emitidos_pago['amount_sat'] - emitidos_pago['amount_ignored'])
        total_odoo_emitidos = (emitidos_data['qty_odoo'] + emitidos_nc['qty_odoo'] + emitidos_pago['qty_odoo'])
        total_importe_odoo_emitidos = (emitidos_data['amount_odoo'] + emitidos_nc['amount_odoo'] + emitidos_pago['amount_odoo'])

        report_lines.append({
            'sequence': sequence,
            'section_type': 'total_emitidos',
            'concepto': 'TOTAL EMITIDOS (Sin Ignorados)',
            'document_type': '',
            'qty_sat': total_sat_emitidos,
            'amount_sat': total_importe_sat_emitidos,
            'qty_odoo': total_odoo_emitidos,
            'amount_odoo': total_importe_odoo_emitidos,
            'start_date': start_date,
            'end_date': end_date,
        })
        sequence += 1

        # Separador
        report_lines.append({
            'sequence': sequence,
            'section_type': 'separator',
            'document_type': '',
            'start_date': start_date,
            'end_date': end_date,
        })
        sequence += 1

        # =====================================================================
        # SECCIÓN: XML RECIBIDOS
        # =====================================================================
        
        # Header Recibidos
        report_lines.append({
            'sequence': sequence,
            'section_type': 'header_recibidos',
            'concepto': '═══ XML RECIBIDOS ═══',
            'document_type': '',
            'start_date': start_date,
            'end_date': end_date,
        })
        sequence += 1

        # 1. Facturas de Proveedor (Ingreso)
        recibidos_data = self._get_recibidos_data(start_date, end_date, 'I', 'in_invoice')
        report_lines.append({
            'sequence': sequence,
            'section_type': 'data_recibidos',
            'document_type': 'Facturas de Proveedor (Ingreso)',
            'qty_sat': recibidos_data['qty_sat'],
            'amount_sat': recibidos_data['amount_sat'],
            'qty_odoo': recibidos_data['qty_odoo'],
            'amount_odoo': recibidos_data['amount_odoo'],
            'qty_ignored': recibidos_data['qty_ignored'],
            'amount_ignored': recibidos_data['amount_ignored'],
            'sat_xml_ids': [(6, 0, recibidos_data.get('sat_xml_ids', []))],
            'odoo_invoice_ids': [(6, 0, recibidos_data.get('odoo_invoice_ids', []))],
            'start_date': start_date,
            'end_date': end_date,
        })
        sequence += 1

        # 2. Notas de Crédito Proveedor (Egreso)
        recibidos_nc = self._get_recibidos_data(start_date, end_date, 'E', 'in_refund')
        report_lines.append({
            'sequence': sequence,
            'section_type': 'data_recibidos',
            'document_type': 'Notas de Crédito Proveedor (Egreso)',
            'qty_sat': recibidos_nc['qty_sat'],
            'amount_sat': recibidos_nc['amount_sat'],
            'qty_odoo': recibidos_nc['qty_odoo'],
            'amount_odoo': recibidos_nc['amount_odoo'],
            'qty_ignored': recibidos_nc['qty_ignored'],
            'amount_ignored': recibidos_nc['amount_ignored'],
            'sat_xml_ids': [(6, 0, recibidos_nc.get('sat_xml_ids', []))],
            'odoo_invoice_ids': [(6, 0, recibidos_nc.get('odoo_invoice_ids', []))],
            'start_date': start_date,
            'end_date': end_date,
        })
        sequence += 1

        # 3. Complemento de Pago Recibidos
        recibidos_pago = self._get_recibidos_pago_data(start_date, end_date)
        report_lines.append({
            'sequence': sequence,
            'section_type': 'data_recibidos',
            'document_type': 'Complemento de Pago Recibidos',
            'qty_sat': recibidos_pago['qty_sat'],
            'amount_sat': recibidos_pago['amount_sat'],
            'qty_odoo': recibidos_pago['qty_odoo'],
            'amount_odoo': recibidos_pago['amount_odoo'],
            'qty_ignored': recibidos_pago['qty_ignored'],
            'amount_ignored': recibidos_pago['amount_ignored'],
            'sat_xml_ids': [(6, 0, recibidos_pago.get('sat_xml_ids', []))],
            'odoo_payment_ids': [(6, 0, recibidos_pago.get('odoo_payment_ids', []))],
            'start_date': start_date,
            'end_date': end_date,
        })
        sequence += 1

        # Total Recibidos (excluyendo ignorados)
        total_sat_recibidos = (recibidos_data['qty_sat'] - recibidos_data['qty_ignored'] + 
                               recibidos_nc['qty_sat'] - recibidos_nc['qty_ignored'] + 
                               recibidos_pago['qty_sat'] - recibidos_pago['qty_ignored'])
        total_importe_sat_recibidos = (recibidos_data['amount_sat'] - recibidos_data['amount_ignored'] + 
                                       recibidos_nc['amount_sat'] - recibidos_nc['amount_ignored'] + 
                                       recibidos_pago['amount_sat'] - recibidos_pago['amount_ignored'])
        total_odoo_recibidos = (recibidos_data['qty_odoo'] + recibidos_nc['qty_odoo'] + recibidos_pago['qty_odoo'])
        total_importe_odoo_recibidos = (recibidos_data['amount_odoo'] + recibidos_nc['amount_odoo'] + recibidos_pago['amount_odoo'])

        report_lines.append({
            'sequence': sequence,
            'section_type': 'total_recibidos',
            'concepto': 'TOTAL RECIBIDOS (Sin Ignorados)',
            'document_type': '',
            'qty_sat': total_sat_recibidos,
            'amount_sat': total_importe_sat_recibidos,
            'qty_odoo': total_odoo_recibidos,
            'amount_odoo': total_importe_odoo_recibidos,
            'start_date': start_date,
            'end_date': end_date,
        })

        # Crear registros
        self.create(report_lines)

        # Retornar acción para abrir vista list
        return {
            'type': 'ir.actions.act_window',
            'name': f'Conciliación SAT vs Odoo ({start_date.strftime("%d/%m/%Y")} - {end_date.strftime("%d/%m/%Y")})',
            'res_model': 'sat.conciliation.report',
            'view_mode': 'list,form,pivot',
            'target': 'current',
            'context': {'create': False, 'edit': False, 'delete': False},
        }

    def _get_emitidos_data(self, start_date, end_date, document_type, move_type):
        """Obtiene datos de XMLs emitidos por tipo de documento"""
        # XMLs en SAT (todos)
        sat_xmls = self.env['account.edi.downloaded.xml.sat'].search([
            ('cfdi_type', '=', 'emitidos'),
            ('document_type', '=', document_type),
            ('document_date', '>=', start_date),
            ('document_date', '<=', end_date),
        ])
        
        # XMLs Ignorados
        ignored_xmls = sat_xmls.filtered(lambda x: x.state == 'ignored')
        
        # Facturas en Odoo
        odoo_moves = self.env['account.move'].search([
            ('state', '=', 'posted'),
            ('move_type', '=', move_type),
            ('l10n_mx_edi_cfdi_sat_state', '=', 'valid'),
            ('invoice_date', '>=', start_date),
            ('invoice_date', '<=', end_date),
        ])

        return {
            'sat_xml_ids': sat_xmls.ids,
            'odoo_invoice_ids': odoo_moves.ids,
            'qty_sat': len(sat_xmls),
            'amount_sat': sum(sat_xmls.mapped('amount_total')),
            'qty_odoo': len(odoo_moves),
            'amount_odoo': abs(sum(odoo_moves.mapped('amount_total_signed'))),
            'qty_ignored': len(ignored_xmls),
            'amount_ignored': sum(ignored_xmls.mapped('amount_total')),
        }

    def _get_emitidos_pago_data(self, start_date, end_date):
        """Obtiene datos de complementos de pago emitidos"""
        # XMLs en SAT
        sat_xmls = self.env['account.edi.downloaded.xml.sat'].search([
            ('cfdi_type', '=', 'emitidos'),
            ('document_type', '=', 'P'),
            ('document_date', '>=', start_date),
            ('document_date', '<=', end_date),
        ])
        
        ignored_xmls = sat_xmls.filtered(lambda x: x.state == 'ignored')
        
        # Pagos en Odoo - Solo pagos de cliente
        odoo_payments = self.env['account.payment'].search([
            ('state', '=', 'posted'),
            ('payment_type', '=', 'inbound'),
            ('partner_type', '=', 'customer'),
            ('date', '>=', start_date),
            ('date', '<=', end_date),
        ])

        return {
            'sat_xml_ids': sat_xmls.ids,
            'odoo_payment_ids': odoo_payments.ids,
            'qty_sat': len(sat_xmls),
            'amount_sat': sum(sat_xmls.mapped('amount_total')),
            'qty_odoo': len(odoo_payments),
            'amount_odoo': abs(sum(odoo_payments.mapped('amount_company_currency_signed'))),
            'qty_ignored': len(ignored_xmls),
            'amount_ignored': sum(ignored_xmls.mapped('amount_total')),
        }

    def _get_recibidos_data(self, start_date, end_date, document_type, move_type):
        """Obtiene datos de XMLs recibidos por tipo de documento"""
        # XMLs en SAT
        sat_xmls = self.env['account.edi.downloaded.xml.sat'].search([
            ('cfdi_type', '=', 'recibidos'),
            ('document_type', '=', document_type),
            ('document_date', '>=', start_date),
            ('document_date', '<=', end_date),
        ])
        
        ignored_xmls = sat_xmls.filtered(lambda x: x.state == 'ignored')
        
        # Facturas en Odoo
        odoo_moves = self.env['account.move'].search([
            ('state', '=', 'posted'),
            ('move_type', '=', move_type),
            ('l10n_mx_edi_cfdi_sat_state', '=', 'valid'),
            ('invoice_date', '>=', start_date),
            ('invoice_date', '<=', end_date),
        ])

        return {
            'sat_xml_ids': sat_xmls.ids,
            'odoo_invoice_ids': odoo_moves.ids,
            'qty_sat': len(sat_xmls),
            'amount_sat': sum(sat_xmls.mapped('amount_total')),
            'qty_odoo': len(odoo_moves),
            'amount_odoo': abs(sum(odoo_moves.mapped('amount_total_signed'))),
            'qty_ignored': len(ignored_xmls),
            'amount_ignored': sum(ignored_xmls.mapped('amount_total')),
        }

    def _get_recibidos_pago_data(self, start_date, end_date):
        """Obtiene datos de complementos de pago recibidos"""
        # XMLs en SAT
        sat_xmls = self.env['account.edi.downloaded.xml.sat'].search([
            ('cfdi_type', '=', 'recibidos'),
            ('document_type', '=', 'P'),
            ('document_date', '>=', start_date),
            ('document_date', '<=', end_date),
        ])
        
        ignored_xmls = sat_xmls.filtered(lambda x: x.state == 'ignored')
        
        # Pagos en Odoo - Solo pagos a proveedores
        odoo_payments = self.env['account.payment'].search([
            ('state', '=', 'posted'),
            ('payment_type', '=', 'outbound'),
            ('partner_type', '=', 'supplier'),
            ('date', '>=', start_date),
            ('date', '<=', end_date),
        ])

        return {
            'sat_xml_ids': sat_xmls.ids,
            'odoo_payment_ids': odoo_payments.ids,
            'qty_sat': len(sat_xmls),
            'amount_sat': sum(sat_xmls.mapped('amount_total')),
            'qty_odoo': len(odoo_payments),
            'amount_odoo': abs(sum(odoo_payments.mapped('amount_company_currency_signed'))),
            'qty_ignored': len(ignored_xmls),
            'amount_ignored': sum(ignored_xmls.mapped('amount_total')),
        }

    
    def action_view_sat_xmls(self):
        """Abrir vista de XMLs del SAT relacionados"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'XMLs del SAT - {self.document_type or self.concepto}',
            'res_model': 'account.edi.downloaded.xml.sat',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.sat_xml_ids.ids)],
            'context': {'create': False},
        }
    
    def action_view_odoo_invoices(self):
        """Abrir vista de facturas Odoo relacionadas"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Facturas Odoo - {self.document_type or self.concepto}',
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.odoo_invoice_ids.ids)],
            'context': {'create': False},
        }
    
    def action_view_odoo_payments(self):
        """Abrir vista de pagos Odoo relacionados"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'Pagos Odoo - {self.document_type or self.concepto}',
            'res_model': 'account.payment',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.odoo_payment_ids.ids)],
            'context': {'create': False},
        }
