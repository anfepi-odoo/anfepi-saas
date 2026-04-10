# -*- coding: utf-8 -*-
"""
Script: setup_tax_config.py
Configura las cuentas contables y conceptos fiscales del módulo mx_tax_liquidation
en la empresa activa (company_id=1).

Ejecución:
  docker exec -it odoo17_enterprise \
    /opt/odoo/odoo-core/odoo-bin shell -d odoo17 -c /etc/odoo/odoo.conf \
    --no-http < /mnt/benotto-addons/mx_tax_liquidation/scripts/setup_tax_config.py
"""
import logging
_logger = logging.getLogger('mx_tax_config_setup')

env.cr.autocommit = False  # noqa: F821 — variable inyectada por odoo-bin shell

Company = env['res.company']  # noqa
Account = env['account.account']
Journal = env['account.journal']
Concept = env['mx.tax.concept']
Config  = env['mx.tax.settlement.config']

company = Company.browse(1)
print(f"\n{'='*60}")
print(f"Empresa: {company.name}  |  id={company.id}")
print('='*60)


# ─────────────────────────────────────────────────────────────
# 1.  CREAR CUENTAS FALTANTES EN EL CATÁLOGO
# ─────────────────────────────────────────────────────────────
def get_or_create_account(code, name_es, name_en, account_type, reconcile=False):
    """Retorna la cuenta existente o la crea si no existe."""
    acc = Account.search([('code', '=', code), ('company_id', '=', company.id)], limit=1)
    if acc:
        print(f"  [existe]   {code}  {name_es}")
        return acc
    acc = Account.create({
        'code': code,
        'name': name_es,         # Odoo 17 acepta string simple
        'account_type': account_type,
        'reconcile': reconcile,
        'company_id': company.id,
    })
    print(f"  [creada]   {code}  {name_es}  (id={acc.id})")
    return acc


print("\n[1] Verificando / creando cuentas necesarias...")

# ISR por pagar (impuesto propio de la empresa)
acc_isr_propio   = get_or_create_account(
    '213.01.01', 'ISR por Pagar (Pago Provisional)', 'ISR Payable (Provisional)',
    'liability_current', reconcile=True,
)
# ISR dividendos retenido
acc_ret_div      = get_or_create_account(
    '216.09.01', 'Retención ISR Dividendos',  'Withholding ISR Dividends',
    'liability_current', reconcile=False,
)
# ISR asimilados (comparte estructura con honorarios pero cuenta separada)
acc_ret_asim     = get_or_create_account(
    '216.05.01', 'Retención ISR Asimilados a Salarios', 'Withholding ISR Assimilated Wages',
    'liability_current', reconcile=False,
)

# Cuentas ya existentes en l10n_mx — sólo referenciamos
def get_account(code):
    acc = Account.search([('code', '=', code), ('company_id', '=', company.id)], limit=1)
    if not acc:
        raise ValueError(f'Cuenta {code} no encontrada en empresa {company.id}')
    return acc

acc_iva_tras_cob   = get_account('208.01.01')  # IVA trasladado cobrado
acc_iva_tras_nocob = get_account('209.01.01')  # IVA trasladado no cobrado
acc_iva_acred1     = get_account('118.01.01')  # IVA acreditable pagado 16%
acc_iva_acred2     = get_account('118.01.02')  # IVA acreditable pagado 8%
acc_iva_pend       = get_account('119.01.01')  # IVA pendiente de pago (acreditable base flujo)
acc_iva_ret_pend   = get_account('216.10.10')  # IVA retenido pendiente (obligación real vs SAT)
acc_iva_ret_pag    = get_account('216.10.20')  # IVA retenido efectivamente pagado (tracking)
acc_ret_sal        = get_account('216.01.01')  # Ret. ISR sueldos y salarios
acc_ret_hon        = get_account('216.04.01')  # Ret. ISR honorarios/serv.prof
acc_ret_arr        = get_account('216.03.01')  # Ret. ISR arrendamiento
acc_isr_ret_col    = get_account('113.02.01')  # ISR Retenido (activo: favor empresa)

