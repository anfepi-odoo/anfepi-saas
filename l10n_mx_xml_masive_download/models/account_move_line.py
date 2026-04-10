from odoo import api, models, fields # type: ignore
from odoo.exceptions import UserError # type: ignore
from datetime import timedelta

class AccountInvoice(models.Model):
    _inherit = "account.move"

    l10n_edi_imported_from_sat = fields.Boolean(
        "Created with DMS?", copy=False, help="Is market if the document was created with DMS."
    )

    def xml2record(self, default_account=False, analytic_account=False):
        """Called by the Documents workflow row during the creation of records by the Create EDI document button.
        Use the last attachment in the xml and fill data in records.

        :param default_account: Account that will be used in the invoice lines where the product is not fount. If it's
        empty, is used the journal account.
        :type domain: list
        """

        return self

    def l10n_edi_document_set_partner(self, domain=None):
        """Perform a :meth:`search` followed by a :meth:`read`.

        :param domain: Search domain, Defaults to an empty domain that will match all records.
        :type domain: list

        :return: True or False
        :rtype: bool"""
        self.ensure_one()
        partner = self.env["res.partner"]

        xml_partner = partner.search(domain, limit=1)
        if not xml_partner:
            return False

        self.partner_id = xml_partner
        self._onchange_partner_id()
        return True

    def _get_edi_document_errors(self):
        # Overwrite for each country and document type
        self.ensure_one()
        return []

    def collect_taxes(self, taxes_xml):
        """
        Get tax data of the Impuesto node of the xml and return
        dictionary with taxes datas
        :param taxes_xml: Impuesto node of xml
        :type taxes_xml: etree
        :return: A list with the taxes data
        :rtype: list
        """
        return []

