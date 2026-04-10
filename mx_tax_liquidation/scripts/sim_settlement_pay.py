# -*- coding: utf-8 -*-
"""
Paso 2 del ejercicio:
  - Crea liquidacion fiscal enero 2026 / IVA Retenido a Terceros
  - Calcula saldos
  - Confirma
  - Registra pago al SAT
  - Imprime TODOS los asientos generados con detalle de cuentas
"""
from datetime import date

env.cr.autocommit = False  # noqa

SEP = "=" * 65

# ── Referencias ──────────────────────────────────────────────────────────
company   = env['res.company'].browse(1)

# Diario de liquidaciones (CABA)
journal_liq = env['account.journal'].search([('code', '=', 'CABA')], limit=1)
# Diario de banco para pagar
journal_bank = env['account.journal'].search([('code', '=', 'BNK1')], limit=1)
# Cuenta bancaria SAT
bank_account = env['res.partner.bank'].browse(1)

print(SEP)
print("  EJERCICIO: Liquidacion IVA Retenido a Terceros — Enero 2026")
print(SEP)
print("  Empresa    : %s" % company.name)
print("  Diario liq : %s" % journal_liq.name)
print("  Banco SAT  : %s" % bank_account.acc_number)
print(SEP)

# ── PASO A: Crear liquidacion ─────────────────────────────────────────────
print("\n[A] Creando liquidacion fiscal...")

settlement = env['mx.tax.settlement'].create({
    'company_id'      : company.id,
    'journal_id'      : journal_liq.id,
    'period_date'     : date(2026, 1, 1),
    'calculation_date': date(2026, 1, 31),
})
print("  Liquidacion creada: %s (id=%d, state=%s)" % (settlement.name, settlement.id, settlement.state))

# ── PASO B: Calcular saldos ───────────────────────────────────────────────
print("\n[B] Calculando saldos...")
settlement.action_calculate_balances()
env.cr.commit()

print("  state: %s" % settlement.state)
print("\n  Lineas de liquidacion:")
print("  %-40s %12s %12s %12s %s" % ("Impuesto", "Liability", "Comp.", "A Pagar", "Estado"))
print("  " + "-"*80)
for line in settlement.line_ids:
    print("  %-40s %12.2f %12.2f %12.2f %s" % (
        (line.tax_concept_id.name if line.tax_concept_id else "?")[:40],
        line.balance_liability,
        line.balance_compensation,
        line.amount_to_pay,
        line.line_state,
    ))

total_to_pay = sum(l.amount_to_pay for l in settlement.line_ids)
print("\n  TOTAL A PAGAR: $%12.2f" % total_to_pay)
print("  (Excel esperado: $400.00)")

# ── PASO C: Confirmar liquidacion ─────────────────────────────────────────
print("\n[C] Confirmando liquidacion...")
settlement.action_confirm()
env.cr.commit()
print("  state: %s" % settlement.state)

# ── PASO D: Registrar pago al SAT ─────────────────────────────────────────
print("\n[D] Registrando pago al SAT...")

# Obtener las lineas pendientes de pago
pending_lines = settlement.line_ids.filtered(lambda l: l.line_state == 'pending')
print("  Lineas pendientes: %d" % len(pending_lines))
for pl in pending_lines:
    print("    - %s: $%.2f" % (pl.tax_concept_id.name if pl.tax_concept_id else "?", pl.amount_to_pay))

# Calcular total a aplicar
total_to_apply = sum(pl.amount_to_pay for pl in pending_lines)

# Crear el wizard de pago
wizard = env['mx.tax.settlement.pay.wizard'].create({
    'settlement_id'  : settlement.id,
    'bank_account_id': bank_account.id,
    'payment_date'   : date(2026, 2, 17),
    'bank_reference' : 'REF-10000-TEST',
    'amount_total'   : total_to_apply,
    'line_ids': [(0, 0, {
        'settlement_line_id': pl.id,
        'amount_applied'    : pl.amount_to_pay,
        'amount_pending'    : pl.amount_to_pay,
    }) for pl in pending_lines],
})
print("  Wizard creado (id=%d)" % wizard.id)

# Confirmar pago
wizard.action_confirm()
env.cr.commit()
print("  Pago confirmado!")

# ── PASO E: Verificar asiento generado ───────────────────────────────────
print("\n" + SEP)
print("  PASO E: ASIENTO GENERADO POR EL PAGO AL SAT")
print(SEP)

sat_payment = env['mx.tax.settlement.payment'].search([('settlement_id', '=', settlement.id)], limit=1)
if sat_payment and sat_payment.move_id:
    move = sat_payment.move_id
    print("  Asiento: %s  |  Diario: %s  |  Fecha: %s  |  state: %s" % (
        move.name, move.journal_id.code, move.date, move.state))
    print()
    print("  %-12s %-35s %12s %12s  %s" % ("Cuenta", "Nombre", "Debe", "Haber", "Etiqueta"))
    print("  " + "-"*90)
    for ml in move.line_ids:
        print("  %-12s %-35s %12.2f %12.2f  %s" % (
            ml.account_id.code,
            (ml.account_id.name if isinstance(ml.account_id.name, str) else ml.account_id.name.get('en_US', '?'))[:35],
            ml.debit,
            ml.credit,
            ml.name[:40] if ml.name else '',
        ))
    print()
    total_d = sum(ml.debit for ml in move.line_ids)
    total_h = sum(ml.credit for ml in move.line_ids)
    print("  %-12s %-35s %12.2f %12.2f" % ("", "TOTALES", total_d, total_h))
    print()
    print("  Cuadre: %s" % ("OK" if abs(total_d - total_h) < 0.01 else "ERROR: %.6f" % (total_d - total_h)))
    print()
    print("  ESPERADO (segun Excel):")
    print("    Dr. 216.10.20   400.00   <- IVA ret. pagado (SAT obligation)")
    print("    Cr. 102.01.01   400.00   <- Banco")
else:
    print("  ERROR: No se encontro asiento para el pago SAT")

# ── PASO F: Balance final de cuentas clave ───────────────────────────────
print("\n" + SEP)
print("  PASO F: BALANCE FINAL CUENTAS CLAVE")
print(SEP)

cuentas = ['216.10.10', '216.10.20', '102.01.01', '118.01.01', '601.84.01']
for code in cuentas:
    acc = env['account.account'].search([('code', '=', code), ('company_id', '=', 1)], limit=1)
    if not acc:
        continue
    lines = env['account.move.line'].search([
        ('account_id', '=', acc.id),
        ('move_id.state', '=', 'posted'),
    ])
    total_d = sum(l.debit for l in lines)
    total_h = sum(l.credit for l in lines)
    balance = total_d - total_h
    print("  %s  %-35s  Debe=%10.2f  Haber=%10.2f  Balance=%10.2f" % (
        code, acc.name[:35] if isinstance(acc.name, str) else acc.name.get('en_US', '')[:35],
        total_d, total_h, balance
    ))

print("\n" + SEP)
print("  EJERCICIO COMPLETO")
print(SEP)
