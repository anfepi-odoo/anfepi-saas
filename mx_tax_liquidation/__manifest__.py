# -*- coding: utf-8 -*-
{
    'name': 'MX Tax Liquidation — Liquidación de Obligaciones Fiscales',
    'version': '18.0.1.0.0',
    'category': 'Accounting/Mexico',
    'summary': 'Gestión mensual del pago de obligaciones fiscales mexicanas: ISR, IVA, retenciones.',
    'description': """
        Módulo de liquidación de obligaciones fiscales para México (Odoo 17 Enterprise).

        Gestiona el proceso mensual de pago de:
        - ISR por pagar (pago provisional)
        - IVA por pagar neto
        - IVA retenido a terceros
        - Retención ISR por salarios
        - Retención por asimilados a salarios
        - Retención por honorarios / RESICO
        - Retención por arrendamiento
        - Retención por dividendos

        Principio rector: El módulo es un LIQUIDADOR DE SALDOS CONTABLES.
        No recalcula impuestos. Solo cancela pasivos fiscales contra bancos.
    """,
    'author': 'ANFEPI: Roberto Requejo Jiménez',
    'website': 'https://www.anfepi.com',
    'license': 'OPL-1',
    'depends': [
        'account',
        'account_accountant',
        'mail',
        'l10n_mx',
    ],
    'data': [
        # Security
        'security/security_groups.xml',
        'security/ir.model.access.csv',
        'security/security_rules.xml',
        # Data
        'data/mx_tax_settlement_sequence.xml',
        'data/mx_tax_concept_data.xml',
        # Reports (must be before views — buttons reference report action XML IDs)
        'report/mx_tax_settlement_report.xml',
        'report/mx_tax_conciliation_report.xml',
        # Views
        'views/mx_tax_concept_views.xml',
        'views/mx_tax_settlement_config_views.xml',
        'views/mx_tax_settlement_views.xml',
        'views/mx_tax_settlement_log_views.xml',
        'views/mx_tax_settlement_pay_wizard_views.xml',
        'views/mx_tax_settlement_cancel_wizard_views.xml',
        'views/res_config_settings_views.xml',
        'views/res_users_views.xml',
        'views/menus.xml',
    ],
    'demo': [],
    'installable': True,
    'auto_install': False,
    'application': False,
    'images': ['static/description/icon.png'],
}
