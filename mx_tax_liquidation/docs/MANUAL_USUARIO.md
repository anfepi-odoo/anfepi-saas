# Manual de Usuario — Módulo Liquidación de Obligaciones Fiscales
### `mx_tax_liquidation` · Odoo 17 Enterprise · México

---

## Tabla de Contenido

1. [Introducción y Marco Legal](#1-introducción-y-marco-legal)
2. [Catálogo de Cuentas Requeridas](#2-catálogo-de-cuentas-requeridas)
3. [Configuración de Impuestos en Odoo](#3-configuración-de-impuestos-en-odoo)
4. [Configuración de Productos](#4-configuración-de-productos)
5. [Configuración del Módulo](#5-configuración-del-módulo)
6. [Flujo Contable Completo (Teoría)](#6-flujo-contable-completo-teoría)
7. [Pantalla: Liquidación de Obligaciones Fiscales](#7-pantalla-liquidación-de-obligaciones-fiscales)
8. [Pantalla: Wizard de Pago al SAT](#8-pantalla-wizard-de-pago-al-sat)
9. [Casos de Uso por Tipo de Retención](#9-casos-de-uso-por-tipo-de-retención)
10. [Conciliación Bancaria](#10-conciliación-bancaria)
11. [Preguntas Frecuentes](#11-preguntas-frecuentes)

---

## 1. Introducción y Marco Legal

### ¿Qué hace este módulo?

El módulo **mx_tax_liquidation** automatiza el proceso mensual de **determinación y pago de obligaciones fiscales al SAT**, generando los asientos contables correctos conforme a la legislación mexicana.

Gestiona los siguientes conceptos fiscales:

| Código | Concepto | Base Legal |
|--------|----------|-----------|
| `IVA_PAGAR` | IVA Trasladado Neto (cobros − acreditables) | LIVA Art. 1, 5 |
| `IVA_RET` | IVA Retenido a Terceros (Fletes, Honorarios, Arrendamiento) | LIVA Art. 1-A |
| `ISR_PROPIO` | ISR Pago Provisional Propio de la Empresa | LISR Art. 14 |
| `RET_SAL` | Retención ISR Sueldos y Salarios | LISR Art. 96 |
| `RET_ASIM` | Retención ISR Asimilados a Salarios | LISR Art. 94 |
| `RET_HON` | Retención ISR Honorarios / RESICO | LISR Art. 106 |
| `RET_ARR` | Retención ISR Arrendamiento | LISR Art. 116 |
| `RET_DIV` | Retención ISR Dividendos | LISR Art. 140 |

---

### La Regla Clave: LIVA Artículo 5, Fracción IV y Artículo 1-A

Esta es la regla que hace necesaria la lógica especial del módulo para operaciones con **retención de IVA**:

> *"El impuesto que le hubieran retenido al contribuyente únicamente podrá ser acreditado en el período en el que se efectúe el entero de dicha retención al fisco."*

**Traducción práctica** — En una factura de Flete de $10,000:

```
IVA total al 16%  = $1,600
Empresa retiene   = $400  (4% del valor del servicio — lo paga la empresa al SAT)
Proveedor cobra   = $1,200 de IVA  (12% del valor — él lo paga al SAT)

¿Qué IVA puedo acreditar YA?      → $1,200 (el que pagó el proveedor)
¿Qué IVA puedo acreditar DESPUÉS? → $400   (cuando yo pague al SAT la retención)
```

Esta misma lógica aplica a:
- **Fletes** — retención del 4% de IVA
- **Honorarios de persona física** — retención del 10.67% de IVA (2/3 partes de 16%)
- **Arrendamiento de persona física** — retención del 10.67% de IVA (2/3 partes de 16%)

---

## 2. Catálogo de Cuentas Requeridas

Antes de usar el módulo, deben existir las siguientes cuentas en el catálogo. El sistema las crea automáticamente al ejecutar `setup_tax_config.py`, pero es importante entender su función.

### 2.1 Cuentas de IVA Acreditable (Activo Circulante)

| Cuenta | Nombre | Cuándo se usa |
|--------|--------|--------------|
| `118.01.01` | IVA Acreditable Pagado 16% | IVA que puedes acreditar inmediatamente al pagar a tu proveedor |
| `118.01.02` | IVA Acreditable Pagado 8% | IVA tasa frontera (zona norte del país) |
| **`118.01.03`** | **IVA Acreditable Pendiente (Retención)** | IVA retenido que NO puedes acreditar hasta pagar al SAT — **creada por el módulo** |
| `119.01.01` | IVA Pendiente de Pago (Acreditable) | Cuenta de tránsito cash-basis del IVA de compras |

> **📌 Importante:** La cuenta `118.01.03` es nueva y creada por este módulo. Es el corazón de la lógica LIVA Art. 5.

### 2.2 Cuentas de IVA a Cargo del SAT (Pasivo Circulante)

| Cuenta | Nombre | Cuándo se usa |
|--------|--------|--------------|
| `208.01.01` | IVA Trasladado Cobrado | IVA de ventas ya cobradas (cash basis) |
| `209.01.01` | IVA Trasladado No Cobrado | IVA de ventas pendientes de cobro |
| `216.10.10` | IVA Retenido Pendiente (Tránsito) | Al recibir la factura del proveedor con retención — cuenta puente |
| `216.10.20` | IVA Retenido Efectivamente Pagado | Después de pagar al proveedor — representa la obligación real ante el SAT |

### 2.3 Cuentas de Retenciones ISR (Pasivo Circulante)

| Cuenta | Nombre |
|--------|--------|
| `213.01.01` | ISR por Pagar (Pago Provisional) |
| `216.01.01` | Retención ISR Sueldos y Salarios |
| `216.03.01` | Retención ISR Arrendamiento |
| `216.04.01` | Retención ISR Honorarios / Servicios Profesionales |
| `216.05.01` | Retención ISR Asimilados a Salarios |
| `216.09.01` | Retención ISR Dividendos |

### 2.4 Otras Cuentas

| Cuenta | Nombre | Tipo |
|--------|--------|------|
| `113.01.01` | IVA Retenido a Favor de la Empresa | Activo — cuando **clientes** retienen IVA a la empresa |
| `113.02.01` | ISR Retenido a Favor de la Empresa | Activo — cuando clientes retienen ISR |
| `102.01.01` | Banco | Activo — cuenta bancaria principal |

---

## 3. Configuración de Impuestos en Odoo

### 3.1 Impuesto para Fletes (IVA 16% con Retención 4%)

Este impuesto debe configurarse en **Contabilidad → Configuración → Impuestos**.

**Datos generales:**
| Campo | Valor |
|-------|-------|
| Nombre | `16% RET` |
| Tipo de impuesto | Compras |
| Cálculo | Porcentaje del precio |
| Importe | 16.00% |
| Exigibilidad fiscal | **Basado en pagos** *(obligatorio para LIVA Art. 5)* |

**Pestaña "Opciones Avanzadas":**
| Campo | Valor |
|-------|-------|
| Exigibilidad fiscal | `Basado en pagos` |
| Cuenta de transición cash-basis | `119.01.01` IVA pendiente de pago |

**Pestaña "Definición" — Distribución de Facturas:**

```
┌─────────────────────────────────────────────────────────────────┐
│  %      Con base en    Cuenta                  Tabla impuestos  │
├─────────────────────────────────────────────────────────────────┤
│  100    Base           (sin cuenta)            +DIOT: 16%       │
│   75    De impuesto    118.01.01 IVA acred.    +DIOT: 16% TAX   │
│   25    De impuesto    118.01.03 IVA pendiente                  │
└─────────────────────────────────────────────────────────────────┘
```

> **¿Por qué 75% y 25%?**
> El IVA total es 16%. La empresa **retiene** 4% (= 25% del impuesto).
> Por LIVA Art. 5, ese 25% no es acreditable hasta pagar al SAT.
> El 75% restante (12% del valor) sí es acreditable cuando pagas a tu proveedor.

**Distribución para Reembolsos** — misma estructura con cuentas de nota de crédito.

---

### 3.2 Impuesto para Honorarios de Persona Física (IVA 16% con Retención 2/3)

Para honorarios y arrendamiento de personas físicas, la retención es **10.67%** (= 2/3 del IVA de 16%):

```
┌─────────────────────────────────────────────────────────────────┐
│  %       Con base en    Cuenta                  Tabla           │
├─────────────────────────────────────────────────────────────────┤
│  100     Base           (sin cuenta)            +DIOT: 16%      │
│   33.33  De impuesto    118.01.01 IVA acred.    +DIOT: 16% TAX  │
│   66.67  De impuesto    118.01.03 IVA pendiente                 │
└─────────────────────────────────────────────────────────────────┘
```

> **¿Por qué 33.33% y 66.67%?**
> En honorarios y arrendamiento la empresa retiene **2/3 partes** del IVA.
> Solo 1/3 es acreditable de inmediato.

**Impuesto de retención ISR** — adicionalmente se requiere un impuesto separado para la retención de ISR (10% sobre honorarios, 10% sobre arrendamiento). Ese impuesto va a `216.04.01` / `216.03.01` directamente.

---

### 3.3 Impuesto de Retención de IVA (4% WH — solo retención)

Este es el impuesto que genera la **obligación** ante el SAT en la cuenta de tránsito:

| Campo | Valor |
|-------|-------|
| Nombre | `4% WH` |
| Tipo | Compras (negativo — retención) |
| Exigibilidad | `Basado en pagos` |
| Cuenta de transición | `216.10.10` |
| Cuenta de repartición | `216.10.20` |

---

## 4. Configuración de Productos

En **Inventario / Contabilidad → Productos**, pestaña **Compras**:

### Producto: Flete

```
┌─────────────────────────────────────────────────────────┐
│ Producto: [F] Flete                                     │
│ ─────────────────────────────────────────────────────── │
│ Facturas de Proveedores                                 │
│  Impuestos de proveedor:  [ 4% WH  ×  ]  [ 16% RET  × ]│
└─────────────────────────────────────────────────────────┘
```

> **Ambos impuestos son necesarios:**
> - `4% WH` → genera la obligación pasivo `216.10.10` → `216.10.20`
> - `16% RET` → divide el IVA 75%/25% entre `118.01.01` y `118.01.03`

### Producto: Honorarios / Servicios Profesionales

```
Impuestos de proveedor:  [ ISR 10% WH ]  [ IVA 16% c/Ret 2/3 ]
```

### Producto: Arrendamiento Persona Física

```
Impuestos de proveedor:  [ ISR 10% Arr ]  [ IVA 16% c/Ret 2/3 ]
```

---

## 5. Configuración del Módulo

Menú: **Liquidación Fiscal → Configuración → Configuración de Liquidaciones Fiscales**

Esta pantalla define las cuentas que el módulo usará al generar los asientos de pago al SAT.

### Columnas de la lista

| Columna | Descripción |
|---------|-------------|
| Concepto Fiscal | El concepto (ISR_PROPIO, IVA_PAGAR, IVA_RET, etc.) |
| Tipo de Impuesto | IVA / ISR / Retención |
| Cuentas de Pasivo a Liquidar | Cuentas cuyo saldo representa la deuda con el SAT |
| Cuentas de Compensación | Créditos que reducen la obligación (IVA acreditable) |
| Umbral % | Diferencia máxima aceptable sin justificación escrita |
| Requerir Acuse SAT Adjunto | ✅ activo = no se puede cerrar sin adjuntar el acuse |

### Campos del formulario — Configuración IVA Retenido a Terceros (IVA_RET)

```
┌─────────────────────────────────────────────────────────────────┐
│ Concepto Fiscal: IVA Retenido a Terceros                        │
│ ─────────────────────────────────────────────────────────────── │
│ CUENTAS DE PASIVO A LIQUIDAR                                    │
│   216.10.20  Impuestos retenidos de IVA efectivamente pagados   │
│                                                                 │
│ CUENTAS DE COMPENSACIÓN                                         │
│   113.01.01  IVA Retenido a Favor de la Empresa                 │
│                                                                 │
│ RECLASIFICACIÓN IVA RETENIDO                                    │
│   Cuenta IVA Retenido (No Pagado): 216.10.10                    │
│   IVA Acreditable Pendiente [118.01.03]: 118.01.03 ◄ nuevo     │
│   IVA Acreditable Definitivo [118.01.01]: 118.01.01 ◄ nuevo    │
└─────────────────────────────────────────────────────────────────┘
```

> **¿Para qué sirven los dos campos nuevos?**
> Al registrar el pago de la retención al SAT, el módulo automáticamente
> libera el IVA acreditable pendiente: mueve el saldo de `118.01.03` a `118.01.01`.

---

## 6. Flujo Contable Completo (Teoría)

### Caso: Factura de Flete $10,000 + IVA 16% (con Retención 4%)

#### Paso 1 — Recepción de Factura del Proveedor

Al confirmar la factura en Odoo se genera el asiento FACTU:

```
FACTU / 2026-01-01
─────────────────────────────────────────────────────────
Dr. 601.84.01  Gasto Flete               10,000.00
Cr. 216.10.10  IVA Ret. Pendiente (trán.)   400.00   ← 4% WH en tránsito
Cr. 119.01.01  IVA Pendiente Cash-Basis   1,600.00   ← 16% RET en tránsito
Cr. 201.01.01  Proveedores               11,200.00   ← pagas 10,000 + 1,200 IVA
─────────────────────────────────────────────────────────
```

*Nota: el proveedor no cobra los $400 de retención — tú los pagas directamente al SAT.*

#### Paso 2 — Pago al Proveedor ($11,200)

Odoo genera automáticamente el asiento cash-basis (CBMX / PBNK):

```
CBMX / 2026-01-20  (al momento del pago)
─────────────────────────────────────────────────────────
Dr. 119.01.01  IVA Pendiente Cash-Basis   1,600.00   ← se despeja
Cr. 118.01.01  IVA Acreditable (12%)      1,200.00   ← puedes acreditar YA
Cr. 118.01.03  IVA Acred. Pendiente (4%)    400.00   ← pendiente hasta pagar SAT

Dr. 216.10.10  IVA Ret. Pendiente           400.00   ← se reclasifica
Cr. 216.10.20  IVA Ret. Efectiv. Pagado     400.00   ← obligación real vs SAT

Dr. 201.01.01  Proveedor                 11,200.00
Cr. 102.01.01  Banco                     11,200.00
─────────────────────────────────────────────────────────
```

**Saldos después de pagar al proveedor:**
- `118.01.01` = $1,200 (IVA acreditable disponible)
- `118.01.03` = $400 (IVA pendiente — bloqueado hasta pagar SAT)
- `216.10.20` = -$400 (deuda con el SAT, saldo acreedor)
- Banco = -$11,200

#### Paso 3 — Liquidación de Obligaciones (módulo)

Creas la liquidación mensual, calculas, confirmas y registras el pago al SAT:

```
MISCE / 2026-02-17  (Asiento de Pago al SAT — generado por el módulo)
─────────────────────────────────────────────────────────────────────
Dr. 216.10.20  IVA Ret. Efectiv. Pagado    400.00   ← cancela deuda SAT
Dr. 118.01.01  IVA Acreditable             400.00   ← liberas el IVA pendiente
Cr. 118.01.03  IVA Acred. Pendiente (Ret.) 400.00   ← se agota
Cr. 102.09.01  Pagos Emitidos en Tránsito  400.00   ← cuenta para conciliar
─────────────────────────────────────────────────────────────────────
```

**Saldos finales después de pagar al SAT:**
- `118.01.01` = $1,600 (IVA acreditable total — los $1,200 + $400 liberados)
- `118.01.03` = $0 ✅
- `216.10.20` = $0 ✅
- Cuenta de tránsito banco = -$400 (reconcila contra extracto)

---

### Caso: Honorarios Persona Física $10,000

```
FACTU (recepción):
  Dr. Gasto Honorarios     10,000.00
  Cr. 119.01.01            1,600.00   ← IVA 16% cash-basis tránsito
  Cr. 216.04.01            1,000.00   ← ISR 10% retenido
  Cr. Proveedor            8,400.00   ← paga solo $8,400 (ojo: sin IVA en efectivo)

CBMX (al pagar $8,400):
  Dr. 119.01.01            1,600.00
  Cr. 118.01.01              533.33   ← IVA acreditable (1/3 del IVA = ~5.33%)
  Cr. 118.01.03            1,066.67   ← IVA pendiente (2/3 del IVA = ~10.67%)

SAT (pago retenciones ISR + IVA):
  Dr. 216.04.01            1,000.00   ← ISR honorarios
  Dr. 118.01.01            1,066.67   ← libera IVA pendiente
  Cr. 118.01.03            1,066.67   ← se agota
  Cr. Pagos Emitidos       1,000.00   ← banco
```

---

### Caso: Arrendamiento Persona Física $10,000

Idéntico a Honorarios, con diferencias:
- ISR → 10% a cuenta `216.03.01`
- Concepto SAT → `RET_ARR`

---

## 7. Pantalla: Liquidación de Obligaciones Fiscales

Menú: **Liquidación Fiscal → Liquidaciones de Obligaciones Fiscales**

### 7.1 Barra de Estado

```
[ Borrador ] → [ Confirmada ] → [ Pago Parcial ] → [ Pagada ]
```

| Estado | Significado | Acciones disponibles |
|--------|-------------|---------------------|
| **Borrador** | En edición, aún no comprometida | Calcular Saldos, Confirmar |
| **Confirmada** | Saldos congelados, comprometida | Registrar Pago al SAT, Cancelar |
| **Pago Parcial** | Al menos un concepto pagado, otros pendientes | Registrar Pago al SAT |
| **Pagada** | Todos los conceptos con obligación = pagados | Imprimir, Cancelar |
| **Cancelada** | Anulada con motivo | — |

### 7.2 Bloque "Identificación"

| Campo | Descripción | Editable |
|-------|-------------|----------|
| **Folio** | Número de serie automático (LIQS/...) | No |
| **Empresa** | Empresa que presenta la declaración | Solo en Borrador |
| **Período Fiscal** | Primer día del mes (ej: 01/01/2026 = Enero 2026) | Solo en Borrador |
| **Período** | Texto calculado: "Enero 2026" | No |
| **Fecha de Corte** | Hasta qué fecha leer saldos (usualmente último día del mes) | Solo en Borrador |

### 7.3 Bloque "Control"

| Campo | Descripción | Editable |
|-------|-------------|----------|
| **Contador Responsable** | Usuario que genera la liquidación | Solo en Borrador |
| **Diario de Liquidación** | Diario contable (tipo Misceláneos/General) donde se contabilizarán los asientos | Solo en Borrador |
| **Referencia SAT** | Línea de captura o folio de la declaración SAT | Siempre |
| **Fecha de Confirmación** | Se llena automáticamente al confirmar | No |
| **Confirmado por** | Usuario que confirmó | No |

> **💡 Tip:** La Referencia SAT se pre-rellena automáticamente en el Wizard de Pago al SAT, evitando capturarla dos veces.

### 7.4 Pestaña "Conceptos Fiscales" — Tabla de Líneas

Esta es la tabla principal donde se ve la situación de cada impuesto:

```
┌────────────────┬──────────┬─────────────┬────────────┬─────────┬─────────┬──────────┬───────┬──────────────┐
│ Concepto       │Saldo Pas.│ Compensación│ Determinado│ A Pagar │  Pagado │ Pendiente│ Dif % │ Estado       │
├────────────────┼──────────┼─────────────┼────────────┼─────────┼─────────┼──────────┼───────┼──────────────┤
│ IVA por Pagar  │  $0.00   │ -$1,200.00  │ -$1,200.00 │  $0.00  │  $0.00  │   $0.00  │  0.00 │ Saldo a Favor│
│ IVA Ret. 3ros  │ $400.00  │    $0.00    │   $400.00  │ $400.00 │ $400.00 │   $0.00  │  0.00 │ Pagado ✅    │
│ Ret ISR Sueld. │  $0.00   │    $0.00    │    $0.00   │  $0.00  │  $0.00  │   $0.00  │  0.00 │ Sin Oblig.   │
└────────────────┴──────────┴─────────────┴────────────┴─────────┴─────────┴──────────┴───────┴──────────────┘
```

**Descripción de cada columna:**

| Columna | Cómo se calcula | Qué significa |
|---------|----------------|---------------|
| **Saldo Pasivo** | Suma de saldos acreedores de las cuentas de pasivo configuradas (ej: 216.10.20) | Lo que debes al SAT |
| **Compensación** | Suma de saldos de cuentas de compensación (ej: 113.01.01) | Créditos que reducen la deuda |
| **Determinado** | Pasivo − Compensación | Monto neto a pagar (puede ser negativo = a favor) |
| **A Pagar** | Campo editable — ingresa el monto que declararás | Lo que realmente pagarás este período |
| **Pagado** | Suma de pagos ya registrados y contabilizados | Pagos al SAT ya realizados |
| **Pendiente** | A Pagar − Pagado | Saldo sin pagar |
| **Dif %** | (Determinado − A Pagar) / Determinado × 100 | Variación respecto al calculado |
| **Estado** | Calculado automáticamente | Ver tabla de estados abajo |
| **Diferida** | Checkbox manual | Marca el concepto como "no aplica este período" |
| **Justificación** | Texto libre | Obligatorio si Dif % supera el umbral configurado |

**Estados de cada línea:**

| Estado | Color | Condición |
|--------|-------|-----------|
| Sin Obligación | Gris | Determinado = 0 y A Pagar = 0 |
| **Saldo a Favor** | **Azul** | Determinado < 0 (compensación > pasivo) |
| Pendiente | Negro | A Pagar > 0, sin pagos aún |
| Pago Parcial | Naranja | Hay pagos pero Pendiente > 0 |
| **Pagado** | **Verde** | Pendiente = 0 y A Pagar > 0 |
| Diferida | Gris | Checkbox "Diferida" marcado |

> **⚠️ Fila en rojo:** Aparece cuando la diferencia entre Determinado y A Pagar supera el umbral configurado (por defecto 5%) **y no hay justificación escrita**. Debes escribir en la columna "Justificación" para poder confirmar.

### 7.5 Panel de Totales

```
Total Determinado:  $400.00
Total a Pagar:      $400.00
Total Pagado:       $400.00
Pendiente:           $0.00
```

### 7.6 Pestaña "Pagos al SAT"

Lista todos los eventos de pago registrados para esta liquidación:

| Campo | Descripción |
|-------|-------------|
| Fecha de Pago | Fecha del pago al SAT |
| Monto Total | Monto total del evento de pago |
| Modo de Distribución | Automático o Manual |
| Cuenta Bancaria | Cuenta desde la que se pagó |
| Referencia Bancaria | Número de operación / folio bancario |
| Asiento | Link al asiento contable generado |
| Estado | Borrador / Registrado / Revertido |

### 7.7 Pestaña "Auditoría"

*(Solo visible para rol Gerente de Liquidaciones)*

Bitácora inmutable de todos los eventos: cálculos, confirmaciones, pagos, cancelaciones. Incluye fecha/hora, usuario, dirección IP.

### 7.8 Botones de Acción

| Botón | Cuándo aparece | Qué hace |
|-------|---------------|----------|
| **Calcular Saldos** | Borrador | Lee los saldos contables actuales de todas las cuentas configuradas y llena la tabla (saldos NO se congelan aún) |
| **Confirmar** | Borrador (solo Gerente) | Congela los saldos como snapshot inmutable. A partir de aquí no se puede editar la tabla |
| **Registrar Pago al SAT** | Confirmada / Pago Parcial | Abre el wizard de pago |
| **Cancelar** | Confirmada, Parcial, Pagada (solo Gerente) | Abre wizard de cancelación con campo de motivo |
| **Imprimir** | Cualquier estado excepto Borrador | Genera el reporte PDF |
| **Asientos** (botón inteligente) | Cuando hay asientos generados | Muestra todos los asientos contables relacionados |

---

## 8. Pantalla: Wizard de Pago al SAT

Se abre al presionar **"Registrar Pago al SAT"** en la liquidación confirmada.

### 8.1 Barra de Información Superior

```
╔══════════════════════════════════════════════════════════════════╗
║  Liquidación: LIQS/MY C/2026/01/...  |  Período: Enero 2026    ║
║  Pendiente: $400.00                                             ║
╚══════════════════════════════════════════════════════════════════╝
```

Muestra el contexto de la liquidación y el total pendiente de pago. Es de solo lectura.

### 8.2 Bloque "Datos del Pago"

| Campo | Descripción | Notas |
|-------|-------------|-------|
| **Fecha de Pago** | Fecha en que se realizó la transferencia al SAT | Por defecto = hoy; puede ser anterior |
| **Monto Total a Pagar** | Importe total de este evento de pago | Debe coincidir exactamente con la suma de la distribución |
| **Modo de Distribución** | `Prorrateo Automático` o `Asignación Manual` | En automático, el sistema distribuye el monto proporcionalmente entre conceptos pendientes |

### 8.3 Bloque "Datos Bancarios"

| Campo | Descripción | Notas |
|-------|-------------|-------|
| **Cuenta Bancaria** | La cuenta bancaria desde donde se realizó la transferencia | Solo cuentas de la empresa activa |
| **Referencia Bancaria** | Número de operación / folio de la transferencia | **Se pre-rellena con la Referencia SAT de la liquidación** |

> **💡 Tip:** La Referencia SAT que capturaste en la liquidación se trae automáticamente aquí. Si el banco asignó un número diferente, puedes modificarla.

### 8.4 Indicador de Cuadre

```
╔══════════════════════════════════════════════════════╗
║  ✅  Distribución cuadrada correctamente.            ║
║      Total distribuido: $400.00                     ║
╚══════════════════════════════════════════════════════╝
```

Si la distribución NO cuadra con el Monto Total:
```
╔══════════════════════════════════════════════════════╗
║  ⚠️  La distribución no está cuadrada.              ║
║      Diferencia: $50.00                             ║
╚══════════════════════════════════════════════════════╝
```

El botón **"Confirmar Pago"** permanece oculto mientras no esté cuadrado.

### 8.5 Tabla de Distribución por Concepto

```
┌──────────────────────────┬───────────┬──────────────────┬──────────┐
│ Concepto                 │ Pendiente │ Monto a Aplicar  │ Cubierto │
├──────────────────────────┼───────────┼──────────────────┼──────────┤
│ IVA Retenido a Terceros  │  $400.00  │       $400.00    │    ✅    │
└──────────────────────────┴───────────┴──────────────────┴──────────┘
```

| Columna | Descripción |
|---------|-------------|
| **Concepto** | Nombre del concepto fiscal con obligación pendiente |
| **Pendiente** | Monto comprometido en la liquidación que falta pagar |
| **Monto a Aplicar** | En modo automático se calcula solo; en modo manual lo editas |
| **Cubierto** ✅ | Verde cuando `Monto a Aplicar = Pendiente` |

> **Modo Manual:** Si pagas un monto parcial (ej: $200 de $400 pendiente), usa "Asignación Manual" y edita el campo "Monto a Aplicar" para cada concepto.

### 8.6 Botones del Wizard

| Botón | Condición | Efecto |
|-------|-----------|--------|
| **Confirmar Pago y Generar Asiento** | Solo visible si la distribución está cuadrada | Genera y contabiliza el asiento; cambia estado de liquidación |
| **Cancelar** | Siempre | Cierra el wizard sin cambios |

### 8.7 Asiento Generado Automáticamente

Al confirmar, el sistema genera el asiento contable en el diario configurado:

```
MISCE / AAAA-MM-DD
Referencia: LIQS/MY C/.../Enero 2026 / {Referencia_Bancaria}

─────────────────────────────────────────────────────────────────────
CONCEPTO: IVA Retenido a Terceros
─────────────────────────────────────────────────────────────────────
Dr. 216.10.20  IVA Ret. Efect. Pagado    400.00  ← cancela deuda SAT
Dr. 118.01.01  IVA Acreditable           400.00  ← libera IVA pendiente
Cr. 118.01.03  IVA Acred. Pendiente      400.00  ← se agota
Cr. 102.09.01  Pagos Emitidos            400.00  ← por bancos (para conciliar)
─────────────────────────────────────────────────────────────────────
TOTALES:       $800.00                   $800.00  ✅ Cuadrado
─────────────────────────────────────────────────────────────────────
```

> **Nota sobre los $800:** El asiento tiene 4 líneas que suman $800 en cada lado. Esto es correcto — las líneas de `118.01.01`/`118.01.03` se netean entre sí ($400 Dr − $400 Cr = $0 neto). El movimiento de efectivo real es solo $400 (Dr 216.10.20 = Cr Banco).

---

## 9. Casos de Uso por Tipo de Retención

### 9.1 Procedimiento Mensual General

Este es el flujo que debes seguir **cada mes** (a más tardar el día 17):

```
1. Contabilizar todas las facturas del mes
2. Registrar todos los pagos a proveedores del mes
3. Menú: Liquidación Fiscal → Liquidaciones → [Nuevo]
4. Capturar: Período, Fecha de Corte, Diario, Referencia SAT
5. Clic: [Calcular Saldos]   ← lee la contabilidad
6. Revisar tabla: verificar que los montos coincidan con tu declaración SAT
7. Ajustar "A Pagar" si hay diferencias justificadas (agregar Justificación)
8. Clic: [Confirmar]         ← congela los saldos (solo Gerente)
9. Realizar la transferencia bancaria al SAT
10. Clic: [Registrar Pago al SAT]
11. Wizard: seleccionar cuenta bancaria, verificar referencia, confirmar
12. Verificar asiento generado en pestaña "Pagos al SAT"
```

### 9.2 Retención IVA Fletes (4%)

**Obligación mensual:** Pagar los $400 que retuviste al transportista.

**Lo que verás en la liquidación:**
- IVA Retenido a Terceros: Saldo Pasivo = $400 (216.10.20)
- Determinado = $400
- A Pagar = $400

**Asiento al pagar SAT:**
```
Dr. 216.10.20    400   (SAT pagado ✅)
Dr. 118.01.01    400   (IVA acreditable liberado ✅)
Cr. 118.01.03    400   (IVA pendiente se agota ✅)
Cr. Banco trán.  400   (para conciliar)
```

### 9.3 Retención IVA Honorarios Persona Física (2/3 partes = 10.67%)

**Ejemplo:** Factura de $5,000 honorarios:
- IVA 16% = $800
- Retención 2/3 = $533.33
- ISR 10% = $500
- Pago al proveedor = $5,000 + $266.67 (1/3 IVA) − $500 ISR = $4,766.67

**Lo que verás en la liquidación (mes siguiente):**
- RET_HON: Saldo Pasivo = $500 (ISR)
- IVA_RET: Saldo Pasivo = $533.33 (IVA retenido)

### 9.4 Retención IVA Arrendamiento Persona Física (2/3 partes = 10.67%)

Idéntico a Honorarios. Solo cambia:
- La cuenta pasivo → `216.03.01` (arrendamiento) en lugar de `216.04.01` (honorarios)
- El concepto LSat → `RET_ARR` en lugar de `RET_HON`

### 9.5 Pago Parcial en un Mes

Si tienes obligaciones por $5,000 pero solo pagas $3,000:

1. En el wizard, usa **Modo Manual**
2. Distribuye $3,000 entre los conceptos según tu prelación
3. La liquidación queda en estado **"Pago Parcial"**
4. El mes siguiente (o cuando tengas fondos) regresa y registra el pago restante
5. La liquidación cierra a **"Pagada"** cuando Pendiente = $0

---

## 10. Conciliación Bancaria

### ¿Cómo funciona la cuenta de tránsito?

El módulo **no abona directamente al banco** (`102.01.01`). En su lugar abona a la **cuenta de Pagos Emitidos** del diario bancario (ej: `102.09.01` Pagos Emitidos en Tránsito).

Esto permite conciliar exactamente igual que cualquier otro pago de Odoo:

```
1. Importar extracto bancario en Odoo
   (Contabilidad → Banco → [tu banco] → Importar)

2. En la columna de transacciones:
   verás el débito de $400 por la transferencia al SAT

3. En "Pagos Registrados / Pendientes de Conciliar":
   aparecerá la línea del asiento MISCE con $400

4. Hacer match → la cuenta de tránsito se limpia
```

Si el diario bancario no tiene configurada la cuenta de Pagos Emitidos, el sistema usará la cuenta principal del banco como fallback. Para configurarla:

```
Contabilidad → Configuración → Diarios → [tu diario bancario]
→ Pagos Salientes → Método: Pago Manual
→ Cuenta de Pagos Emitidos Pendientes: 102.09.01
```

---

## 11. Preguntas Frecuentes

**P: ¿Por qué aparece "IVA por Pagar -$1,200" si no hice ventas?**

R: Es correcto. El CBMX registró $1,200 en `118.01.01` (IVA acreditable de compras). Esa cuenta es parte de la compensación de IVA_PAGAR. Como no hay ventas, el resultado es: Pasivo $0 − Compensación $1,200 = **Determinado -$1,200 (Saldo a Favor)**. Ese saldo a favor se arrastrará en los meses siguientes para reducir el IVA a pagar cuando sí haya ventas. **No genera ningún asiento ni pago.**

---

**P: ¿Qué pasa si calculo y los saldos no coinciden con mi declaración SAT?**

R: Puedes editar el campo **"A Pagar"** en cada línea para ingresar el monto exacto de tu declaración. Si la diferencia supera el umbral (por defecto 5%), el sistema te pedirá que escribas una **Justificación**. Esto queda en la bitácora de auditoría.

---

**P: ¿Puedo cancelar una liquidación ya pagada?**

R: Sí, con el rol de Gerente. Al cancelar, el sistema revierte los asientos contables generados y la liquidación queda en estado "Cancelada" con el motivo registrado en la bitácora. Deberás generar y contabilizar los ajustes manuales si el pago bancario ya se realizó.

---

**P: ¿Se puede hacer una liquidación anual o hay que hacerla mensual?**

R: El módulo está diseñado para liquidaciones **mensuales** conforme a la obligación del SAT (declaración mensual). Cada liquidación corresponde a un mes calendario. No se puede crear dos liquidaciones para el mismo mes en la misma empresa.

---

**P: ¿Por qué el asiento MISCE tiene $800 de débitos y $800 de créditos si solo pagué $400?**

R: El asiento tiene 4 líneas. Las dos líneas de `118.01.03` y `118.01.01` se netean entre sí (ambas por $400, una débito y una crédito), por lo que el movimiento neto de esas cuentas es cero. El único flujo de efectivo real es Dr. `216.10.20` $400 / Cr. Banco $400. El total de $800 en cada lado es aritméticamente correcto y el asiento cuadra.

---

**P: ¿Cómo sé qué cuenta se usará para el abono al banco en el asiento?**

R: El sistema determina la cuenta en este orden:
1. Cuenta de Pagos Emitidos del método de pago saliente del diario bancario seleccionado
2. Cuenta principal del diario bancario
3. Cuenta principal del diario de liquidación (fallback)

Para garantizar la conciliación correcta, configura la **Cuenta de Pagos Emitidos Pendientes** en tu diario bancario.

---

*Manual generado para mx_tax_liquidation v17.0.1.0.0 | Odoo 17 Enterprise*
*Última actualización: Febrero 2026*
