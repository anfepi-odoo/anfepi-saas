# -*- coding: utf-8 -*-
from odoo import api, fields, models, tools, _ # type: ignore
from odoo.exceptions import UserError # type: ignore
from lxml import etree # type: ignore
from lxml.objectify import fromstring # type: ignore
import base64
import requests # type: ignore
import hashlib
import logging
from odoo.addons.l10n_mx_edi.models.l10n_mx_edi_document import ( # type: ignore
    CFDI_CODE_TO_TAX_TYPE,
)
from io import BytesIO
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher
import qrcode
from urllib.parse import urlencode

_logger = logging.getLogger(__name__) 
from datetime import datetime, timedelta

USO_CFDI  = [
    ("G01", "Adquisición de mercancías"),
    ("G02", "Devoluciones, descuentos o bonificaciones"),
    ("G03", "Gastos en general"),
    ("I01", "Construcciones"),
    ("101", "Construcciones"),
    ("I02", "Mobiliario y equipo de oficina por inversiones"),
    ("I03", "Equipo de transporte"),
    ("I04", "Equipo de cómputo y accesorios"),    
    ("I05", "Dados, troqueles, moldes, matrices y herramental"),
    ("I06", "Comunicaciones telefónicas"),
    ("I07", "Comunicaciones satelitales"),
    ("I08", "Otra maquinaria y equipo"),
    ("D01", "Honorarios médicos, dentales y gastos hospitalarios"),
    ("D02", "Gastos médicos por incapacidad o discapacidad"),
    ("D03", "Gastos funerales"),
    ("D04", "Donativos"),
    ("D05", "Intereses reales efectivamente pagados por créditos hipotecarios (casa habitación)"),
    ("D06", "Aportaciones voluntarias al SAR"),
    ("D07", "Primas por seguros de gastos médicos"),
    ("D08", "Gastos de transportación escolar obligatoria"),
    ("D09", "Depósitos en cuentas para el ahorro, primas que tengan como base planes de pensiones"),
    ("D10", "Pagos por servicios educativos (colegiaturas)"),
    ("CP01", "Pagos"),
    ("CN01", "Nómina"),
    ("S01", "Sin Efectos Fiscales"),
]
 
PAYMENT_METHOD = [
    ("01", "Efectivo"),
    ("02", "Cheque nominativo"),
    ("03", "Transferencia electrónica de fondos"),
    ("04", "Tarjeta de crédito"),
    ("05", "Monedero electrónico"),
    ("06", "Dinero electrónico"),
    ("08", "Vales de despensa"),
    ("12", "Dación en pago"),
    ("13", "Pago por subrogación"),
    ("14", "Pago por consignación"),
    ("15", "Condonación"),
    ("17", "Compensación"),
    ("23", "Novación"),
    ("24", "Confusión"),
    ("25", "Remisión de deuda"),
    ("26", "Prescripción o caducidad"),
    ("27", "A satisfacción del acreedor"),
    ("28", "Tarjeta de débito"),
    ("29", "Tarjeta de servicios"),
    ("30", "Aplicación de anticipos"),
    ("31", "Intermediario pagos"),
    ("99", "Por definir"),
]

TAX_REGIME = [
    ("601", "General de Ley Personas Morales"),
    ("603", "Personas Morales con Fines no Lucrativos"),
    ("605", "Sueldos y Salarios e Ingresos Asimilados a Salarios"),
    ("606", "Arrendamiento"),
    ("607", "Régimen de Enajenación o Adquisición de Bienes"),
    ("609", "Consolidación"),
    ("610", "Residentes en el Extranjero sin Establecimiento Permanente en México"),
    ("611", "Ingresos por Dividendos (socios y accionistas)"),
    ("612", "Personas Físicas con Actividades Empresariales y Profesionales"),
    ("614", "Ingresos por intereses"),
    ("615", "Régimen de los ingresos por obtención de premios"),
    ("616", "Sin obligaciones fiscales"),
    ("620", "Sociedades Cooperativas de Producción que optan por diferir sus ingresos"),
    ("621", "Incorporación Fiscal"),
    ("622", "Actividades Agrícolas, Ganaderas, Silvícolas y Pesqueras"),
    ("623", "Opcional para Grupos de Sociedades"),
    ("624", "Coordinados"),
    ("625", "Régimen de las Actividades Empresariales con ingresos a través de Plataformas Tecnológicas"),
    ("626", "Régimen Simplificado de Confianza"),
    ("628", "Hidrocarburos"),
    ("629", "De los Regímenes Fiscales Preferentes y de las Empresas Multinacionales"),
    ("630", "Enajenación de acciones en bolsa de valores")
]

