# -*- coding: utf-8 -*-
from odoo import models, fields, api
import base64
import csv
from io import StringIO

class L10nMxArt69BImportWizard(models.TransientModel):
    _name = 'l10n_mx.art69b.import.wizard'
    _description = 'Importar Lista Art 69-B desde CSV'

    csv_file = fields.Binary(string='Archivo CSV', required=True)
    filename = fields.Char(string='Nombre archivo')
    tipo_lista = fields.Selection([
        ('definitivo', 'Listado Definitivo'),
        ('presuncion', 'Listado Presunción')
    ], string='Tipo de Lista', required=True, default='definitivo')

    def import_csv(self):
        """Importar CSV del SAT y actualizar lista negra"""
        # Decodificar archivo
        csv_data = base64.b64decode(self.csv_file)
        csv_text = csv_data.decode('utf-8')
        csv_file = StringIO(csv_text)
        # Parsear CSV
        reader = csv.DictReader(csv_file)
        # Marcar todos como inactivos
        self.env['l10n_mx.art69b.blacklist'].search([]).write({'activo': False})
        nuevos = 0
        actualizados = 0
        for row in reader:
            rfc = row.get('RFC', '').strip().upper()
            if not rfc or len(rfc) < 12:
                continue
            vals = {
                'rfc': rfc,
                'razon_social': row.get('Nombre', row.get('Razón Social', '')).strip(),
                'situacion': self.tipo_lista,
                'fecha_publicacion': self._parse_fecha(row.get('Fecha Publicación DOF', '')),
                'numero_publicacion': row.get('Número DOF', '').strip(),
                'supuesto': row.get('Supuesto', 'Art. 69-B').strip(),
                'activo': True,
                'fecha_ultima_actualizacion': fields.Date.today()
            }
            existing = self.env['l10n_mx.art69b.blacklist'].search([('rfc', '=', rfc)])
            if existing:
                existing.write(vals)
                actualizados += 1
            else:
                vals['fecha_primera_deteccion'] = fields.Date.today()
                self.env['l10n_mx.art69b.blacklist'].create(vals)
                nuevos += 1
        # Actualizar alertas en XMLs
        self._actualizar_alertas_xmls()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Importación Completada',
                'message': f'Nuevos: {nuevos}, Actualizados: {actualizados}',
                'type': 'success',
                'sticky': False,
            }
        }

    def _parse_fecha(self, fecha_str):
        """Convertir fecha del formato del SAT"""
        from datetime import datetime
        if not fecha_str:
            return False
        formatos = ['%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y']
        for formato in formatos:
            try:
                return datetime.strptime(fecha_str.strip(), formato).date()
            except ValueError:
                continue
        return False

    def _actualizar_alertas_xmls(self):
        """Actualizar campo alerta_fiscal en XMLs existentes"""
        self.env['account.edi.downloaded.xml.sat'].search([])._compute_fiscal_alert()