class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    downloaded_product_rel = fields.Many2one('account.edi.downloaded.xml.sat.products', string='Downloaded Product')
    
    # ============================================================================
    # NUEVOS CAMPOS PARA DOCUMENTO ORIGEN (NO AFECTA FUNCIONALIDAD EXISTENTE)
    # ============================================================================
    origin_document_id = fields.Many2one(
        'account.move',
        string='Documento Origen',
        help='Documento origen relacionado (SO/PO/Factura)',
        index=True,
        copy=False,
        readonly=True,  # Solo se llena por búsqueda automática/manual
    )
    
    origin_document_name = fields.Char(
        string='Referencia Origen',
        compute='_compute_origin_document_name',
        search='_search_origin_document_name',
        help='Nombre del documento origen (SO001, PO042, etc.)'
    )
    
    origin_document_type = fields.Selection([
        ('sale_order', 'Pedido de Venta'),
        ('purchase_order', 'Orden de Compra'),
        ('invoice', 'Factura'),
        ('other', 'Otro')
    ], string='Tipo Documento', compute='_compute_origin_document_name')

    @api.onchange('product_id')
    def update_downloaded_product(self):
        if self.downloaded_product_rel:
            self.downloaded_product_rel.write({'product_rel':self.product_id.id})
     

    @api.depends("product_id")
    def _compute_product_uom_id(self):
        # OPTIMIZACIÓN: Solo filtrar si hay líneas importadas del SAT
        # Evita filtrado innecesario en TODAS las líneas de factura
        dms = self.env['account.move.line']
        if any(l.move_id.l10n_edi_imported_from_sat for l in self):
            dms = self.filtered(
                lambda l: l.move_id.l10n_edi_imported_from_sat
                and l.product_id
                and l.display_type not in ("line_section", "line_note")
                and l._origin
            )
        return super(AccountMoveLine, self - dms)._compute_tax_ids()

    # ============================================================================
    # MÉTODOS PARA DOCUMENTO ORIGEN (NUEVOS - NO MODIFICAN FUNCIONALIDAD ACTUAL)
    # ============================================================================
    
    @api.depends('origin_document_id')
    def _compute_origin_document_name(self):
        """Calcula el nombre y tipo del documento origen - OPTIMIZADO."""
        for record in self:
            origin = record.origin_document_id
            
            if not origin:
                record.origin_document_name = False
                record.origin_document_type = False
                continue
            
            origin_ref = origin.invoice_origin
            if origin_ref:
                if 'SO' in origin_ref or 'S0' in origin_ref:
                    record.origin_document_type = 'sale_order'
                    record.origin_document_name = origin_ref
                elif 'PO' in origin_ref or 'P0' in origin_ref:
                    record.origin_document_type = 'purchase_order'
                    record.origin_document_name = origin_ref
                else:
                    record.origin_document_type = 'invoice'
                    record.origin_document_name = origin.name
            else:
                record.origin_document_type = 'invoice'
                record.origin_document_name = origin.name
    
    def _search_origin_document_name(self, operator, value):
        """Búsqueda customizada para origin_document_name."""
        if operator == '!=' and not value:
            return [('origin_document_id', '!=', False)]
        elif operator == '=' and not value:
            return [('origin_document_id', '=', False)]
        else:
            return [('origin_document_id.invoice_origin', operator, value)]
    
    def _search_origin_document_emitidos(self):
        """
        Buscar documento origen para XMLs Emitidos (Facturas Cliente).
        Solo se ejecuta si se llama manualmente, NO afecta el flujo normal.
        """
        self.ensure_one()
        
        if not self.move_id or self.move_id.move_type != 'out_invoice':
            return False
            
        move = self.move_id
        
        # Buscar factura existente que tenga invoice_origin (SO)
        if move.invoice_origin:
            # Ya tiene origen directo, usarlo
            existing_invoice = self.env['account.move'].search([
                ('name', '=', move.name),
                ('invoice_origin', '!=', False),
                ('state', '!=', 'cancel')
            ], limit=1)
            if existing_invoice:
                return existing_invoice
        
        # Buscar SO por criterios de similitud
        domain = [
            ('partner_id', '=', move.partner_id.id),
            ('state', 'in', ['sale', 'done']),
            ('amount_total', '>=', move.amount_total * 0.95),
            ('amount_total', '<=', move.amount_total * 1.05),
        ]
        
        if move.invoice_date:
            date_from = move.invoice_date - timedelta(days=30)
            date_to = move.invoice_date + timedelta(days=30)
            domain.extend([
                ('date_order', '>=', date_from),
                ('date_order', '<=', date_to)
            ])
        
        sale_order = self.env['sale.order'].search(domain, limit=1, order='date_order desc')
        
        if sale_order:
            # Buscar factura de esa SO
            invoice = self.env['account.move'].search([
                ('invoice_origin', '=', sale_order.name),
                ('partner_id', '=', move.partner_id.id),
                ('move_type', '=', 'out_invoice'),
                ('state', '!=', 'cancel')
            ], limit=1)
            return invoice
        
        return False
    
    def _search_origin_document_recibidos(self):
        """
        Buscar documento origen para XMLs Recibidos (Facturas Proveedor).
        Solo se ejecuta si se llama manualmente, NO afecta el flujo normal.
        """
        self.ensure_one()
        
        if not self.move_id or self.move_id.move_type not in ['in_invoice', 'in_refund']:
            return False
            
        move = self.move_id
        
        # Buscar factura existente que tenga invoice_origin (PO)
        if move.invoice_origin:
            existing_invoice = self.env['account.move'].search([
                ('name', '=', move.name),
                ('invoice_origin', '!=', False),
                ('state', '!=', 'cancel')
            ], limit=1)
            if existing_invoice:
                return existing_invoice
        
        # Buscar PO por criterios de similitud
        domain = [
            ('partner_id', '=', move.partner_id.id),
            ('state', 'in', ['purchase', 'done']),
            ('amount_total', '>=', move.amount_total * 0.95),
            ('amount_total', '<=', move.amount_total * 1.05),
        ]
        
        if move.invoice_date:
            date_from = move.invoice_date - timedelta(days=45)
            date_to = move.invoice_date + timedelta(days=15)
            domain.extend([
                ('date_order', '>=', date_from),
                ('date_order', '<=', date_to)
            ])
        
        purchase_order = self.env['purchase.order'].search(domain, limit=1, order='date_order desc')
        
        if purchase_order:
            # Buscar factura de esa PO
            invoice = self.env['account.move'].search([
                ('invoice_origin', '=', purchase_order.name),
                ('partner_id', '=', move.partner_id.id),
                ('move_type', 'in', ['in_invoice', 'in_refund']),
                ('state', '!=', 'cancel')
            ], limit=1)
            return invoice
        
        return False
    
    def action_search_origin_document(self):
        """
        Acción MANUAL para buscar documento origen.
        NO se ejecuta automáticamente, solo cuando el usuario lo solicita.
        100% SEGURO - No afecta flujos existentes.
        """
        found_count = 0
        not_found_count = 0
        
        for record in self:
            # Saltar si ya tiene origen
            if record.origin_document_id:
                continue
                
            if not record.move_id:
                not_found_count += 1
                continue
            
            origin = False
            
            # Determinar tipo y buscar
            if record.move_id.move_type == 'out_invoice':
                origin = record._search_origin_document_emitidos()
            elif record.move_id.move_type in ['in_invoice', 'in_refund']:
                origin = record._search_origin_document_recibidos()
            
            if origin:
                record.origin_document_id = origin.id
                found_count += 1
            else:
                not_found_count += 1
        
        # Mensaje de resultados
        message = f'✓ {found_count} documentos encontrados'
        if not_found_count > 0:
            message += f'\n⊘ {not_found_count} sin coincidencias'
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Búsqueda de Documentos Origen',
                'message': message,
                'type': 'success' if found_count > 0 else 'warning',
                'sticky': False,
            }
        }

    @api.depends("product_id")
    def _compute_product_uom_id(self):
        # OPTIMIZACIÓN: Solo filtrar si hay líneas importadas del SAT
        # Evita filtrado innecesario en TODAS las líneas de factura
        dms = self.env['account.move.line']
        if any(l.move_id.l10n_edi_imported_from_sat for l in self):
            dms = self.filtered(
                lambda l: l.move_id.l10n_edi_imported_from_sat
                and l.product_id
                and l.display_type not in ("line_section", "line_note")
                and l._origin
            )
        return super(AccountMoveLine, self - dms)._compute_product_uom_id()

    @api.depends("product_id", "product_uom_id")
    def _compute_price_unit(self):
        # OPTIMIZACIÓN: Solo filtrar si hay líneas importadas del SAT
        dms = self.env['account.move.line']
        if any(l.move_id.l10n_edi_imported_from_sat for l in self):
            dms = self.filtered(
                lambda l: l.move_id.l10n_edi_imported_from_sat
                and l.product_id
                and l.display_type not in ("line_section", "line_note")
                and l._origin
            )
        return super(AccountMoveLine, self - dms)._compute_price_unit()

    @api.depends("product_id", "product_uom_id")
    def _compute_tax_ids(self):
        # OPTIMIZACIÓN: Solo filtrar si hay líneas importadas del SAT
        dms = self.env['account.move.line']
        if any(l.move_id.l10n_edi_imported_from_sat for l in self):
            dms = self.filtered(
                lambda l: l.move_id.l10n_edi_imported_from_sat
                and l.product_id
                and l.display_type not in ("line_section", "line_note")
                and l._origin
            )
        return super(AccountMoveLine, self - dms)._compute_tax_ids()
