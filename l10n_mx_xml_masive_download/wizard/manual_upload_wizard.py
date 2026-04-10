# models/manual_upload_wizard.py
from odoo import models, fields, api
from odoo.exceptions import UserError
from difflib import SequenceMatcher 
import xml.etree.ElementTree as ET
import zipfile
import base64
from lxml import etree
import io
from lxml.objectify import fromstring

CFDI_CODE_TO_TAX_TYPE = {
    '001': 'Tasa',
    '002': 'Cuota',
    '003': 'Exento',
}

class ManualUploadWizard(models.TransientModel):
    _name = 'manual.upload.wizard'
    _description = 'Manual Upload Wizard'

    download_batch_id = fields.Many2one('account.edi.api.download', string="Download Record", readonly=True)
    file_data = fields.Binary(string="Archivo Zip con XMLs", required=True)

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if self.env.context.get('active_id'):
            res['download_batch_id'] = self.env.context['active_id']
        return res

    def action_process_upload(self):
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
                domain = [
                    #*self.env['account.journal']._check_company_domain(company_id),
                    ('amount', '=', amount),
                    ('type_tax_use', '=', 'sale' if self.cfdi_type.cfdi_type == 'emitidos' else 'purchase'),
                    ('amount_type', '=', 'percent'),
                ]
                tax_type = CFDI_CODE_TO_TAX_TYPE.get(tax_node.attrib.get('Impuesto'))
                if tax_type:
                    domain.append(('l10n_mx_tax_type', '=', tax_type))
                taxes = self.env['account.tax'].search(domain, limit=1)
                if not taxes:
                    raise UserError("No se encotro un impuesto para el siguiente: "+tax_type+" "+str(amount))
                return taxes[:1]
            except: 
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
                    # Buscamos a ver si ya se relaciono el producto
                    domain = [
                        ('sat_id.code', '=', clave_prod_serv),
                        ('downloaded_invoice_id.partner_id', '!=', False)
                        ]
                    
                    products = self.env['account.edi.downloaded.xml.sat.products'].search(domain, limit=1)
                    final_product = False
                    if products:
                        for product in products:
                            if similar(descripcion, product.description) > 0.8:
                                final_product=product.product_rel
                                break

                    # Create a dictionary for each concepto and append it to the list
                    concepto_info = {
                        'sat_id':self.env['product.unspsc.code'].search([('code','=',clave_prod_serv)]).id,
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
             

        
        create_contact = self.env.company.l10n_mx_xml_download_automatic_contact_creation


        response = base64.b64decode(self.file_data)

        # Handle zipfile response
        if isinstance(response, bytes):
            # If response is bytes, create a zipfile from it
            zip_buffer = io.BytesIO(response)
            with zipfile.ZipFile(zip_buffer, 'r') as zip_file:
                xml_files = []
                for file_info in zip_file.infolist():
                    if file_info.filename.endswith('.xml'):
                        xml_content = zip_file.read(file_info.filename)
                        # Extract UUID from filename or XML content
                        try:
                            root = ET.fromstring(xml_content)
                            uuid = root.get('UUID') or file_info.filename.replace('.xml', '')
                        except:
                            uuid = file_info.filename.replace('.xml', '')
                        
                        xml_files.append({
                            'xmlFile': xml_content,
                            'uuid': uuid,
                            'state': 'Vigente'  # Default state, adjust as needed
                        })
        else:
            # Fallback for dictionary format (backward compatibility)
            xml_files = response.get("xmls", [])

        for xml in xml_files:
            try:
                cfdi_node = fromstring(xml["xmlFile"])
            except etree.XMLSyntaxError:
                cfdi_info = {}
                continue

            cfdi_infos = self.env['account.move']._l10n_mx_edi_decode_cfdi_etree(cfdi_node)
            root = ET.fromstring(xml["xmlFile"])

            # Verificar que no se duplique el UUID
            domain = [('name', '=', cfdi_infos.get('uuid'))]
            if self.env['account.edi.downloaded.xml.sat'].search(domain, limit=1):
                continue
            
            """ 'uuid', 'supplier_rfc', 'customer_rfc', 'amount_total', 'cfdi_node', 'usage', 'payment_method'
            'bank_account', 'sello', 'sello_sat', 'cadena', 'certificate_number', 'certificate_sat_number'
            'expedition', 'fiscal_regime', 'emission_date_str', 'stamp_date' """
            
            tax_regime = ""
            rfc = ""
            name = ""
            zip = ""
            # Buscar el partner
            if self.download_batch_id.cfdi_type == 'emitidos':
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
            factura = self.env['account.move'].search([('stored_sat_uuid','=',cfdi_infos.get('uuid'))], limit=1)
            
            vals = {
                'name': cfdi_infos.get('uuid'),
                'cfdi_type': self.download_batch_id.cfdi_type,
                'company_id': self.download_batch_id.company_id.id,
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
                'sat_state':xml.get('state', 'vigente'),  # Use get() with default value
                'cfdi_usage': cfdi_infos.get('usage'),
                'tax_regime': tax_regime,
                'batch_id':self.download_batch_id.id,
                'discount': -float(root.get("Descuento")) if root.get("Descuento") else None,
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
            
            if products:
                if root.get('TipoDeComprobante') == 'P':
                    for product in products:
                        product['total_amount'] = float(monto_total_pagos)
                
                created_products = self.env['account.edi.downloaded.xml.sat.products'].create(products)
                vals['downloaded_product_id'] = created_products

                record = self.env['account.edi.downloaded.xml.sat'].create(vals)
                attachment = self.env['ir.attachment'].create({
                    'name': xml.get("uuid", cfdi_infos.get('uuid')) + ".xml",  # Use get() with fallback
                    'datas': base64.b64encode(xml["xmlFile"]),
                    'res_model': 'account.edi.downloaded.xml.sat',
                    'res_id': record.id,
                    'type': 'binary',
                    'mimetype': 'application/xml',
                })

                # Update the main record with the attachment ID
                record.write({'attachment_id': attachment.id})

        self.download_batch_id.write({'state': 'imported'})