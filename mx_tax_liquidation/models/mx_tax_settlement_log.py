# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import AccessError


class MxTaxSettlementLog(models.Model):
    _name = 'mx.tax.settlement.log'
    _description = 'Bitácora de Auditoría — Liquidaciones Fiscales'
    _order = 'timestamp desc, id desc'
    _log_access = False  # Control manual de timestamps

    settlement_id = fields.Many2one(
        comodel_name='mx.tax.settlement',
        string='Liquidación',
        required=True,
        index=True,
        ondelete='cascade',
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        related='settlement_id.company_id',
        store=True,
        readonly=True,
        index=True,
    )
    action = fields.Selection(
        selection=[
            ('create', 'Creación'),
            ('calculate', 'Cálculo de Saldos'),
            ('confirm', 'Confirmación'),
            ('pay', 'Registro de Pago'),
            ('cancel', 'Cancelación'),
            ('modify_line', 'Modificación de Línea'),
            ('attach', 'Adjunto de Documento'),
        ],
        string='Acción',
        required=True,
        index=True,
    )
    user_id = fields.Many2one(
        comodel_name='res.users',
        string='Usuario',
        required=True,
        ondelete='restrict',
    )
    timestamp = fields.Datetime(
        string='Fecha y Hora',
        required=True,
        default=fields.Datetime.now,
        index=True,
    )
    description = fields.Text(
        string='Descripción',
        required=True,
    )
    value_before = fields.Text(
        string='Valor Anterior',
        help='Representación JSON de los valores antes del cambio.',
    )
    value_after = fields.Text(
        string='Valor Posterior',
        help='Representación JSON de los valores después del cambio.',
    )
    ip_address = fields.Char(
        string='Dirección IP',
        readonly=True,
    )
    payment_id = fields.Many2one(
        comodel_name='mx.tax.settlement.payment',
        string='Pago Relacionado',
        ondelete='set null',
    )

    # =========================================================
    # INMUTABILIDAD: write y unlink bloqueados
    # =========================================================

    def write(self, vals):
        raise AccessError(
            'Los registros de bitácora de auditoría son inmutables. '
            'No se permite modificar entradas de la bitácora.'
        )

    def unlink(self):
        raise AccessError(
            'Los registros de bitácora de auditoría no pueden ser eliminados. '
            'Esta restricción garantiza la integridad del rastro de auditoría.'
        )

    @api.autovacuum
    def _gc_old_logs(self):
        """
        Archivado automático de logs muy antiguos (>5 años) conforme al Art. 30 CFF.
        Solo marca como archivados, nunca elimina físicamente.
        """
        pass  # Implementación futura: marcar campo archived=True para logs > 5 años
