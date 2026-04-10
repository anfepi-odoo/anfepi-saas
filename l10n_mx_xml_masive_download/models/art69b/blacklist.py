# -*- coding: utf-8 -*-
from odoo import models, fields, api

class L10nMxArt69BBlacklist(models.Model):
    _name = 'l10n_mx.art69b.blacklist'
    _description = 'Lista Negra Art 69-B del SAT (EFOs)'
    _rec_name = 'rfc'

    rfc = fields.Char(string='RFC', required=True, index=True, size=13)
    razon_social = fields.Char(string='Razón Social', size=500)
    situacion = fields.Selection([
        ('presuncion', 'Presunción'),
        ('definitivo', 'Definitivo'),
        ('desvirtuado', 'Desvirtuado')
    ], string='Situación')
    fecha_publicacion = fields.Date(string='Fecha Publicación DOF')
    numero_publicacion = fields.Char(string='Número DOF')
    supuesto = fields.Char(string='Supuesto Legal')
    activo = fields.Boolean(string='Activo en Lista', default=True, index=True)
    fecha_primera_deteccion = fields.Date(string='Primera Detección')
    fecha_ultima_actualizacion = fields.Date(string='Última Actualización')
    notas = fields.Text(string='Notas')

    _sql = models.Constraint('UNIQUE(rfc)', 'El RFC ya existe en la lista negra')

    def download_from_sat(self):
        """Descargar y actualizar lista negra desde el SAT (implementación básica, puede mejorarse)"""
        # Aquí se puede implementar la descarga automática de los CSV del SAT
        pass
