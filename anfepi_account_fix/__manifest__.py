# -*- coding: utf-8 -*-
{
    'name': 'ANFEPI - Restaurar Cuenta ISR A Favor',
    'version': '16.0.1.0.0',
    'category': 'Accounting',
    'summary': 'Restaura la cuenta contable 113.02.01 ISR A Favor eliminada durante la migración',
    'description': """
        Este módulo restaura la cuenta contable 113.02.01 ISR A Favor
        que desapareció durante la migración a Odoo 16.
        
        La cuenta se crea automáticamente para todas las compañías activas
        que utilicen la localización mexicana (l10n_mx) y no tengan
        ya definida esa cuenta.
    """,
    'author': 'ANFEPI',
    'depends': [
        'account',
        'l10n_mx',
    ],
    'data': [],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'auto_install': False,
    'application': False,
    'license': 'LGPL-3',
}
