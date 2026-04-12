# -*- coding: utf-8 -*-
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

{
    'name': 'XML Masive Download',
    'version': '19.0.31.0',
    'category': 'Hidden',
    'author':'ANFEPI: Roberto Requejo Jiménez y Roberto Requejo Fernández',
    'description': """
XML Masive Download from SAT WebService
========================================

Download, import and manage XML files from SAT (Mexican Tax Authority) automatically.

Main Features:
--------------
* Automatic XML download from SAT for emitted and received invoices
* Batch processing with configurable date ranges
* Smart invoice matching and import
* Origin document tracking (Sales Orders/Purchase Orders)
* SAT status validation and updates
* Multi-company support with automatic FIEL configuration
* Performance optimized for large volumes

Origin Document Tracking:
-------------------------
* Link downloaded XMLs to their source documents (SO/PO)
* Smart search with flexible matching criteria
* Manual batch processing available
* Filters and grouping by document type

SAT vs Odoo Reconciliation Report:
----------------------------------
* Professional reconciliation report
* Compare SAT XMLs against Odoo invoices and payments
* Color-coded differences (green=match, yellow=variance, red/blue=large gaps)
* Drill-down functionality with smart buttons:
  - View related SAT XMLs
  - Access Odoo invoices/credit notes
  - Check payment complements
* Automatic calculation of variances and percentages
* Separate tracking for issued and received documents
* Filter ignored documents to focus on real differences

Technical Features:
-------------------
* Optimized database queries for better performance
* Automatic cleanup of temporary files
* Comprehensive error handling and logging
* Compatible with Odoo 17 Enterprise

    """,
    'depends': ['l10n_mx_edi', 'account', 'base', 'mail', 'sale', 'purchase'],
    'external_dependencies': {
        'python': ['pdf417gen'],
    },
    'data': [
        'security/security.xml',
        'security/ir_rules.xml',
        'security/ir.model.access.csv',
        'data/ir_cron.xml',
        'wizard/invoice_wizard_views.xml',
        'wizard/upload_fiel_wizard.xml',
        'wizard/manual_upload_wizard_view.xml',
        'wizard/conciliaton_report_wizard_views.xml',
        'views/l10n_mx_edi_view.xml',
        'views/art69b_views.xml',
        'views/res_company_view.xml',
        'views/account_move_view.xml',
        'views/account_move_line_origin_view.xml',
        'views/custom_accounting_settings_view.xml',
        'models/server_actions.xml',
        'data/server_actions.xml',
        # 'models/server_action_fix_company.xml',  # DESHABILITADO: Ya no es necesario porque ahora asigna la empresa correcta desde el inicio
        'report/product_report.xml',
        'report/ir_actions_report.xml',
        'report/reporte_conciliacion_view_new.xml',
        'report/reporte_conciliacion_form_view.xml',
    ],
    'images': ['static/description/icon.png'],
    'auto_install': False,
    "license": "AGPL-3",

}
