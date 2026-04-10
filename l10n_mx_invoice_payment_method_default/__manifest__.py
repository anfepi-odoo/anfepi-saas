# -*- coding: utf-8 -*-
{
    'name': 'MX: Heredar y Asignar Forma de Pago Correcta en Facturas',
    'version': '19.0.1.3.2',
    'category': 'Localization/Mexico',
    'summary': 'Hereda forma de pago del cliente y asigna default según policy PUE/PPD (v19 fix)',
    'description': '''
        PROBLEMA RESUELTO:
        ==================
        Al crear facturas desde SO/PACK, no se heredaba correctamente la forma de pago,
        causando que facturas PUE tuvieran forma "99 Por Definir" (ilegal SAT).
        
        SOLUCIÓN:
        =========
        Al crear factura:
        1. Si tiene partner, hereda forma de pago del cliente
        2. Si no tiene forma y es PUE → asigna "03 - Transferencia Electrónica" (default)
        3. Si no tiene forma y es PPD → asigna "99 - Por Definir" (obligatorio SAT)
        4. Valida al guardar que no se usen combinaciones incorrectas
        
        REEMPLAZA:
        ==========
        Este módulo REEMPLAZA la Acción Automatizada ID 21 
        "Factura Cliente PUE y PPD Revisar antes Guardar"
        
        Después de instalar este módulo, DESACTIVAR la acción ID 21:
        UPDATE base_automation SET active = false WHERE id = 21;
        
        REGLAS SAT APLICADAS:
        =====================
        - PPD (Pago Diferido) → SIEMPRE forma "99 Por Definir"
        - PUE (Pago en Una Exhibición) → NUNCA forma "99", cualquier otra (01,03,04,etc)
        
        Default PUE: "03 - Transferencia Electrónica de Fondos"
    ''',
    'author': 'ANFEPI: Roberto Requejo Jiménez',
    'website': 'https://www.anfepi.com',
    'depends': ['account', 'l10n_mx_edi', 'sale'],
    'data': [
        'security/ir.model.access.csv',
        'views/account_move_view.xml',
        'wizard/fix_policy_wizard_view.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
