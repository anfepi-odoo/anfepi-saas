# -*- coding: utf-8 -*-
from odoo import api, fields, models

_ROLE_XMLIDS = [
    # (key, xml_id)  — orden de prioridad: más privilegio primero
    ('config',  'mx_tax_liquidation.group_tax_settlement_config'),
    ('manager', 'mx_tax_liquidation.group_tax_settlement_manager'),
    ('auditor', 'mx_tax_liquidation.group_tax_settlement_auditor'),
    ('user',    'mx_tax_liquidation.group_tax_settlement_user'),
]

# Por cada rol, qué grupos deben estar activos (respetando la cadena implied_ids)
_ROLE_IMPLIES = {
    'config':  ['config', 'manager', 'auditor', 'user'],
    'manager': ['manager', 'user'],
    'auditor': ['auditor', 'user'],
    'user':    ['user'],
}


class ResUsers(models.Model):
    _inherit = 'res.users'

    tax_settlement_role = fields.Selection(
        selection=[
            ('user',    'Usuario — ver liquidaciones y registrar pagos'),
            ('manager', 'Gestor — crear, confirmar y cancelar liquidaciones'),
            ('auditor', 'Auditor — solo lectura + bitácora completa'),
            ('config',  'Configuración — cuentas fiscales y parámetros'),
        ],
        string='Liquidación Fiscal MX',
        compute='_compute_tax_settlement_role',
        inverse='_inverse_tax_settlement_role',
        store=False,
    )

    @api.depends()
    def _compute_tax_settlement_role(self):
        if not self.ids:
            return
        # Resolver IDs de los grupos
        group_ids_by_key = {}
        for key, xmlid in _ROLE_XMLIDS:
            grp = self.env.ref(xmlid, raise_if_not_found=False)
            if grp:
                group_ids_by_key[key] = grp.id

        all_gids = list(group_ids_by_key.values())
        if not all_gids:
            for user in self:
                user.tax_settlement_role = False
            return

        # Consulta directa a la tabla de relación (evita caché ORM)
        self.env.cr.execute(
            "SELECT uid, gid FROM res_groups_users_rel "
            "WHERE uid = ANY(%s) AND gid = ANY(%s)",
            (self.ids, all_gids)
        )
        user_groups = {}
        for uid, gid in self.env.cr.fetchall():
            user_groups.setdefault(uid, set()).add(gid)

        for user in self:
            role = False
            user_gids = user_groups.get(user.id, set())
            for key, _ in _ROLE_XMLIDS:  # prioridad: config > manager > auditor > user
                gid = group_ids_by_key.get(key)
                if gid and gid in user_gids:
                    role = key
                    break
            user.tax_settlement_role = role

    def _inverse_tax_settlement_role(self):
        # Resolver IDs de todos los grupos del módulo
        group_ids = {}
        for key, xmlid in _ROLE_XMLIDS:
            grp = self.env.ref(xmlid, raise_if_not_found=False)
            if grp:
                group_ids[key] = grp.id

        all_gids = list(group_ids.values())
        if not all_gids:
            return

        for user in self:
            # Quitar al usuario de TODOS los grupos del módulo
            self.env.cr.execute(
                "DELETE FROM res_groups_users_rel "
                "WHERE uid = %s AND gid = ANY(%s)",
                (user.id, all_gids)
            )

            # Agregar el grupo seleccionado + todos los que implica
            role = user.tax_settlement_role
            if role and role in _ROLE_IMPLIES:
                keys_to_add = _ROLE_IMPLIES[role]
                gids_to_add = [group_ids[k] for k in keys_to_add if k in group_ids]
                for gid in gids_to_add:
                    self.env.cr.execute(
                        "INSERT INTO res_groups_users_rel (gid, uid) "
                        "VALUES (%s, %s) ON CONFLICT DO NOTHING",
                        (gid, user.id)
                    )

        # Invalidar caché para que los cambios sean visibles de inmediato
        self.invalidate_recordset()