# IVA retenido A FAVOR (lo que los clientes retuvieron a la empresa = crédito)
acc_iva_ret_fav = get_or_create_account(
    '113.01.01', 'IVA Retenido a Favor de la Empresa',
    'IVA Withheld in Favor of the Company',
    'asset_current', reconcile=True,
)

# IVA Acreditable Pendiente de Retención (LIVA Art. 5)
# El 4% retenido al proveedor no es acreditable hasta pagar al SAT.
# Al registrar pago SAT se traslada: 118.01.03 → 118.01.01
acc_iva_ret_pendiente = get_or_create_account(
    '118.01.03', 'IVA Acreditable Pendiente (Retención)',
    'IVA Creditable Pending (Withholding)',
    'asset_current', reconcile=False,
)

print("  [ok] Todas las cuentas de referencia localizadas.")


# ─────────────────────────────────────────────────────────────
# 2.  IDENTIFICAR EL DIARIO DE LIQUIDACIONES
# ─────────────────────────────────────────────────────────────
print("\n[2] Identificando diario de liquidaciones...")

journal_liq = Journal.search([
    ('code', '=', 'CABA'), ('company_id', '=', company.id),
], limit=1)

if not journal_liq:
    # Fallback: buscar cualquier diario general
    journal_liq = Journal.search([
        ('type', '=', 'general'), ('company_id', '=', company.id),
    ], limit=1)

print(f"  Diario: {journal_liq.name}  código={journal_liq.code}  id={journal_liq.id}")


# ─────────────────────────────────────────────────────────────
# 3.  MAPA DE CONFIGURACIÓN POR CONCEPTO FISCAL
# ─────────────────────────────────────────────────────────────
# Estructura:
#   code: código del concepto
#   liability_accounts: cuentas de pasivo a liquidar
#   compensation_accounts: cuentas de compensación (puede ser vacío)
#   reclass_source: cuenta origen para reclasificación (IVA_RET)
#   threshold_pct: umbral de diferencia aceptable (%)

CONFIG_MAP = [
    {
        'code': 'ISR_PROPIO',
        'liability_accounts': [acc_isr_propio],
        'compensation_accounts': [acc_isr_ret_col],  # ISR retenido (saldo favor)
        'reclass_source': None,
        'threshold_pct': 5.0,
    },
    {
        'code': 'IVA_PAGAR',
        'liability_accounts': [acc_iva_tras_cob, acc_iva_tras_nocob],
        'compensation_accounts': [acc_iva_acred1, acc_iva_acred2],
        'reclass_source': None,
        'threshold_pct': 2.0,
    },
    {
        'code': 'IVA_RET',
        # DESPUÉS de pagar al proveedor, Odoo reclasifica automáticamente:
        #   Dr. 216.10.10 (pendiente)  →  Cr. 216.10.20 (efectivamente pagado)
        # La OBLIGACIÓN REAL ante el SAT vive en 216.10.20 (crédito acreedor)
        'liability_accounts': [acc_iva_ret_pag],   # 216.10.20 = saldo a enterar al SAT
        'compensation_accounts': [acc_iva_ret_fav],  # 113.01.01 = IVA ret. a favor
        # Cuenta origen (antes del cash-basis): requerido porque requires_reclassification=True
        'reclass_source': acc_iva_ret_pend,          # 216.10.10 = origen antes del pago
        # LIVA Art. 5: Al pagar retención al SAT liberar IVA acreditable pendiente
        'iva_pending_account': acc_iva_ret_pendiente,   # 118.01.03 pendiente
        'iva_acreditable_account': acc_iva_acred1,      # 118.01.01 definitivo
        'threshold_pct': 1.0,
    },
    {
        'code': 'RET_SAL',
        'liability_accounts': [acc_ret_sal],
        'compensation_accounts': [],
        'reclass_source': None,
        'threshold_pct': 1.0,
    },
    {
        'code': 'RET_ASIM',
        'liability_accounts': [acc_ret_asim],
        'compensation_accounts': [],
        'reclass_source': None,
        'threshold_pct': 1.0,
    },
    {
        'code': 'RET_HON',
        'liability_accounts': [acc_ret_hon],
        'compensation_accounts': [],
        'reclass_source': None,
        'threshold_pct': 1.0,
    },
    {
        'code': 'RET_ARR',
        'liability_accounts': [acc_ret_arr],
        'compensation_accounts': [],
        'reclass_source': None,
        'threshold_pct': 1.0,
    },
    {
        'code': 'RET_DIV',
        'liability_accounts': [acc_ret_div],
        'compensation_accounts': [],
        'reclass_source': None,
        'threshold_pct': 1.0,
    },
]


