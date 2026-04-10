from odoo import api, fields, models, tools
from odoo.exceptions import UserError
import xml.etree.ElementTree as ET
import base64

class AccountPayment(models.Model):
    _inherit = 'account.payment'

    stored_sat_uuid = fields.Char(
        compute='_get_uuid_from_xml_attachment', 
        string="CFDI UUID", 
        store=True,
        index=True,  # Índice para búsquedas rápidas
    )

    @api.depends('attachment_ids')
    def _get_uuid_from_xml_attachment(self):
        for record in self:
            # OPTIMIZACIÓN: Filtrar XMLs directamente
            xml_attachments = record.attachment_ids.filtered(
                lambda x: x.mimetype == 'application/xml' and x.name and x.name.lower().endswith('.xml')
            )
            
            if not xml_attachments:
                record.stored_sat_uuid = False
                continue
            
            # Intentar extraer UUID del primer XML válido
            uuid_found = False
            for attachment in xml_attachments:
                try:
                    xml_content = base64.b64decode(attachment.datas)
                    root = ET.fromstring(xml_content)
                    uuid = root.find('.//{http://www.sat.gob.mx/TimbreFiscalDigital}TimbreFiscalDigital').attrib['UUID']
                    record.stored_sat_uuid = uuid
                    uuid_found = True
                    break
                except Exception:
                    continue
            
            if not uuid_found:
                record.stored_sat_uuid = False

class IrAttachment(models.Model):
    _inherit = 'ir.attachment'

    @api.model_create_multi
    def create(self, vals_list):
        """
        Sobrescritura de create para soportar creación múltiple de adjuntos.
        Procesa XMLs de pagos para extraer el UUID del complemento de pago.
        OPTIMIZADO: Solo procesa si es XML de account.payment
        """
        # Asegurar que siempre trabajamos con lista
        if isinstance(vals_list, dict):
            vals_list = [vals_list]
        
        # OPTIMIZACIÓN: Verificar ANTES de crear si hay XMLs de pagos
        # para evitar procesamiento innecesario
        has_payment_xml = any(
            vals.get('mimetype') == 'application/xml' and 
            vals.get('res_model') == 'account.payment'
            for vals in vals_list
        )
        
        # Crear los adjuntos
        attachments = super(IrAttachment, self).create(vals_list)
        
        # OPTIMIZACIÓN: Solo procesar si hay XMLs de pagos
        if not has_payment_xml:
            return attachments
        
        # Procesar SOLO adjuntos XML de account.payment
        payment_xmls = attachments.filtered(
            lambda a: a.mimetype == 'application/xml' and a.res_model == 'account.payment'
        )
        
        for attachment in payment_xmls:
            try:
                payment = self.env['account.payment'].browse(attachment.res_id)
                if payment.exists():
                    data = base64.b64decode(attachment.datas)
                    root = ET.fromstring(data)
                    uuid = root.find('.//{http://www.sat.gob.mx/TimbreFiscalDigital}TimbreFiscalDigital').attrib['UUID']
                    payment.stored_sat_uuid = uuid
            except Exception as e:
                # Silenciar errores de parsing XML para no romper otros adjuntos
                pass
        
        return attachments