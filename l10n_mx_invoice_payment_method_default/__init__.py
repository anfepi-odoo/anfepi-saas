# -*- coding: utf-8 -*-
from . import models
from . import wizard
import logging

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """
    Reactiva el registro code='99' (Por Definir) en l10n_mx_edi.payment.method.

    Se usa SQL directo porque:
    1. search() sin active_test=False NO encuentra el registro (active=False).
    2. ORM create() dispara @api.constrains('code') que detecta el registro
       inactivo existente y lanza "A payment method with the same code already exists".
    3. ORM write({'active': True}) también dispara la misma constraint.
    El UPDATE por SQL actualiza la fila directamente sin pasar por el ORM.
    """
    env.cr.execute("""
        UPDATE l10n_mx_edi_payment_method
           SET active = true
         WHERE code = '99'
    """)
    updated = env.cr.rowcount
    if updated:
        _logger.info('post_init_hook: %d registro(s) code=99 reactivados via SQL', updated)
    else:
        # No existe en absoluto: insertar también via SQL
        env.cr.execute("""
            INSERT INTO l10n_mx_edi_payment_method
                   (name, code, active, create_uid, write_uid, create_date, write_date)
            VALUES ('Por definir', '99', true, 1, 1, now(), now())
            ON CONFLICT DO NOTHING
        """)
        _logger.info('post_init_hook: registro code=99 creado via SQL INSERT')
