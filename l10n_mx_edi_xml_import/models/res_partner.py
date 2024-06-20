# -*- coding: utf-8 -*-
from odoo import api, exceptions, fields, models, _

class ResPartner(models.Model):
    _inherit = 'res.partner'

    def _get_xml_import_account_domain(self):
        domain = [
         ('deprecated', '=', False)]
        return domain

    default_xml_import_account = fields.Many2one('account.account', string='Cuenta de importacion de xml',
      help='Esta cuenta se usara cuando se importen facturas de esta empresa por medio de xmls ',
      domain=(lambda self: self._get_xml_import_account_domain()))