class DownloadedXmlSat(models.Model):
    _name = "account.edi.downloaded.xml.sat"
    _description = "Account Edi Download From SAT Web Service"
    _inherit = ['mail.thread']
    _check_company_auto = True
  
    name = fields.Char(string="UUID", required=True, index='trigram')
    active_company_id = fields.Integer(string='Empresa activa', compute='_compute_active_company_id')
    company_id = fields.Many2one('res.company', string='Empresa configurada', default=lambda self: self.env.company.id) 
    partner_id = fields.Many2one('res.partner', string="Proveedor") # Cliente/Proveedor
    invoice_id = fields.Many2one('account.move', string="Factura Relacionada") # Factura
    cfdi_type = fields.Selection([('recibidos', 'Recibidos'),('emitidos', 'Emitidos'), ], string='Tipo', required=True, default='emitidos') 
    batch_id = fields.Many2one(
        comodel_name='account.edi.api.download',
        string='Batch',
        required=True,
        readonly=True,
        index=True,
        ondelete="cascade",
        check_company=True,
    )
    attachment_id = fields.Many2one('ir.attachment', string='XML Attachment')
    document_date =  fields.Date(string="Fecha de Documento")
    serie = fields.Char(string="Serie Factura")
    folio = fields.Char(string="Folio Factura")
    divisa = fields.Char(string="Divisa en Factura")
    currency_id = fields.Many2one('res.currency', string='Moneda', compute='_compute_currency_id', store=True, default=lambda self: self.env.company.currency_id)
    state = fields.Selection(
        selection=[
            ('not_imported', 'No Importado'),
            ('draft', 'Borrador'),
            ('posted', 'Publicado'),
            ('cancel', 'Cancelado'),
            ('ignored', 'Ignorado'),
            ('error_relating', 'Error Relacionando'),
        ],
        string='Status',
        default='draft',
    )
    sat_state = fields.Selection([
        ('Vigente', 'Vigente'),
        ('Cancelado','Cancelado'),
        ('No Encontrado', 'No encontrado'),
        ('Sin Definir', 'Sin Definir')
    ], string="Estatus SAT", default='Sin Definir')
    payment_method = fields.Selection([('PPD','PPD'),('PUE','PUE')], string='Metodo de Pago')
    sub_total = fields.Float(string="Sub Total", required=True)
    amount_total = fields.Float(string="Total", required=True)
    document_type = fields.Selection([
        ('I', 'Ingreso'),
        ('E', 'Egreso'),
        ('T', 'Traslado'),
        ('N', 'Nomina'),
        ('P', 'Pago'),
    ], string='Tipo de Documento')
    cfdi_usage = fields.Selection(USO_CFDI, string="Uso CFDI")
    imported = fields.Boolean(string="Importado", default=False)
    discount = fields.Float(string="Descuento")
    
    downloaded_product_id = fields.One2many(
        'account.edi.downloaded.xml.sat.products',
        'downloaded_invoice_id',
        string='Downloaded product ID',)  
    payment_method_sat = fields.Selection(PAYMENT_METHOD, string="Forma de Pago")
    total_impuestos = fields.Float(string='Total Impuestos')
    total_retenciones = fields.Float(string='Total Retenciones')
    tax_regime = fields.Selection(TAX_REGIME, string="Regimen Fiscal")

    total_impuestos = fields.Float(string='Total Impuestos')
    total_retenciones = fields.Float(string='Total Retenciones')
    
    # ============================================================================
    # CAMPOS PARA SELLOS DIGITALES Y CERTIFICADOS
    # ============================================================================
    sello_cfdi = fields.Text(string="Sello Digital CFDI", readonly=True, copy=False)
    sello_sat = fields.Text(string="Sello Digital SAT", readonly=True, copy=False)
    cadena_original = fields.Text(string="Cadena Original", readonly=True, copy=False)
    certificate_number = fields.Char(string="No. Certificado Emisor", readonly=True, copy=False)
    certificate_sat_number = fields.Char(string="No. Certificado SAT", readonly=True, copy=False)
    qr_code_image = fields.Text(string="QR Code Image", compute="_compute_qr_code_image", readonly=True, store=True)
    
    @api.depends('name', 'rfc_emisor', 'rfc_receptor', 'amount_total', 'sello_cfdi')
    def _compute_qr_code_image(self):
        """Genera el QR code como imagen base64 con la URL completa del SAT."""
        for record in self:
            if not record.name:
                record.qr_code_image = False
                continue
                
            try:
                # Construir URL del SAT con todos los parámetros
                params = {
                    'id': record.name,
                    're': record.rfc_emisor or '',
                    'rr': record.rfc_receptor or '',
                    'tt': f"{record.amount_total:.6f}",
                }
                
                # Agregar últimos 8 caracteres del sello si existe
                if record.sello_cfdi and len(record.sello_cfdi) >= 8:
                    params['fe'] = record.sello_cfdi[-8:]
                
                # URL completa
                url = f"https://verificacfdi.facturaelectronica.sat.gob.mx/default.aspx?{urlencode(params)}"
                
                # Generar QR code
                qr = qrcode.QRCode(
                    version=1,
                    error_correction=qrcode.constants.ERROR_CORRECT_L,
                    box_size=10,
                    border=4,
                )
                qr.add_data(url)
                qr.make(fit=True)
                
                # Crear imagen
                img = qr.make_image(fill_color="black", back_color="white")
                
                # Convertir a base64
                buffer = BytesIO()
                img.save(buffer, format='PNG')
                img_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
                
                record.qr_code_image = img_base64
                
            except Exception as e:
                _logger.error(f"Error generando QR code para {record.name}: {e}")
                record.qr_code_image = False
    
    # ============================================================================
    # CAMPOS RFC Y EMPRESA (MIGRADOS DE V17)
    # ============================================================================
    rfc_emisor = fields.Char(
        string='RFC Emisor',
        compute='_compute_rfc_fields',
        store=True,
        index=True
    )
    rfc_receptor = fields.Char(
        string='RFC Receptor',
        compute='_compute_rfc_fields',
        store=True,
        index=True
    )
    rfc_empresa = fields.Char(
        string='RFC Empresa',
        compute='_compute_rfc_empresa',
        store=True,
        help='RFC de la empresa: Emisor en Emitidos, Receptor en Recibidos'
    )
    rfc_partner = fields.Char(
        string='RFC Contacto',
        compute='_compute_rfc_partner',
        store=True,
        help='RFC del proveedor/cliente: Receptor en Emitidos, Emisor en Recibidos'
    )
    company_mismatch = fields.Boolean(
        string='Empresa Incorrecta',
        compute='_compute_company_mismatch',
        store=True,
        help='Indica si el XML está asignado a una empresa incorrecta según el RFC'
    )
    
    # ============================================================================
    # ART 69-B ALERTA FISCAL (MIGRADO DE V17)
    # ============================================================================
    estatus_69b = fields.Char(
        string='⚠️ Estatus Artículo 69-B',
        index=True,
        help='Estatus del RFC ante el SAT según Artículo 69-B (Presunto, Definitivo, No listado, etc.)'
    )

    # ============================================================================
    # NUEVOS CAMPOS: Documento Origen (NO AFECTA FUNCIONALIDAD EXISTENTE)
    # ============================================================================
    origin_document_id = fields.Many2one(
        'account.move',
        string='Documento Origen',
        help='Documento origen relacionado (SO/PO/Factura)',
        index=True,
        copy=False,
        readonly=True,
    )
    
    origin_document_name = fields.Char(
        string='Referencia Origen',
        compute='_compute_origin_document_name',
        search='_search_origin_document_name',
        help='Nombre del documento origen (SO001, PO042, etc.)'
    )
    
    origin_document_type = fields.Selection([
        ('sale_order', 'Pedido de Venta'),
        ('purchase_order', 'Orden de Compra'),
        ('invoice', 'Factura'),
        ('other', 'Otro')
    ], string='Tipo Documento', compute='_compute_origin_document_name')

    def _compute_active_company_id(self):
        self.active_company_id = self.env.company.id
    
    @api.depends('attachment_id', 'attachment_id.datas')
    def _compute_rfc_fields(self):
        """Extraer RFC emisor y receptor del XML - MIGRADO DE V17"""
        for record in self:
            record.rfc_emisor = False
            record.rfc_receptor = False
            
            if not record.attachment_id or not record.attachment_id.datas:
                continue
            
            try:
                xml_content = base64.b64decode(record.attachment_id.datas)
                root = ET.fromstring(xml_content)
                ns = {'cfdi': 'http://www.sat.gob.mx/cfd/4'}
                
                emisor = root.find('.//cfdi:Emisor', namespaces=ns)
                if emisor is not None:
                    record.rfc_emisor = emisor.get('Rfc')
                
                receptor = root.find('.//cfdi:Receptor', namespaces=ns)
                if receptor is not None:
                    record.rfc_receptor = receptor.get('Rfc')
            except (ET.ParseError, ValueError, AttributeError):
                record.rfc_emisor = False
                record.rfc_receptor = False
    
    @api.depends('rfc_emisor', 'rfc_receptor', 'cfdi_type')
    def _compute_rfc_empresa(self):
        """Determinar el RFC de la empresa según el tipo de CFDI - MIGRADO DE V17"""
        for record in self:
            if record.cfdi_type == 'emitidos':
                record.rfc_empresa = record.rfc_emisor
            else:
                record.rfc_empresa = record.rfc_receptor
    
    @api.depends('divisa')
    def _compute_currency_id(self):
        """Calcular el currency_id basado en el campo divisa"""
        for record in self:
            if record.divisa:
                currency = self.env['res.currency'].search([('name', '=', record.divisa)], limit=1)
                record.currency_id = currency.id if currency else self.env.company.currency_id.id
            else:
                record.currency_id = self.env.company.currency_id.id
    
    @api.depends('rfc_emisor', 'rfc_receptor', 'cfdi_type')
    def _compute_rfc_partner(self):
        """Determinar el RFC del contacto según el tipo de CFDI - MIGRADO DE V17"""
        for record in self:
            if record.cfdi_type == 'emitidos':
                record.rfc_partner = record.rfc_receptor
            else:
                record.rfc_partner = record.rfc_emisor
    
    @api.depends('company_id', 'company_id.vat', 'rfc_emisor', 'rfc_receptor', 'cfdi_type')
    def _compute_company_mismatch(self):
        """Detectar si el XML está asignado a la empresa incorrecta - MIGRADO DE V17"""
        for record in self:
            record.company_mismatch = False
            
            if not record.company_id or not record.company_id.vat:
                continue
            
            company_vat = record.company_id.vat
            
            if record.cfdi_type == 'emitidos':
                if record.rfc_emisor and record.rfc_emisor != company_vat:
                    record.company_mismatch = True
            else:
                if record.rfc_receptor and record.rfc_receptor != company_vat:
                    record.company_mismatch = True

    def view_invoice(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Invoice',
            'view_mode': 'form',
            'res_model': 'account.move',
            'res_id': self.invoice_id.id,
            'target': 'current',
        }

    def relate_download(self): 
        for item in self:
            move = self.env['account.move'].search([('stored_sat_uuid', '=', item.name)], limit=1)
            if move:
                item.write({'invoice_id': move.id, 'state': move.state})

    def action_wizard_relate(self):
        action = self.env.ref('l10n_mx_xml_masive_download.action_open_invoice_wizard').read()[0]
        return action
    
    def generate_pdf_attatchment(self, account_id):

        datas = {
            'partner_id':self.partner_id,
            'cfdi_type':self.cfdi_type,
            'company_id':self.company_id,
            'payment_method':self.payment_method,
            'serie':self.serie,
            'folio':self.folio, 
            'divisa':self.divisa,
            'name':self.name,
            'document_date':self.document_date,
            'document_type':self.document_type,
            'downloaded_product_id':self.downloaded_product_id,
            'total_impuestos':self.total_impuestos,
            'total_retenciones':self.total_retenciones,
            'downloaded_product_id':self.downloaded_product_id,
            'total_impuestos':self.total_impuestos,
            'total_retenciones':self.total_retenciones,

        }
        result, format = self.env["ir.actions.report"]._render_qweb_pdf('l10n_mx_xml_masive_download.report_product', [self.id], datas)

        result = base64.b64encode(result)

        ir_values = {
            'name': 'Invoice ' + self.name,
            'type': 'binary',
            'datas': result,
            'store_fname': 'Factura ' + self.name + '.pdf',
            'mimetype': 'application/pdf',
            'res_model': 'account.move',
            'res_id': account_id,
        }
       
        self.env['ir.attachment'].create(ir_values)

    def action_import_invoice(self):
        for item in self:
            # Asegurar que currency_id esté calculado antes de generar PDF
            if not item.currency_id:
                item._compute_currency_id()
            
            ref = (self.serie + '/' if self.serie else '') + (self.folio if self.folio else '')
            
            # Buscar moneda, si no se encuentra usar MXN por defecto
            currency = self.env['res.currency'].search([('name', '=', self.divisa or 'MXN')], limit=1)
            if not currency:
                currency = self.env['res.currency'].search([('name', '=', 'MXN')], limit=1)
            if not currency:
                raise UserError("No se pudo encontrar una moneda válida. Asegúrese de tener MXN configurada.")
            
            currency_id = currency.id
            
            account_move_dict = {
                'ref': ref,
                'ref': ref,
                'invoice_date': item.document_date,
                'date': item.document_date,
                'move_type':'out_invoice' if self.cfdi_type == 'recividos' else 'in_invoice',
                'partner_id': item.partner_id.id,
                'company_id': item.company_id.id,
                'invoice_line_ids': [],
                'currency_id': currency_id,
                'l10n_edi_imported_from_sat': True,
                'payment_method':self.payment_method,
                'uso_sat':self.cfdi_usage,
                'xml_imported_id': item.id
            }

            discount = 0
            for concepto in item.downloaded_product_id:
                    if concepto.discount:
                        discount = abs(concepto.discount / concepto.quantity / concepto.unit_value)* 100
                    exchange_rate = 1
                    amount_base_currency = concepto.total_amount / exchange_rate

                    account_move_dict['invoice_line_ids'].append((0, 0, {
                        'product_id': concepto.product_rel.id,
                        'name': concepto.description,
                        'quantity': concepto.quantity,
                        'price_unit': concepto.unit_value,
                        'amount_currency': concepto.total_amount,
                        'tax_ids': concepto.tax_id,
                        'downloaded_product_rel': concepto.id,
                        'discount': discount if discount else None,
                    }))
            account_move = self.env['account.move'].create(account_move_dict)
            item.write({'invoice_id': account_move.id, 'state': 'draft'})


            
            self.generate_pdf_attatchment(account_move.id)
            xml_file = self.attachment_id.filtered(lambda x: x.mimetype == 'application/xml')
            attachment_values = {
                'name': self.name,  # Name of the XML file
                'datas': xml_file.datas,  # Read XML file content
                'res_model': 'account.move',
                'res_id': account_move.id,
                'mimetype': 'application/xml',
            }
            self.env['ir.attachment'].create(attachment_values)
            account_move.create_edi_document_from_attatchment(self.name)
            item.write({'imported': True})

    def action_add_payment(self):
        # Buscar factura
        xml_attachment = self.attachment_id.filtered(lambda x: x.mimetype == 'application/xml')
        if not xml_attachment:
            raise UserError('No se encontró el archivo XML adjunto.')
        root = ET.fromstring(base64.b64decode(xml_attachment[0].datas))
        namespace = {'cfdi': 'http://www.sat.gob.mx/cfd/4', 'pago20': 'http://www.sat.gob.mx/Pagos20'}
        id_documentos = []

        for docto_relacionado in root.findall('.//pago20:DoctoRelacionado', namespace):
            id_documento = docto_relacionado.get('IdDocumento')
            id_documentos.append(id_documento)

        moves = self.env['account.move'].search([('l10n_mx_edi_cfdi_uuid','in', id_documentos)])

        # Si hay factura, verificar si el estatus es in_payment 

        if moves:
            for move in moves:
                if move.payment_state == 'in_payment' or move.payment_state == 'paid':
                    # Buscar el Id del pago
                    
                    payments = self.env['account.payment'].search([('reconciled_invoice_ids','=',move.id)])
                    xml_file = self.attachment_id.filtered(lambda x: x.mimetype == 'application/xml')
                    for payment in payments:
                        attachment_values = {
                                'name': xml_file.name,  # Name of the XML file
                                'datas': xml_file.datas,  # Read XML file content
                                'res_model': 'account.payment',
                                'res_id': payment.id,
                                'mimetype': 'application/xml',
                            }
                        
                        self.write({'invoice_id':move.id, 'imported':True})
                        res = self.env['ir.attachment'].create(attachment_values)

                        edi = self.env['l10n_mx_edi.document']
    
                        edi_data = {
                                    # 'name' : uuid_name+'.xml',
                                    'state' : 'payment_sent',
                                    'sat_state' : 'not_defined',
                                    'message': '',
                                    'datetime': fields.Datetime.now(),
                                    'attachment_uuid': self.name,
                                    'attachment_id' : res.id,
                                    'move_id'    : payment.move_id.id,
                                    }
                        new_edi_doc = edi.create(edi_data)

                        #### Asociando las Facturas ####
                        invoice_rel_ids = []
                        #### Facturas de Cliente ####
                        if payment.reconciled_invoice_ids:
                            invoice_rel_ids = payment.reconciled_invoice_ids.ids
                        #### Facturas de Proveedor ####
                        if payment.reconciled_bill_ids:
                            invoice_rel_ids = payment.reconciled_bill_ids.ids

                        new_edi_doc.invoice_ids = [(6,0, invoice_rel_ids)]
        else: 
            raise UserError("Error adjuntando pago, verifique que la factura exista y tenga un pago creado")

    def action_ignor(self):
        self.state = 'ignored'

    def _fetch_sat_status(self, supplier_rfc, customer_rfc, total, uuid):
        url = 'https://consultaqr.facturaelectronica.sat.gob.mx/ConsultaCFDIService.svc?wsdl'
        headers = {
            'SOAPAction': 'http://tempuri.org/IConsultaCFDIService/Consulta',
            'Content-Type': 'text/xml; charset=utf-8',
        }
        params = f'<![CDATA[?id={uuid or ""}' \
                 f'&re={tools.html_escape(supplier_rfc or "")}' \
                 f'&rr={tools.html_escape(customer_rfc or "")}' \
                 f'&tt={total or 0.0}]]>'
        envelope = f"""<?xml version="1.0" encoding="UTF-8"?>
            <SOAP-ENV:Envelope
                xmlns:ns0="http://tempuri.org/"
                xmlns:ns1="http://schemas.xmlsoap.org/soap/envelope/"
                xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
                xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/">
                <SOAP-ENV:Header/>
                <ns1:Body>
                    <ns0:Consulta>
                        <ns0:expresionImpresa>{params}</ns0:expresionImpresa>
                    </ns0:Consulta>
                </ns1:Body>
            </SOAP-ENV:Envelope>
        """
        namespace = {'a': 'http://schemas.datacontract.org/2004/07/Sat.Cfdi.Negocio.ConsultaCfdi.Servicio'}

        try:
            soap_xml = requests.post(url, data=envelope, headers=headers, timeout=35)
            response = etree.fromstring(soap_xml.text)
            fetched_status = response.xpath('//a:Estado', namespaces=namespace)
            fetched_state = fetched_status[0].text if fetched_status else None
        except Exception as e:
            return {
                'error': _("Failure during update of the SAT status: %s", str(e)),
                'value': 'error',
            }
        if fetched_state == 'Vigente':
            self.sat_state = 'Vigente'
        elif fetched_state == 'Cancelado':
            self.sat_state = 'Cancelado'
        elif fetched_state == 'No Encontrado':
            self.sat_state = 'No Encontrado'
        else:
            self.sat_state = 'Sin Definir'

    def action_fetch_sat_status(self):
        if self.cfdi_type == 'emitidos':
            self._fetch_sat_status(self.company_id.vat, self.partner_id.vat, self.amount_total, self.name)
        else: 
            self._fetch_sat_status(self.partner_id.vat, self.company_id.vat, self.amount_total, self.name)

    def cron_fetch_sat_status(self):
        # Calculate the date range for the last 31 days
        today = datetime.now()
        last_31_days = today - timedelta(days=31)
        
        # Modify the search domain to dynamically filter records from the last 31 days
        records = self.env['account.edi.downloaded.xml.sat'].search([
            ('sat_state', '!=', 'Cancelado'),
            ('document_date', '>=', last_31_days.strftime('%Y-%m-%d')),
            ('document_date', '<=', today.strftime('%Y-%m-%d'))
        ])
        for record in records:
            if self.cfdi_type == 'emitidos':
                record._fetch_sat_status(record.company_id.vat, record.partner_id.vat, record.amount_total, record.name)
            else: 
                record._fetch_sat_status(record.partner_id.vat, record.company_id.vat, record.amount_total, record.name)
    
    # ============================================================================
    # MÉTODOS PARA DOCUMENTO ORIGEN (NUEVOS - NO MODIFICAN FUNCIONALIDAD ACTUAL)
    # ============================================================================
    
    @api.depends('origin_document_id', 'invoice_id')
    def _compute_origin_document_name(self):
        """Calcula el nombre y tipo del documento origen - OPTIMIZADO."""
        for record in self:
            origin = record.origin_document_id or record.invoice_id
            
            if not origin:
                record.origin_document_name = False
                record.origin_document_type = False
                continue
            
            # Obtener invoice_origin en una sola lectura
            origin_ref = origin.invoice_origin
            if origin_ref:
                if 'SO' in origin_ref or 'S0' in origin_ref:
                    record.origin_document_type = 'sale_order'
                    record.origin_document_name = origin_ref
                elif 'PO' in origin_ref or 'P0' in origin_ref:
                    record.origin_document_type = 'purchase_order'
                    record.origin_document_name = origin_ref
                else:
                    record.origin_document_type = 'invoice'
                    record.origin_document_name = origin.name
            else:
                record.origin_document_type = 'invoice'
                record.origin_document_name = origin.name
    
    def _search_origin_document_name(self, operator, value):
        """Búsqueda customizada para origin_document_name sin store=True."""
        if operator == '!=' and not value:
            # Buscar registros CON documento origen
            return ['|', ('origin_document_id', '!=', False), ('invoice_id', '!=', False)]
        elif operator == '=' and not value:
            # Buscar registros SIN documento origen
            return [('origin_document_id', '=', False), ('invoice_id', '=', False)]
        else:
            # Búsqueda en invoice_origin de ambos campos
            return ['|', 
                    ('origin_document_id.invoice_origin', operator, value),
                    ('invoice_id.invoice_origin', operator, value)]
    
    def _search_origin_document_emitidos(self):
        """Buscar documento origen para XMLs Emitidos (Facturas Cliente)."""
        self.ensure_one()
        
        if self.cfdi_type != 'emitidos':
            return False
        
        # Si ya tiene invoice_id con origen, usarlo
        if self.invoice_id and self.invoice_id.invoice_origin:
            return self.invoice_id
        
        # Buscar SO por criterios de similitud
        if not self.partner_id or not self.amount_total:
            return False
            
        from datetime import timedelta
        
        domain = [
            ('partner_id', '=', self.partner_id.id),
            ('state', 'in', ['sale', 'done']),
            ('amount_total', '>=', self.amount_total * 0.95),
            ('amount_total', '<=', self.amount_total * 1.05),
        ]
        
        if self.document_date:
            date_from = self.document_date - timedelta(days=30)
            date_to = self.document_date + timedelta(days=30)
            domain.extend([
                ('date_order', '>=', date_from),
                ('date_order', '<=', date_to)
            ])
        
        sale_order = self.env['sale.order'].search(domain, limit=1, order='date_order desc')
        
        if sale_order:
            # Buscar factura de esa SO
            invoice = self.env['account.move'].search([
                ('invoice_origin', '=', sale_order.name),
                ('partner_id', '=', self.partner_id.id),
                ('move_type', '=', 'out_invoice'),
                ('state', '!=', 'cancel')
            ], limit=1)
            return invoice
        
        return False
    
    def _search_origin_document_recibidos(self):
        """Buscar documento origen para XMLs Recibidos (Facturas Proveedor)."""
        self.ensure_one()
        
        if self.cfdi_type != 'recibidos':
            return False
        
        # Si ya tiene invoice_id con origen, usarlo
        if self.invoice_id and self.invoice_id.invoice_origin:
            return self.invoice_id
        
        # Buscar PO por criterios de similitud
        if not self.partner_id or not self.amount_total:
            return False
            
        from datetime import timedelta
        
        domain = [
            ('partner_id', '=', self.partner_id.id),
            ('state', 'in', ['purchase', 'done']),
            ('amount_total', '>=', self.amount_total * 0.95),
            ('amount_total', '<=', self.amount_total * 1.05),
        ]
        
        if self.document_date:
            date_from = self.document_date - timedelta(days=45)
            date_to = self.document_date + timedelta(days=15)
            domain.extend([
                ('date_order', '>=', date_from),
                ('date_order', '<=', date_to)
            ])
        
        purchase_order = self.env['purchase.order'].search(domain, limit=1, order='date_order desc')
        
        if purchase_order:
            # Buscar factura de esa PO
            invoice = self.env['account.move'].search([
                ('invoice_origin', '=', purchase_order.name),
                ('partner_id', '=', self.partner_id.id),
                ('move_type', 'in', ['in_invoice', 'in_refund']),
                ('state', '!=', 'cancel')
            ], limit=1)
            return invoice
        
        return False
    
    def action_search_origin_document(self):
        """
        Acción MANUAL para buscar documento origen.
        100% SEGURA - Solo se ejecuta cuando el usuario lo solicita.
        """
        found_count = 0
        not_found_count = 0
        
        for record in self:
            # Saltar si ya tiene origen
            if record.origin_document_id:
                continue
            
            origin = False
            
            # Determinar tipo y buscar
            if record.cfdi_type == 'emitidos':
                origin = record._search_origin_document_emitidos()
            elif record.cfdi_type == 'recibidos':
                origin = record._search_origin_document_recibidos()
            
            if origin:
                record.origin_document_id = origin.id
                found_count += 1
            else:
                not_found_count += 1
        
        # Mensaje de resultados
        message = f'✓ {found_count} documentos encontrados'
        if not_found_count > 0:
            message += f'\n⊘ {not_found_count} sin coincidencias'
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Búsqueda de Documentos Origen',
                'message': message,
                'type': 'success' if found_count > 0 else 'warning',
                'sticky': False,
            }
        }
    
    def _update_69b_statuses(self):
        """
        Método interno para actualizar el estatus 69-B de los registros.
        Retorna tupla (actualizados, no encontrados)
        """
        updated = 0
        not_found = 0
        for record in self:
            rfc = record.rfc_partner
            if not rfc:
                not_found += 1
                continue
            blacklist = self.env['l10n_mx.art69b.blacklist'].search([
                ('rfc', '=', rfc),
                ('activo', '=', True)
            ], limit=1)
            if blacklist:
                if blacklist.situacion == 'presuncion':
                    record.estatus_69b = 'Presunto'
                elif blacklist.situacion == 'definitivo':
                    record.estatus_69b = 'Definitivo'
                elif blacklist.situacion == 'desvirtuado':
                    record.estatus_69b = 'Desvirtuado'
                else:
                    record.estatus_69b = 'Listado'
                updated += 1
            else:
                record.estatus_69b = 'No listado'
                not_found += 1
        return updated, not_found
    
    def action_review_69b(self):
        """
        Acción para revisar Art 69-B en XMLs seleccionados - MIGRADO DE V17
        """
        updated, not_found = self._update_69b_statuses()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Revisión Art 69-B',
                'message': f'Actualizados: {updated}, No listados: {not_found}',
                'type': 'success',
                'sticky': False,
            }
        }
    
    def _compute_fiscal_alert(self):
        """Permite recalcular el estatus 69-B sin generar notificaciones"""
        self._update_69b_statuses()
    
    def action_search_related_invoice(self):
        """
        Acción para buscar y relacionar facturas para XMLs seleccionados - MIGRADO DE V17
        """
        related = 0
        not_found = 0
        
        for record in self:
            if not record.invoice_id:
                move = self.env['account.move'].search([
                    ('stored_sat_uuid', '=', record.name),
                    ('company_id', '=', record.company_id.id)
                ], limit=1)
                
                if move:
                    record.write({'invoice_id': move.id, 'state': move.state})
                    related += 1
                else:
                    not_found += 1
        
        message = f'Relacionadas: {related}, No encontradas: {not_found}'
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Búsqueda de Facturas',
                'message': message,
                'type': 'success' if related > 0 else 'warning',
                'sticky': False,
            }
        }
    
