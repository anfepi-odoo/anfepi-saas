# -*- coding: utf-8 -*-
{
    'name': "Importación XML a Factura",

    'summary': """
       Carga Masiva por medio de Archivos ZIP.
       """,

    'description': """
       Carga Masiva de XML para la creación de Facturas.
    """,

    'author': "German Ponce Dominguez",
    'website': "http://poncesoft.blogspot.com",
    'category': 'Invoicing',
    'version': '1.7',

    'maintainer':"German Ponce Dominguez",

    'depends': [
        'account',
        'sale_management',
        'base_vat',
        'base_address_extended',
        'l10n_mx_edi',
        ],

    'data': [
        'security/ir.model.access.csv',
        'views/extra_fit_views.xml',
        'views/partner_views.xml',         
    ],
    'demo': [],
    'installable': True,
    'auto_install': False,
}