# ─────────────────────────────────────────────────────────────
# 4.  CREAR / ACTUALIZAR REGISTROS DE CONFIGURACIÓN
# ─────────────────────────────────────────────────────────────
print("\n[3] Creando / actualizando configuraciones de conceptos fiscales...\n")

created = 0
updated = 0
errors  = 0

for cfg in CONFIG_MAP:
    concept = Concept.search([('code', '=', cfg['code'])], limit=1)
    if not concept:
        print(f"  [ERROR] Concepto '{cfg['code']}' no encontrado — omitiendo.")
        errors += 1
        continue

    existing = Config.search([
        ('company_id', '=', company.id),
        ('tax_concept_id', '=', concept.id),
    ], limit=1)

    vals = {
        'company_id': company.id,
        'tax_concept_id': concept.id,
        'liability_account_ids': [(6, 0, [a.id for a in cfg['liability_accounts']])],
        'compensation_account_ids': [(6, 0, [a.id for a in cfg['compensation_accounts']])],
        'settlement_journal_id': journal_liq.id,
        'difference_threshold_pct': cfg['threshold_pct'],
        'require_attachment': True,
    }
    if cfg['reclass_source']:
        vals['reclassification_source_account_id'] = cfg['reclass_source'].id
    else:
        vals['reclassification_source_account_id'] = False  # limpiar si era None
    # LIVA Art. 5: cuentas de liberación IVA acreditable pendiente
    iva_pend = cfg.get('iva_pending_account')
    iva_acred = cfg.get('iva_acreditable_account')
    vals['iva_pending_account_id'] = iva_pend.id if iva_pend else False
    vals['iva_acreditable_account_id'] = iva_acred.id if iva_acred else False

    if existing:
        existing.write(vals)
        print(f"  [actualizado] {cfg['code']:<12}  →  {concept.name}")
        updated += 1
    else:
        Config.create(vals)
        print(f"  [creado]      {cfg['code']:<12}  →  {concept.name}")
        created += 1

print(f"\n  Resumen: {created} creados, {updated} actualizados, {errors} errores.")


# ─────────────────────────────────────────────────────────────
# 5.  COMMIT
# ─────────────────────────────────────────────────────────────
env.cr.commit()
print("\n[✓] Commit ejecutado. Configuración guardada exitosamente.")


# ─────────────────────────────────────────────────────────────
# 6.  VALIDACIÓN FINAL
# ─────────────────────────────────────────────────────────────
print("\n[4] Validación final de la configuración cargada:\n")
print(f"  {'Concepto':<12}  {'Tipo':<10}  {'Pasivos':<2}  {'Compensación':<2}  {'Reclasif.':<5}  {'Umbral'}")
print(f"  {'-'*12}  {'-'*10}  {'-'*7}  {'-'*12}  {'-'*9}  {'-'*6}")

for c in Config.search([('company_id', '=', company.id)], order='tax_concept_id'):
    code  = c.tax_concept_id.code
    ttype = c.tax_type or ''
    n_lib = len(c.liability_account_ids)
    n_cmp = len(c.compensation_account_ids)
    rcls  = '✓' if c.reclassification_source_account_id else '-'
    pct   = f"{c.difference_threshold_pct:.1f}%"
    print(f"  {code:<12}  {ttype:<10}  {n_lib} ctas    {n_cmp} ctas        {rcls:<9}  {pct}")

print(f"\n{'='*60}")
print("  CONFIGURACIÓN COMPLETADA")
print('='*60)