class AccountEdiApiDownload(models.Model):
    _name = 'account.edi.api.download'
    _description = "Account Edi Download From SAT Web Service"

    @api.model
    def _get_default_vat(self):
        return self.env.company.vat
    
    # Fields
    name = fields.Char(string='Nombre',  index=True) 
    vat = fields.Char(string='RFC',  default=_get_default_vat)
    company_id = fields.Many2one('res.company', string='Empresa', default=lambda self: self.env.company.id, readonly = True)
    date_start = fields.Date(string='Fecha de Comienzo', required=True, default=fields.Date.today())
    date_end = fields.Date(string='Fecha de Finalizacion', required=True, default=fields.Date.today())
    last_update_date = fields.Date(string='Última actualización',  default=fields.Date.today())
    cfdi_type = fields.Selection([('emitidos', 'Emitidos'), ('recibidos', 'Recibidos')], string='Tipo', required=True, default='recibidos')
    state = fields.Selection(
    selection=[
        ('not_imported', 'No importado'),
        ('imported', 'Importado'),
        ('updated', 'Actualizado'),
        ('error', 'Error'),
    ],
    string='Status', default='not_imported', readonly=True, 
    )
    xml_sat_ids = fields.One2many(
        'account.edi.downloaded.xml.sat',
        'batch_id',
        string='Downloaded XML SAT',
        copy=True,
        readonly=True,
    )
    xml_count = fields.Integer(string='Delivery Orders', compute='_compute_xml_ids')

    # Campos para filtrat por tipo de documento
    ingreso = fields.Boolean(string="Ingreso", default=True)
    egreso = fields.Boolean(string="Egreso", default=True)
    pago = fields.Boolean(string="Pago", default=True)
    nomina = fields.Boolean(string="Nomina", default=True)
    traslado = fields.Boolean(string="Traslado", default=True)
    # Estos estan mas dificiles (pendiente)
    cancelado = fields.Boolean(string="Cancelados", default=True)
    valido = fields.Boolean(string="Vigentes", default=True)
    no_encontrado = fields.Boolean(string="No encontrado", default=True)

        
    @api.depends('xml_sat_ids')
    def _compute_xml_ids(self):
        for xml in self:
            xml.xml_count = len(xml.xml_sat_ids)
        
    def view_xml_sat(self):
         xml_sat_ids = self.xml_sat_ids.ids

         return {
            'type': 'ir.actions.act_window',
            'name': 'XML SAT',
            'res_model': 'account.edi.downloaded.xml.sat',
            'view_mode': 'list,form',
            'views': [(False, 'list'), (False, 'form')],
            'target': 'current',
            'domain': [('id', 'in', xml_sat_ids)]
        }
    
    def action_manual_upload(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Upload XML',
            'res_model': 'manual.upload.wizard',
            'view_mode': 'form',
            'view_id': self.env.ref('l10n_mx_xml_masive_download.view_manual_upload_wizard_form').id,
            'target': 'new',
            'context': {
                'default_download_batch_id': self.id,
                'active_id': self.id,
            },
        }

    def action_download(self):
        # Cache para impuestos, productos y empresas para optimizar búsquedas repetidas
        tax_cache = {}
        product_cache = {}
        company_cache = {}
        
        _logger.info(f"Iniciando procesamiento del lote {self.name}")
        
        """
        Function that recives two strings and returns a number 
        from 0 to 1 depending on how similar they are. 
        Used to compare descriptions that have dates or numbers
        """
        def similar(a, b):
            return SequenceMatcher(None, a, b).ratio()
        
        def _l10n_mx_edi_import_cfdi_get_tax_from_node(self, tax_node, is_withholding=False):
            try: 
                amount = float(tax_node.attrib.get('TasaOCuota')) * (-100 if is_withholding else 100)
                tax_type = CFDI_CODE_TO_TAX_TYPE.get(tax_node.attrib.get('Impuesto'))
                type_use = 'sale' if self.cfdi_type == 'emitidos' else 'purchase'
                
                # Cache key
                cache_key = (amount, type_use, tax_type)
                if cache_key in tax_cache:
                    return tax_cache[cache_key]
                
                domain = [
                    #*self.env['account.journal']._check_company_domain(company_id),
                    ('amount', '=', amount),
                    ('type_tax_use', '=', type_use),
                    ('amount_type', '=', 'percent'),
                ]
                if tax_type:
                    domain.append(('l10n_mx_tax_type', '=', tax_type))
                taxes = self.env['account.tax'].search(domain, limit=1)
                if not taxes:
                    _logger.warning(f"No se encontró impuesto: {tax_type} {amount}")
                    return False
                
                tax_cache[cache_key] = taxes[:1]
                return taxes[:1]
            except Exception as e:
                _logger.error(f"Error buscando impuesto: {str(e)}")
                return False  

        """  
        Function that extracts the products from the XML
        return: list of dictionaries with the products
        """
        def get_products(xml_file):
            root = ET.fromstring(xml_file)
            # Define the namespace used in the XML
            ns = {'cfdi': 'http://www.sat.gob.mx/cfd/4'}
            # Find the cfdi:Conceptos element
            conceptos_element = root.find('.//cfdi:Conceptos', namespaces=ns)
            # Initialize an empty list to store dictionaries
            conceptos_list = []
            if conceptos_element is not None:

                # Iterate over cfdi:Concepto elements and extract information
                for concepto_element in conceptos_element.findall('.//cfdi:Concepto', namespaces=ns):
                    clave_prod_serv = concepto_element.get('ClaveProdServ')
                    cantidad = concepto_element.get('Cantidad')
                    clave_unidad = concepto_element.get('ClaveUnidad')
                    descripcion = concepto_element.get('Descripcion')
                    valor_unitario = concepto_element.get('ValorUnitario')
                    importe = concepto_element.get('Importe')
                    descuento = concepto_element.get('Descuento')

                    taxes = []
                    taxes_ids = []
                    total_impuestos = 0
                    total_retenciones = 0
                    # Buscamos los impuestos
                    impuestos = concepto_element.find('.//cfdi:Impuestos', namespaces=ns)
                    if impuestos is not None:
                    
                        traslados = impuestos.find('.//cfdi:Traslados', namespaces=ns)
                        if traslados is not None:
                            for traslado in traslados.findall('.//cfdi:Traslado', namespaces=ns):
                                total_impuestos += float(traslado.get('Importe')) if traslado.get('Importe') else 0
                                taxes.append(_l10n_mx_edi_import_cfdi_get_tax_from_node(self, tax_node=traslado, is_withholding=False))
                        retenciones = impuestos.find('.//cfdi:Retenciones', namespaces=ns)
                        if retenciones is not None:
                            for retencion in retenciones.findall('.//cfdi:Retencion', namespaces=ns):
                                total_retenciones += float(retencion.get('Importe')) if retencion.get('Importe') else 0
                                taxes.append(_l10n_mx_edi_import_cfdi_get_tax_from_node(self, tax_node=retencion, is_withholding=True))
                    
                    for tax in taxes: 
                        try:
                            if tax.id:
                                taxes_ids.append(tax.id)
                        except AttributeError as e:
                            pass
                    
                    # Búsqueda de producto con cache
                    product_cache_key = (clave_prod_serv, descripcion)
                    final_product = False
                    
                    if product_cache_key in product_cache:
                        final_product = product_cache[product_cache_key]
                    else:
                        # Buscamos a ver si ya se relaciono el producto
                        domain = [
                            ('sat_id.code', '=', clave_prod_serv),
                            ('downloaded_invoice_id.partner_id', '!=', False)
                        ]
                        
                        products = self.env['account.edi.downloaded.xml.sat.products'].search(domain, limit=5)
                        if products:
                            for product in products:
                                if similar(descripcion, product.description) > 0.8:
                                    final_product = product.product_rel
                                    product_cache[product_cache_key] = final_product
                                    break
                        
                        if not final_product:
                            product_cache[product_cache_key] = False

                    # Búsqueda de código SAT con cache - cada producto tiene su propio código SAT
                    sat_code = self.env['product.unspsc.code'].search([('code','=',clave_prod_serv)], limit=1)
                    
                    # Create a dictionary for each concepto and append it to the list
                    concepto_info = {
                        'sat_id': sat_code.id if sat_code else False,
                        'quantity': cantidad,
                        'product_metrics': clave_unidad,
                        'description': descripcion,
                        'unit_value': valor_unitario,
                        'total_amount': importe,
                        'downloaded_invoice_id': False,
                        'product_rel': final_product.id if final_product else False,
                        'tax_id': taxes_ids if taxes_ids else False,
                        'discount': -float(descuento) if descuento else 0.0,
                    }
                    conceptos_list.append(concepto_info)
                return (conceptos_list, total_impuestos, total_retenciones)

        def fetch_cfdi_data(RFC, startDate, endDate, xml_type, ingreso, egreso, pago, nomina, valido, cancelado, no_encontrado, traslado):
            #base_url ='http://127.0.0.1:5000/get-cfdis'
            base_url = 'https://xmlsat.anfepi.com/get-cfdis'
            company = self.env['res.company'].search([('id', '=', self.env.company.id)], limit=1)
            api_key = company.l10n_mx_xml_download_api_key
            # El API key YA viene hasheado desde la base de datos, NO hashear nuevamente
            # La base de datos xml_api_downloader almacena el hash SHA-512 directamente

            url = (
                f"{base_url}?RFC={RFC}&startDate={startDate}&endDate={endDate}&xml_type={xml_type}&api_key={api_key}"
                f"&ingreso={'true' if ingreso else 'false'}"
                f"&egreso={'true' if egreso else 'false'}"
                f"&pago={'true' if pago else 'false'}"
                f"&nomina={'true' if nomina else 'false'}"
                f"&traslado={'true' if traslado else 'false'}"
                f"&valido={'true' if valido else 'false'}"
                f"&cancelado={'true' if cancelado else 'false'}"
                f"&no_encontrado={'true' if no_encontrado else 'false'}"
                f"&no_encontrado={'true' if no_encontrado else 'false'}"
            )
            try:
                _logger.info(f"\n{'='*80}")
                _logger.info(f"PETICIÓN AL SERVIDOR API")
                _logger.info(f"{'='*80}")
                _logger.info(f"URL: {base_url}")
                _logger.info(f"RFC: {RFC}")
                _logger.info(f"Periodo: {startDate} - {endDate}")
                _logger.info(f"Tipo: {xml_type}")
                _logger.info(f"API Key (hash): {api_key[:40] if api_key else 'NO CONFIGURADO'}...")
                _logger.info(f"Timeout: 120 segundos")
                _logger.info(f"{'='*80}\n")
                
                response = requests.get(url, verify=False, timeout=120)
                
                _logger.info(f"✅ Respuesta recibida: {response.status_code}")
                
                if response.status_code == 200:
                    data = response.json()
                    xml_count = len(data.get('xmls', []))
                    _logger.info(f"✅ XMLs encontrados: {xml_count}")
                    return data
                else:
                    # Handle other status codes if needed
                    _logger.error(f"❌ Request failed with status code: {response.status_code}")
                    _logger.error(f"Response: {response.text[:200]}")
                    return None
            except requests.exceptions.Timeout:
                print(f"❌ TIMEOUT: El servidor no respondió en 120 segundos")
                print(f"Verificar conectividad con: curl {base_url}")
                return None
            except requests.exceptions.ConnectionError as e:
                print(f"❌ CONNECTION ERROR: {str(e)[:200]}")
                return None
            except requests.exceptions.RequestException as e:
                print(f"❌ Error during request: {str(e)[:200]}")
                return None     
            
        # Create Batch Name
        start_date_str = self.date_start.strftime('%d-%b-%Y')
        end_date_str = self.date_end.strftime('%d-%b-%Y')
        self.write({'name': f"{self.cfdi_type} ({start_date_str} - {end_date_str})"})
        
        create_contact = self.env.company.l10n_mx_xml_download_automatic_contact_creation
        response = fetch_cfdi_data(self._get_default_vat(), self.date_start, self.date_end, self.cfdi_type, self.ingreso, self.egreso, self.pago, self.nomina, self.valido, self.cancelado, self.no_encontrado, self.traslado)

        _logger.info(f"DEBUG: Respuesta del API recibida. Type: {type(response)}, Value: {response if not response or len(str(response)) < 200 else str(response)[:200]+'...'}")
        
        if response:
            xmls_list = response.get("xmls", [])
            total_xmls = len(xmls_list)
            _logger.info(f"Procesando {total_xmls} XMLs del lote {self.name}")
            
            processed_count = 0
            skipped_count = 0
            
            for idx, xml in enumerate(xmls_list, 1):
                try:
                    cfdi_node = fromstring(xml["xmlFile"])
                except etree.XMLSyntaxError:
                    cfdi_info = {}
                    skipped_count += 1
                    _logger.warning(f"XML {idx}/{total_xmls} - Error de sintaxis, se omite")
                    continue

                cfdi_infos = self.env['account.move']._l10n_mx_edi_decode_cfdi_etree(cfdi_node)
                root = ET.fromstring(xml["xmlFile"])

                # Verificar que no se duplique el UUID
                domain = [('name', '=', cfdi_infos.get('uuid'))]
                if self.env['account.edi.downloaded.xml.sat'].search(domain, limit=1):
                    skipped_count += 1
                    if idx % 10 == 0:
                        _logger.info(f"Progreso: {idx}/{total_xmls} XMLs procesados ({skipped_count} omitidos)")
                    continue
                
                # Log progreso cada 10 XMLs
                if idx % 10 == 0:
                    _logger.info(f"Progreso: {idx}/{total_xmls} XMLs procesados ({processed_count} creados, {skipped_count} omitidos)")
              
                """ 'uuid', 'supplier_rfc', 'customer_rfc', 'amount_total', 'cfdi_node', 'usage', 'payment_method'
                'bank_account', 'sello', 'sello_sat', 'cadena', 'certificate_number', 'certificate_sat_number'
                'expedition', 'fiscal_regime', 'emission_date_str', 'stamp_date' """
                
                tax_regime = ""
                rfc = ""
                name = ""
                zip = ""
                # Buscar el partner
                if self.cfdi_type == 'emitidos':
                    rfc = cfdi_infos.get('customer_rfc')
                    partner = self.env['res.partner'].search([('vat', '=', rfc)], limit=1)

                    receptor_element = root.find('.//cfdi:Receptor', namespaces={'cfdi': 'http://www.sat.gob.mx/cfd/4'})
                    tax_regime = receptor_element.get("RegimenFiscal") if receptor_element is not None else None
                    name = receptor_element.get("Nombre") if receptor_element is not None else None
                    zip = receptor_element.get("DomicilioFiscalReceptor") if receptor_element is not None else None

                else: 
                    rfc = cfdi_infos.get('supplier_rfc')
                    partner = self.env['res.partner'].search([('vat', '=', rfc)], limit=1)

                    emisor_element = root.find('.//cfdi:Emisor', namespaces={'cfdi': 'http://www.sat.gob.mx/cfd/4'})
                    tax_regime = emisor_element.get("RegimenFiscal") if emisor_element is not None else None
                    name = emisor_element.get("Nombre") if emisor_element is not None else None
                    zip = cfdi_infos.get('expedition')

                # Si no hay partner y en ajustes esta configurado para crear contacto, lo va a crear 
                if not partner and create_contact: 
                    partner = self.env['res.partner'].create({
                        'vat':rfc,
                        'name': name,
                        'country_id':156, # ID de México
                        'l10n_mx_edi_fiscal_regime':tax_regime,
                        'zip':zip
                    })

                factura = None
                # TODO: Reactivar cuando stored_sat_uuid tenga store=True
                # factura = self.env['account.move'].search([('stored_sat_uuid','=',cfdi_infos.get('uuid'))], limit=1)
                
                # Determinar la empresa correcta según el RFC del XML (con cache)
                correct_company_id = self.company_id.id
                
                if self.cfdi_type == 'emitidos':
                    # En emitidos, usar el RFC del emisor
                    emisor_rfc = cfdi_infos.get('supplier_rfc')
                    if emisor_rfc:
                        if emisor_rfc not in company_cache:
                            company_cache[emisor_rfc] = self.env['res.company'].search([('vat', '=', emisor_rfc)], limit=1)
                        if company_cache[emisor_rfc]:
                            correct_company_id = company_cache[emisor_rfc].id
                else:
                    # En recibidos, usar el RFC del receptor
                    receptor_rfc = cfdi_infos.get('customer_rfc')
                    if receptor_rfc:
                        if receptor_rfc not in company_cache:
                            company_cache[receptor_rfc] = self.env['res.company'].search([('vat', '=', receptor_rfc)], limit=1)
                        if company_cache[receptor_rfc]:
                            correct_company_id = company_cache[receptor_rfc].id
                
                vals = {
                    'name': cfdi_infos.get('uuid'),
                    'cfdi_type': self.cfdi_type,
                    'company_id': correct_company_id,
                    'invoice_id': factura.id if factura else None,
                    'partner_id': partner.id if partner else False,
                    'document_date': root.attrib.get('Fecha'),
                    'state': factura.state if factura else 'not_imported',
                    'document_type': root.get('TipoDeComprobante'),
                    'payment_method': cfdi_infos.get('payment_method'),
                    'payment_method_sat': root.get('FormaPago'),
                    'sub_total': root.get('SubTotal') if root.get('SubTotal') else '0.0',
                    'amount_total': cfdi_infos.get('amount_total') if cfdi_infos.get('amount_total') else '0.0',
                    'serie':root.get('Serie'),
                    'folio':root.get('Folio'),
                    'divisa':root.get('Moneda'),
                    'sat_state':xml['state'],
                    'cfdi_usage': cfdi_infos.get('usage'),
                    'tax_regime': tax_regime,
                    'batch_id':self.id,
                    'discount': -float(root.get("Descuento")) if root.get("Descuento") else None,
                    'sello_cfdi': cfdi_infos.get('sello'),
                    'sello_sat': cfdi_infos.get('sello_sat'),
                    'certificate_number': cfdi_infos.get('certificate_number'),
                    'certificate_sat_number': cfdi_infos.get('certificate_sat_number'),
                    'cadena_original': cfdi_infos.get('cadena_original'),
                }

                if root.get('TipoDeComprobante') == 'P':
                    monto_total_pagos_element = root.find('.//pago20:Totales', {'pago20': 'http://www.sat.gob.mx/Pagos20'})

                    monto_total_pagos = monto_total_pagos_element.get('MontoTotalPagos') if monto_total_pagos_element is not None else ''

                    vals['amount_total'] = monto_total_pagos if monto_total_pagos else ''
                    vals['sub_total'] = monto_total_pagos if monto_total_pagos else ''


                # Creamos los productos del xml
                # recived: boolean to search type of tax
                products = False
                try:
                    products, total_impuestos, total_retenciones = get_products(xml["xmlFile"])
                    vals['total_impuestos'] = total_impuestos
                    vals['total_retenciones'] = total_retenciones
                except:
                    pass
                
                # SIEMPRE crear el registro del XML, tenga o no productos
                # (los XMLs de pago tipo P no tienen productos)
                record = self.env['account.edi.downloaded.xml.sat'].create(vals)
                
                if products:
                    if root.get('TipoDeComprobante') == 'P':
                        for product in products:
                            product['total_amount'] = float(monto_total_pagos)
                    
                    # Asociar los productos al registro ya creado    
                    for product in products:
                        product['downloaded_invoice_id'] = record.id
                    created_products = self.env['account.edi.downloaded.xml.sat.products'].create(products)
                    record.write({'downloaded_product_id': created_products})

                # Crear el attachment del XML
                attachment = self.env['ir.attachment'].create({
                    'name': xml["uuid"] + ".xml",
                    'datas': base64.b64encode(xml["xmlFile"].encode('utf-8')),
                    'res_model': 'account.edi.downloaded.xml.sat',
                    'res_id': record.id,
                    'type': 'binary',
                    'mimetype': 'application/xml',
                })

                # Update the main record with the attachment ID
                record.write({'attachment_id': attachment.id})
                processed_count += 1
                    
            _logger.info(f"Lote {self.name} completado: {processed_count} XMLs creados, {skipped_count} omitidos de {total_xmls} totales")
        self.write({'state': 'imported'})

    def action_update(self): 
        self.action_download()
        self.write({
            'last_update_date':fields.Date.today(),
            'state':'updated',
        })
        # Forzar flush para asegurar que los datos se escriban
        self.env.flush_all()

class DownloadedXmlSatProducts(models.Model):
    _name = "account.edi.downloaded.xml.sat.products"
    _description = "Account Edi Download From SAT Web Service Products"

    sat_id = fields.Many2one('product.unspsc.code', string="Codigo SAT")
    quantity = fields.Float(string="Cantidad", required=True)
    product_metrics = fields.Char(string="Clave Unidad")
    description = fields.Char(string="Descripcion", required=True)
    unit_value = fields.Float(string="Valor Unitario", required=True)
    total_amount = fields.Float(string="Importe", required=True)
    product_rel = fields.Many2one('product.product', string="Producto Odoo")
    tax_id = fields.Many2many('account.tax', string="Impuestos")
    discount = fields.Float(string="Descuento")

    downloaded_invoice_id = fields.Many2one(
        'account.edi.downloaded.xml.sat',
        string='Downloaded product ID',
        ondelete="cascade")
