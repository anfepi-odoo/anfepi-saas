# Manual Técnico — MX Tax Liquidation

**Módulo:** `mx_tax_liquidation`  
**Versión:** 17.0.1.0.0  
**Plataforma:** Odoo 17 Enterprise  
**Autor:** ANFEPI: Roberto Requejo Jiménez | https://www.anfepi.com

---

## Índice

1. [Introducción técnica](#1-introducción-técnica)
2. [Estructura de archivos](#2-estructura-de-archivos)
3. [Modelo de datos](#3-modelo-de-datos)
4. [Flujo de estados](#4-flujo-de-estados)
5. [Lectura de saldos SQL](#5-lectura-de-saldos-sql)
6. [Generación del asiento contable](#6-generación-del-asiento-contable)
7. [Reclasificación atómica IVA retenido](#7-reclasificación-atómica-iva-retenido)
8. [Control de concurrencia](#8-control-de-concurrencia)
9. [Bitácora inmutable de auditoría](#9-bitácora-inmutable-de-auditoría)
10. [Seguridad y multicompañía](#10-seguridad-y-multicompañía)
11. [Wizards](#11-wizards)
12. [Reportes QWeb](#12-reportes-qweb)
13. [Tests](#13-tests)
14. [Parámetros de configuración](#14-parámetros-de-configuración)
15. [Extensión y personalización](#15-extensión-y-personalización)
16. [Consideraciones de rendimiento](#16-consideraciones-de-rendimiento)

---

## 1. Introducción técnica

`mx_tax_liquidation` implementa el patrón **liquidador de saldos contables**:
no recalcula impuestos ni recorre documentos fuente. Opera exclusivamente sobre
`account_move_line` para leer saldos y genera asientos `account.move` para cancelar pasivos.

### Dependencias

```python
'depends': ['account', 'account_accountant', 'mail', 'l10n_mx'],
```

### Namespace de modelos

Todos los modelos viven bajo el prefijo `mx.tax.*` para evitar colisiones con otros módulos:

| Modelo ORM | Tabla PostgreSQL |
|---|---|
| `mx.tax.concept` | `mx_tax_concept` |
| `mx.tax.settlement.config` | `mx_tax_settlement_config` |
| `mx.tax.settlement` | `mx_tax_settlement` |
| `mx.tax.settlement.line` | `mx_tax_settlement_line` |
| `mx.tax.settlement.payment` | `mx_tax_settlement_payment` |
| `mx.tax.settlement.payment.line` | `mx_tax_settlement_payment_line` |
| `mx.tax.settlement.log` | `mx_tax_settlement_log` |

---

## 2. Estructura de archivos

```
mx_tax_liquidation/
├── __init__.py
├── __manifest__.py
├── models/
│   ├── __init__.py
│   ├── mx_tax_concept.py               # Catálogo de conceptos
│   ├── mx_tax_settlement_config.py     # Config por empresa/concepto
│   ├── mx_tax_settlement.py            # Cabecera de liquidación
│   ├── mx_tax_settlement_line.py       # Líneas por concepto
│   ├── mx_tax_settlement_payment.py    # Eventos de pago + motor de asientos
│   ├── mx_tax_settlement_payment_line.py  # Distribución del pago
│   ├── mx_tax_settlement_log.py        # Bitácora inmutable
│   ├── account_move_line_ext.py        # Extensión account.move.line
│   └── res_config_settings.py          # Extensiones res.company / res.config.settings
├── wizards/
│   ├── __init__.py
│   ├── mx_tax_settlement_pay_wizard.py     # Asistente de pago
│   └── mx_tax_settlement_cancel_wizard.py  # Asistente de cancelación
├── security/
│   ├── security_groups.xml
│   ├── ir.model.access.csv
│   └── security_rules.xml
├── data/
│   ├── mx_tax_settlement_sequence.xml  # ir.sequence folio LIQS/
│   └── mx_tax_concept_data.xml         # 8 conceptos fiscales iniciales
├── views/
│   ├── mx_tax_concept_views.xml
│   ├── mx_tax_settlement_config_views.xml
│   ├── mx_tax_settlement_views.xml     # Vista principal
│   ├── mx_tax_settlement_log_views.xml
│   ├── mx_tax_settlement_pay_wizard_views.xml
│   ├── mx_tax_settlement_cancel_wizard_views.xml
│   ├── res_config_settings_views.xml
│   └── menus.xml
├── report/
│   ├── mx_tax_settlement_report.xml    # PDF liquidación
│   └── mx_tax_conciliation_report.xml  # PDF conciliación con semáforo
├── tests/
│   ├── __init__.py
│   ├── test_settlement_flow.py         # Flujo principal (13 casos)
│   ├── test_partial_payment.py         # Pagos parciales (5 casos)
│   ├── test_multicompany.py            # Multicompañía (7 casos)
│   └── test_reclassification.py        # Reclasificación IVA (7 casos)
└── static/
    └── description/
        ├── index.html
        ├── manual_usuario.md
        └── manual_tecnico.md
```

---

## 3. Modelo de datos

### `mx.tax.concept`

```python
code          = Char(required, unique via SQL constraint)
name          = Char(required)
tax_type      = Selection(['iva', 'isr', 'retencion'])
nature        = Selection(['liability', 'asset'])
requires_reclassification = Boolean(default=False)
active        = Boolean(default=True)
```

**Constraint SQL:** `UNIQUE(code)` implementado con `_sql_constraints`.

---

### `mx.tax.settlement.config`

```python
company_id                          = Many2one('res.company', required)
tax_concept_id                      = Many2one('mx.tax.concept', required)
liability_account_ids               = Many2many('account.account')   # pasivos
compensation_account_ids            = Many2many('account.account')   # acreditables
reclassification_source_account_id  = Many2one('account.account')    # fuente IVA-RET
```

**Constraint Python:** Si `tax_concept_id.requires_reclassification`, entonces
`reclassification_source_account_id` es obligatorio.

**Unicidad:** `_check_unique_config()` valida `UNIQUE(company_id, tax_concept_id)`.

---

### `mx.tax.settlement`

```python
name               = Char(readonly, sequence LIQS/)
company_id         = Many2one('res.company')
period_date        = Date(required)  # primer día del mes
calculation_date   = Date(required)  # fecha de corte SQL
journal_id         = Many2one('account.journal')
responsible_id     = Many2one('res.users')
state              = Selection(['draft','confirmed','partial','paid','cancel'])
line_ids           = One2many('mx.tax.settlement.line')
payment_ids        = One2many('mx.tax.settlement.payment')
log_ids            = One2many('mx.tax.settlement.log')
total_determined   = Float (compute, sum de amount_determined)
total_to_pay       = Float (compute, sum de amount_to_pay)
total_paid         = Float (compute, sum de amount_paid)
total_pending      = Float (compute, sum de amount_pending)
```

**Unicidad de período:** `_check_no_duplicate()` valida que no exista otra liquidación
activa (`state != 'cancel'`) para la misma `(company_id, period_date)`.

**Normalización de fecha:** `_onchange_period_date()` fuerza el día 1 del mes.

---

### `mx.tax.settlement.line`

```python
settlement_id          = Many2one('mx.tax.settlement', ondelete='cascade')
tax_concept_id         = Many2one('mx.tax.concept')
config_id              = Many2one('mx.tax.settlement.config')
balance_liability      = Float  # saldo crédito de cuentas pasivo
balance_compensation   = Float  # saldo crédito de cuentas acreditables
amount_determined      = Float (compute: max(liability - compensation, 0))
amount_to_pay          = Float (editable)
amount_paid            = Float (compute: sum de payment_line_ids.amount_applied)
amount_pending         = Float (compute: amount_to_pay - amount_paid)
difference_pct         = Float (compute: (amount_to_pay - amount_determined) / amount_determined * 100)
line_state             = Selection (compute: pending/partial/paid/deferred/zero)
payment_line_ids       = One2many('mx.tax.settlement.payment.line')
```

**Constraint Python:** `amount_to_pay >= 0`.

---

### `mx.tax.settlement.payment`

```python
settlement_id          = Many2one('mx.tax.settlement')
payment_date           = Date(required)
amount_total           = Float(required)
distribution_mode      = Selection(['auto', 'manual'])
bank_account_id        = Many2one('res.partner.bank')
bank_reference         = Char(required)
move_id                = Many2one('account.move', readonly)
state                  = Selection(['draft', 'posted', 'cancelled'])
distribution_line_ids  = One2many('mx.tax.settlement.payment.line')
is_balanced            = Boolean (compute)
```

**Método clave:** `action_generate_move()` — genera el asiento contable.

---

### `mx.tax.settlement.payment.line`

```python
payment_id             = Many2one('mx.tax.settlement.payment', ondelete='cascade')
settlement_line_id     = Many2one('mx.tax.settlement.line')
amount_pending_before  = Float (readonly)
amount_applied         = Float
```

**Constraint Python:** `amount_applied <= amount_pending_before`.

---

### `mx.tax.settlement.log`

```python
settlement_id   = Many2one('mx.tax.settlement')
action          = Selection([...])
timestamp       = Datetime (default=now)
user_id         = Many2one('res.users')
description     = Text
value_before    = Text (JSON)
value_after     = Text (JSON)
ip_address      = Char
payment_id      = Many2one('mx.tax.settlement.payment')
```

**Inmutabilidad:**

```python
def write(self, vals):
    raise AccessError(_('Los registros de auditoría no pueden modificarse.'))

def unlink(self):
    raise AccessError(_('Los registros de auditoría no pueden eliminarse.'))
```

---

### `account.move.line` (extensión)

```python
tax_settlement_line_id = Many2one('mx.tax.settlement.line',
                                   string='Línea de liquidación',
                                   ondelete='set null',
                                   index=True)
```

Permite trazabilidad inversa: desde cualquier línea de asiento hacia la liquidación.

---

## 4. Flujo de estados

```
draft ──→ confirmed ──→ partial ──→ paid
  │              │         │
  │              └────────┘
  └──→ cancel (desde cualquier estado con rol Gerente)
```

Transiciones:

| Método | Estado origen | Estado destino |
|---|---|---|
| `action_calculate_balances()` | draft | draft (recrea líneas) |
| `action_confirm()` | draft | confirmed |
| `_update_payment_state()` | confirmed / partial | partial / paid |
| `_do_cancel()` | cualquiera | cancel |

---

## 5. Lectura de saldos SQL

El método `_fetch_account_balances(account_ids, company_id, date_to)` en
`mx.tax.settlement` ejecuta:

```sql
SELECT
    aml.account_id,
    COALESCE(SUM(aml.credit) - SUM(aml.debit), 0) AS net_credit
FROM account_move_line aml
JOIN account_move am ON am.id = aml.move_id
WHERE
    am.state = 'posted'
    AND aml.company_id = %(company_id)s
    AND aml.account_id = ANY(%(account_ids)s)
    AND aml.date <= %(date_to)s
GROUP BY aml.account_id
```

**Resultado:** `dict {account_id: net_credit_balance}`.

La consulta usa parámetros posicionales (`%(key)s`) para prevenir inyección SQL.
Opera directamente sobre `self.env.cr` sin ORM para máximo rendimiento.

---

## 6. Generación del asiento contable

`mx.tax.settlement.payment.action_generate_move()`:

### Paso 1 — Bloqueo concurrente

```sql
SELECT id FROM mx_tax_settlement WHERE id = %s FOR UPDATE NOWAIT
```

Si el registro está bloqueado, lanza `UserError('Liquidación en uso por otro proceso')`.

### Paso 2 — Validaciones previas

- Período no cerrado (`account.period` si existe)
- `is_balanced == True`
- `amount_total > 0`

### Paso 3 — Construcción de líneas de asiento

**Para conceptos normales:**

Por cada cuenta de pasivo de la línea, se crea una línea DEBE proporcional al saldo
de esa cuenta. Una sola línea HABER a la cuenta de liquidez del banco.

Ajuste de redondeo: la primera línea DEBE absorbe el residuo de centavos para garantizar
que `sum(debits) == sum(credits)`.

**Para conceptos con `requires_reclassification = True`:**

```
DEBE: reclassification_source_account   amount_applied
HABER: bank_liquidity_account           amount_applied
```

Solo 2 líneas. Sin pasos intermedios.

### Paso 4 — Creación y publicación

```python
move = self.env['account.move'].create(move_vals)
move.action_post()
```

### Paso 5 — Vinculación de trazabilidad

```python
for line in move.line_ids:
    if line.account_id in liability_accounts:
        line.write({'tax_settlement_line_id': settlement_line.id})
```

### Paso 6 — Actualización de estado

Se llama `settlement._update_payment_state()` que computa si quedan pendientes
y ajusta `state` a `partial` o `paid`.

---

## 7. Reclasificación atómica IVA retenido

El diseño deliberadamente simplificado para IVA retenido evita la duplicación
de pasos contables:

```
❌ Patrón incorrecto (NO implementado):
   DEBE 2166 IVA-RET-COBRAR    → HABER 2162 IVA-RET-CLIENTES   (reclasificación)
   DEBE 2162 IVA-RET-CLIENTES  → HABER 1110 BANCOS              (liquidación)

✅ Patrón correcto (implementado):
   DEBE 2162 IVA-RET-CLIENTES  → HABER 1110 BANCOS              (un solo asiento atómico)
```

La cuenta `reclassification_source_account_id` en la config señala la cuenta origen
del IVA retenido. El asiento resultante tiene **exactamente 2 líneas**.

---

## 8. Control de concurrencia

Se usa `SELECT ... FOR UPDATE NOWAIT` tanto en `action_confirm()` como en
`action_generate_move()` para evitar procesamiento doble en entornos multiusuario.

```python
self._cr.execute(
    'SELECT id FROM mx_tax_settlement WHERE id = %s FOR UPDATE NOWAIT',
    (self.id,)
)
```

Si el registro está bloqueado (otro proceso lo tiene), PostgreSQL lanza
`psycopg2.errors.LockNotAvailable` que se captura y convierte en `UserError`.

---

## 9. Bitácora inmutable de auditoría

### Creación de entradas

Se crea mediante el método helper en `mx.tax.settlement`:

```python
def _log_action(self, action, description, value_before=None, value_after=None, payment_id=None):
    self.env['mx.tax.settlement.log'].sudo().create({
        'settlement_id': self.id,
        'action': action,
        'description': description,
        'user_id': self.env.uid,
        'timestamp': fields.Datetime.now(),
        'value_before': json.dumps(value_before) if value_before else False,
        'value_after': json.dumps(value_after) if value_after else False,
        'ip_address': self.env['ir.http']._get_request().httprequest.remote_addr
                      if hasattr(self.env['ir.http'], '_get_request') else False,
        'payment_id': payment_id,
    })
```

### Acciones registradas

`calculate`, `confirm`, `pay`, `cancel`, `edit_amount`, `defer`

---

## 10. Seguridad y multicompañía

### Grupos de seguridad

| Referencia XML | Nombre | Hereda de |
|---|---|---|
| `group_tax_settlement_user` | Liquidación Fiscal: Usuario | `account.group_account_invoice` |
| `group_tax_settlement_manager` | Liquidación Fiscal: Gerente | `group_tax_settlement_user` |
| `group_tax_settlement_auditor` | Liquidación Fiscal: Auditor | `base.group_user` |
| `group_tax_settlement_config` | Liquidación Fiscal: Configuración | `group_tax_settlement_manager` |

### Reglas de acceso por modelo

Las reglas `ir.model.access.csv` cubren todos los modelos. El Auditor tiene solo lectura.
El Gerente tiene crear/escribir/eliminar en los modelos principales.

### Reglas de registro (ir.rule)

```xml
<domain_force>[('company_id', 'in', company_ids)]</domain_force>
```

Se aplica a todos los modelos con `company_id`. Esto garantiza aislamiento total
entre empresas en entornos multicompañía.

---

## 11. Wizards

### `mx.tax.settlement.pay.wizard` (TransientModel)

**`default_get()`:** Precarga las líneas con `amount_pending` > 0 de la liquidación activa.

**`_apply_auto_distribution()`:** Calcula montos proporcionales. El último concepto absorbe
el residuo de redondeo para garantizar que `sum(amounts) == amount_total`.

**`action_confirm()`:**
1. Valida suma de líneas manuales == `amount_total`
2. Crea `mx.tax.settlement.payment` con `distribution_line_ids`
3. Llama `payment.action_generate_move()`

### `mx.tax.settlement.cancel.wizard` (TransientModel)

**`action_confirm()`:**
1. Valida motivo >= 20 caracteres
2. Llama `settlement._do_cancel(reason)`

**`_do_cancel()`** (en `mx.tax.settlement`):
1. Revierte cada `account.move` publicado (`move.button_cancel()` + reinversión)
2. Cambia `state = 'cancel'`
3. Registra en bitácora

---

## 12. Reportes QWeb

### `mx_tax_settlement_report`

- **ID:** `mx_tax_liquidation.action_report_settlement`
- **Template:** `mx_tax_liquidation.report_settlement_document`
- **Método Python:** `_get_report_values()` en el modelo

Secciones:
- Encabezado empresa y período
- Tabla de líneas con estado visual
- Tabla de pagos realizados
- Referencias a asientos generados
- Firma Preparó / Autorizó

### `mx_tax_conciliation_report`

- **ID:** `mx_tax_liquidation.action_report_conciliation`
- **Template:** `mx_tax_liquidation.report_conciliation_document`

Semáforo basado en `difference_pct`:

```xml
<t t-if="line.difference_pct == 0">✅</t>
<t t-elif="abs(line.difference_pct) &lt;= 2">✅</t>
<t t-elif="abs(line.difference_pct) &lt;= 5">⚠️</t>
<t t-elif="line.amount_determined == 0">⬜</t>
<t t-else="">🔴</t>
```

---

## 13. Tests

### Estructura

```
tests/
├── __init__.py                   # imports de los 4 módulos de test
├── test_settlement_flow.py       # 13 casos: flujo completo, validaciones
├── test_partial_payment.py       # 5 casos: pagos parciales
├── test_multicompany.py          # 7 casos: aislamiento multicompañía
└── test_reclassification.py      # 7 casos: asiento atómico IVA-RET
```

### Ejecución

```bash
# Todos los tests del módulo
python odoo-bin -d <db> --test-enable --test-tags mx_tax_liquidation

# Un archivo específico
python odoo-bin -d <db> --test-enable \
  --test-tags mx_tax_liquidation \
  -i mx_tax_liquidation
```

### Patrón usado: `@tagged` + `TransactionCase`

```python
@tagged('post_install', '-at_install', 'mx_tax_liquidation')
class TestSettlementFlow(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # crear cuentas, diarios, conceptos, configs, saldos semilla
```

Cada `setUpClass` crea sus propios registros con códigos únicos para evitar
colisiones entre clases de test.

---

## 14. Parámetros de configuración

Almacenados en `res.company` (extendido vía `res_config_settings.py`):

| Campo técnico | Tipo | Default | Descripción |
|---|---|---|---|
| `tax_settlement_journal_id` | Many2one | — | Diario de liquidaciones |
| `tax_settlement_diff_threshold` | Float | 5.0 | Umbral % diferencia aceptable |
| `tax_settlement_require_attachment` | Boolean | False | Exigir adjunto al confirmar |

Expuestos en `res.config.settings` con `related='company_id.tax_settlement_*'`.

---

## 15. Extensión y personalización

### Agregar un nuevo concepto fiscal

1. Crear registro en `mx.tax.concept` (o en XML de datos de otro módulo).
2. Asegurarse de que `requires_reclassification` sea correcto.
3. Ir a *Configuración → Configuración de Liquidación* y mapear las cuentas.

### Extender el modelo de liquidación desde otro módulo

```python
# En tu módulo personalizado
class MxTaxSettlementExtended(models.Model):
    _inherit = 'mx.tax.settlement'

    custom_field = fields.Char('Campo propio')

    def action_confirm(self):
        super().action_confirm()
        # lógica adicional
```

### Agregar una acción al log

```python
self.settlement_id._log_action(
    action='custom_action',
    description='Acción personalizada ejecutada',
    value_before={'campo': valor_antes},
    value_after={'campo': valor_despues},
)
```

Nota: el campo `action` en `mx.tax.settlement.log` es `Selection`. Para agregar
nuevas acciones, hereda el modelo y extiende el campo:

```python
action = fields.Selection(
    selection_add=[('custom_action', 'Acción Personalizada')],
    ondelete={'custom_action': 'set default'},
)
```

---

## 16. Consideraciones de rendimiento

### Lectura de saldos

La consulta SQL de `_fetch_account_balances()` es la operación más costosa.
Para empresas con grandes volúmenes, asegúrese de tener índices en:

```sql
-- Recomendado (Odoo los crea por default):
CREATE INDEX ON account_move_line (account_id, company_id, date)
    WHERE move_id IN (SELECT id FROM account_move WHERE state = 'posted');
```

### Generación de asientos

La creación del asiento (`account.move.create`) ejecuta triggers de Odoo.
Para liquidaciones con muchos conceptos (>20), el proceso puede tardar 2-5 segundos.
Se recomienda ejecutar desde la interfaz de usuario (no desde scripts masivos).

### Bitácora

La bitácora puede crecer rápidamente. Se recomienda una política de retención:
archivar entradas con más de 5 años mediante un job programado externo o acción planificada.

### Multicompañía masiva (>50 empresas)

Si se ejecuta `action_calculate_balances()` para muchas empresas simultáneamente,
asegurarse de que el servidor tenga suficiente memoria y que los workers de Odoo
tengan configurado `limit_memory_hard` apropiado.

---

*Manual Técnico — MX Tax Liquidation v17.0.1.0.0*  
*ANFEPI: Roberto Requejo Jiménez | https://www.anfepi.com*
