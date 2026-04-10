# -*- coding: utf-8 -*-
from odoo import models, fields, api
from datetime import date

class ConciliationReportWizard(models.TransientModel):
    _name = 'conciliation.report.wizard'
    _description = 'Asistente de Reporte de Conciliación SAT vs Odoo'

    start_date = fields.Date(
        string='Fecha Inicio', 
        required=True,
        default=lambda self: date(date.today().year, 1, 1)
    )
    end_date = fields.Date(
        string='Fecha Fin', 
        required=True,
        default=fields.Date.today
    )

    def action_generate_report(self):
        """Genera el reporte de conciliación y abre la vista list"""
        self.ensure_one()
        return self.env['sat.conciliation.report'].generate_report(self.start_date, self.end_date)