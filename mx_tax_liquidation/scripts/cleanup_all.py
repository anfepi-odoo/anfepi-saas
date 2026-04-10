import logging
_logger = logging.getLogger(__name__)

print("="*60)
print("LIMPIEZA COMPLETA - INICIO")
print("="*60)

# 1. Cancelar y borrar pagos al SAT
print("\n[1] Cancelando pagos al SAT...")
sat_payments = env['mx.tax.settlement.payment'].search([])
for sp in sat_payments:
    if sp.move_id:
        move = sp.move_id
        if move.state == 'posted':
            move.button_draft()
            print("   Asiento %s -> borrador" % move.name)
        move.unlink()
        print("   Asiento eliminado")
    sp.unlink()
    print("   Pago SAT eliminado")
env.cr.commit()
print("   OK Pagos SAT eliminados")

# 2. Borrar lineas y liquidaciones
print("\n[2] Borrando liquidaciones...")
settlements = env['mx.tax.settlement'].search([])
for s in settlements:
    name = s.name
    env.cr.execute("UPDATE mx_tax_settlement_line SET line_state='pending' WHERE settlement_id=%s", (s.id,))
    env.cr.execute("UPDATE mx_tax_settlement SET state='confirmed' WHERE id=%s", (s.id,))
    env.cr.commit()
    lines = env['mx.tax.settlement.line'].search([('settlement_id', '=', s.id)])
    lines.unlink()
    s.unlink()
    print("   Liquidacion '%s' eliminada" % name)
env.cr.commit()
print("   OK Liquidaciones eliminadas")

# 3. Cancelar pagos de proveedor y sus asientos CBMX
print("\n[3] Cancelando pagos de proveedor (PBNK y CBMX)...")
payments = env['account.payment'].search([('payment_type', '=', 'outbound')])
print("   Encontrados %d pagos" % len(payments))

for pay in payments:
    move = pay.move_id
    if not move:
        continue
    move_name = move.name
    for line in move.line_ids:
        if line.matched_debit_ids or line.matched_credit_ids:
            (line.matched_debit_ids + line.matched_credit_ids).unlink()
    if move.state == 'posted':
        move.button_draft()
    move.button_cancel()
    print("   %s cancelado" % move_name)

cbmx_moves = env['account.move'].search([('name', 'ilike', 'CBMX/')])
for m in cbmx_moves:
    if m.state == 'posted':
        m.button_draft()
    m.button_cancel()
    print("   %s cancelado" % m.name)

env.cr.commit()
print("   OK Pagos y CBMX cancelados")

# 4. Cancelar facturas
print("\n[4] Cancelando facturas de proveedor...")
invoices = env['account.move'].search([('move_type', '=', 'in_invoice'), ('state', '=', 'posted')])
print("   Encontradas %d facturas" % len(invoices))
for inv in invoices:
    for line in inv.line_ids:
        if line.matched_debit_ids or line.matched_credit_ids:
            (line.matched_debit_ids + line.matched_credit_ids).unlink()
    inv.button_draft()
    inv.button_cancel()
    print("   %s cancelada" % inv.name)
env.cr.commit()
print("   OK Facturas canceladas")

# 5. Borrar registros account_payment
print("\n[5] Eliminando registros de pago...")
all_payments = env['account.payment'].search([])
for p in all_payments:
    try:
        p.unlink()
    except Exception as ex:
        print("   WARN pago %d: %s" % (p.id, ex))
env.cr.commit()

# 6. Borrar moves cancelados/borrador
print("\n[6] Eliminando asientos cancelados/borrador...")
moves_to_delete = env['account.move'].search([('state', 'in', ['cancel', 'draft']), ('name', '!=', '/')])
print("   %d asientos a eliminar" % len(moves_to_delete))
for m in moves_to_delete:
    try:
        m.unlink()
        print("   Eliminado: %s" % m.name)
    except Exception as ex:
        print("   WARN %s: %s" % (m.name, ex))
env.cr.commit()

# Verificacion final
print("\n" + "="*60)
print("LIMPIEZA COMPLETA - FIN")
print("="*60)
remaining_moves = env['account.move'].search([('name', '!=', '/')])
remaining_payments = env['account.payment'].search([])
remaining_settlements = env['mx.tax.settlement'].search([])
print("Verificacion:")
print("  account_move restantes: %d" % len(remaining_moves))
print("  account_payment restantes: %d" % len(remaining_payments))
print("  mx.tax.settlement restantes: %d" % len(remaining_settlements))
