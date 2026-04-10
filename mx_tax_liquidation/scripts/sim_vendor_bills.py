# -*- coding: utf-8 -*-
"""
Script: sim_vendor_bills.py
Simula 1 factura de proveedor de "Flete" con base $10,000, IVA 16% + Retención IVA 4%
del proveedor "Asesores y Soluciones ANFEPI" en enero 2026, la valida y paga.

Ejecución:
  MSYS_NO_PATHCONV=1 docker exec odoo17_enterprise bash -c "
    sed 's/\r//' /mnt/benotto-addons/mx_tax_liquidation/scripts/sim_vendor_bills.py | \
    python3 /opt/odoo/odoo-core/odoo-bin shell -d odoo17 -c /etc/odoo/odoo.conf --no-http"
"""
from datetime import date
from odoo.exceptions import UserError

env.cr.autocommit = False  # noqa

# ── IDs confirmados en DB ──────────────────────────────────────────────────
PARTNER_ID      = 7      # Asesores y Soluciones ANFEPI
TAX_IVA16       = 22     # 16% compras
TAX_RET_IVA4    = 13     # 4% WH (retención IVA)
JOURNAL_PURCHASE = 2     # Facturas de proveedores
JOURNAL_BANK     = 6     # Banco (BNK1) — para los pagos

# ── Obtener product.product desde product.template id=1 (Flete) ───────────
product_tmpl = env['product.template'].browse(1)
product = product_tmpl.product_variant_ids[:1]
if not product:
    raise ValueError("No se encontró variante de producto para 'Flete' (template id=1)")

# ── Objetos de referencia ──────────────────────────────────────────────────
partner  = env['res.partner'].browse(PARTNER_ID)
tax_iva  = env['account.tax'].browse(TAX_IVA16)
tax_ret  = env['account.tax'].browse(TAX_RET_IVA4)
journal_purchase = env['account.journal'].browse(JOURNAL_PURCHASE)
journal_bank     = env['account.journal'].browse(JOURNAL_BANK)
company          = env['res.company'].browse(1)

print(f"\n{'='*65}")
print(f"  SIMULACIÓN — Facturas de Proveedor con IVA + Retención IVA")
print(f"{'='*65}")
print(f"  Proveedor : {partner.name}")
print(f"  Producto  : {product.name}  (tipo: {product.type})")
print(f"  Impuestos : {tax_iva.name} + {tax_ret.name}")
print(f"  Diario    : {journal_purchase.name}")
print(f"  Banco     : {journal_bank.name}")
print(f"{'='*65}\n")

# ── Datos de las facturas ────────────────────────────────────────────────
#   (fecha_factura, fecha_pago, monto_base, ref_proveedor)
INVOICES = [
    (date(2026, 1, 15), date(2026, 1, 20),  10_000.00, 'ANFEPI/2026-001'),
]

created_invoices = []

for inv_date, pay_date, base_amount, ref in INVOICES:

    # ── 1. Crear factura proveedor ─────────────────────────────────────────
    invoice = env['account.move'].create({
        'move_type'          : 'in_invoice',
        'partner_id'         : partner.id,
        'journal_id'         : journal_purchase.id,
        'invoice_date'       : inv_date,
        'ref'                : ref,
        'company_id'         : company.id,
        'invoice_line_ids'   : [(0, 0, {
            'product_id'     : product.id,
            'name'           : f'Servicio de flete — {ref}',
            'quantity'       : 1.0,
            'price_unit'     : base_amount,
            'tax_ids'        : [(6, 0, [tax_iva.id, tax_ret.id])],
        })],
    })

    # ── 2. Confirmar (post) ────────────────────────────────────────────────
    invoice.action_post()

    # Recalcular montos para reporte
    iva_amount = base_amount * 0.16
    ret_amount = base_amount * 0.04
    net_pay    = base_amount + iva_amount - ret_amount   # lo que se paga al proveedor

    print(f"  [{ref}]  {inv_date}  Base: ${base_amount:>10,.2f}  "
          f"IVA: ${iva_amount:>8,.2f}  RET: ${ret_amount:>7,.2f}  "
          f"Pago proveedor: ${net_pay:>10,.2f}  → {invoice.name}")

    # ── 3. Registrar pago al proveedor ────────────────────────────────────
    #   El pago es por el neto: base + IVA - retención
    #   La retención queda en 216.10.10 pendiente de entero al SAT
    pay_wizard = env['account.payment.register'].with_context(
        active_model='account.move',
        active_ids=[invoice.id],
    ).create({
        'payment_date'  : pay_date,
        'journal_id'    : journal_bank.id,
        'amount'        : net_pay,
        'communication' : ref,
    })
    pay_wizard.action_create_payments()

    created_invoices.append(invoice)

env.cr.commit()
print(f"\n  [✓] {len(created_invoices)} facturas creadas, confirmadas y pagadas.\n")


# ── 4. Resumen consolidado ─────────────────────────────────────────────────
print(f"\n{'='*65}")
print(f"  RESUMEN CONSOLIDADO ENERO 2026")
print(f"{'='*65}")
print(f"  {'Factura':<18} {'Base':>12} {'IVA 16%':>10} {'RET 4%':>9} {'Estado'}")
print(f"  {'-'*18} {'-'*12} {'-'*10} {'-'*9} {'-'*12}")

total_base = total_iva = total_ret = 0.0
for inv in created_invoices:
    base = sum(l.price_subtotal for l in inv.invoice_line_ids)
    iva  = sum(t.amount_currency for t in inv.line_ids
               if t.tax_line_id and t.tax_line_id.amount > 0)
    ret  = sum(abs(t.amount_currency) for t in inv.line_ids
               if t.tax_line_id and t.tax_line_id.amount < 0)
    total_base += base; total_iva += iva; total_ret += ret
    print(f"  {inv.name:<18} ${base:>11,.2f} ${iva:>9,.2f} ${ret:>8,.2f}  {inv.payment_state}")

print(f"  {'─'*18} {'─'*12} {'─'*10} {'─'*9}")
print(f"  {'TOTAL':<18} ${total_base:>11,.2f} ${total_iva:>9,.2f} ${total_ret:>8,.2f}")

print(f"\n  Obligación IVA Retenido en 216.10.10 = ${total_ret:,.2f}")
print(f"  → Este es el monto a liquidar al SAT como IVA_RET en enero 2026.")
print(f"\n{'='*65}")
print(f"  ¿Qué sigue?")
print(f"  Contabilidad → Liquidación Fiscal → Liquidaciones Fiscales → Nuevo")
print(f"  Período: enero 2026 | Concepto: IVA Retenido a Terceros")
print(f"  Calcular Saldos → verificar que muestra ${total_ret:,.2f}")
print(f"{'='*65}\n")
