# Manual de Usuario — MX Tax Liquidation

**Módulo:** `mx_tax_liquidation`  
**Versión:** 17.0.1.0.0  
**Plataforma:** Odoo 17 Enterprise  
**Autor:** ANFEPI: Roberto Requejo Jiménez | https://www.anfepi.com

---

## Índice

1. [Introducción](#1-introducción)
2. [Principio rector del módulo](#2-principio-rector-del-módulo)
3. [Perfil de usuarios y permisos](#3-perfil-de-usuarios-y-permisos)
4. [Configuración inicial](#4-configuración-inicial)
5. [Crear una liquidación mensual](#5-crear-una-liquidación-mensual)
6. [Calcular saldos](#6-calcular-saldos)
7. [Revisar y ajustar las líneas](#7-revisar-y-ajustar-las-líneas)
8. [Confirmar la liquidación](#8-confirmar-la-liquidación)
9. [Registrar un pago](#9-registrar-un-pago)
10. [Pagos parciales](#10-pagos-parciales)
11. [Consultar la bitácora de auditoría](#11-consultar-la-bitácora-de-auditoría)
12. [Cancelar una liquidación](#12-cancelar-una-liquidación)
13. [Reportes](#13-reportes)
14. [Preguntas frecuentes](#14-preguntas-frecuentes)

---

## 1. Introducción

**MX Tax Liquidation** es una herramienta integrada en Odoo 17 Enterprise que permite gestionar
el pago mensual de las principales obligaciones fiscales en México:

- ISR cargo propio
- IVA neto por pagar
- IVA retenido a clientes
- Retenciones de ISR (salarios, honorarios, arrendamiento, asimilados, dividendos)

El módulo **lee los saldos contables ya registrados** en el sistema y genera los asientos
de cancelación de pasivos contra la cuenta bancaria del SAT. No recalcula impuestos
ni recorre facturas individuales.

---

## 2. Principio rector del módulo

> **"El módulo es un liquidador de saldos contables. No recalcula impuestos,
> no recorre facturas. Solo cancela los pasivos fiscales ya registrados contra bancos."**

Esto significa que:

- Si el saldo de una cuenta está incorrecto, primero se corrige en contabilidad; luego se liquida.
- El módulo confía en los saldos al corte de fecha que usted configure.
- Los ajustes manuales en las líneas son posibles, pero quedan registrados en la bitácora.

---

## 3. Perfil de usuarios y permisos

| Grupo | Acceso |
|---|---|
| **Usuario** | Ver liquidaciones propias de su compañía; registrar pagos |
| **Gerente** | Todo lo anterior + confirmar, cancelar, modificar monto a pagar |
| **Auditor** | Solo lectura de todos los registros incluyendo bitácora |
| **Configuración** | Gestión de catálogos y configuración de cuentas |

El administrador de Odoo asigna el grupo adecuado desde
*Ajustes → Usuarios y Compañías → Usuarios*.

---

## 4. Configuración inicial

### 4.1 Configurar el diario de liquidaciones

Ir a *Contabilidad → Configuración → Ajustes* y localizar la sección
**Liquidación de Impuestos**.

- **Diario de liquidación fiscal**: seleccione el diario general que se usará para
  los asientos de pago (recomendado: crear un diario exclusivo llamado "Liquidaciones SAT").
- **Umbral de diferencia aceptable (%)**: porcentaje máximo tolerable entre el saldo
  calculado y el monto que se pagará (default: 5 %). Si la diferencia es mayor, el sistema
  mostrará una advertencia al confirmar.
- **Requerir adjunto documentos**: si está activo, no se podrá confirmar una liquidación
  sin adjuntar al menos una evidencia (formulario SAT, acuse, etc.).

### 4.2 Configurar conceptos fiscales

Ir a *Contabilidad → Configuración → Conceptos Fiscales (Liquidación)*.

El sistema incluye 8 conceptos predefinidos. Para cada uno, revise y configure:

| Campo | Descripción |
|---|---|
| Nombre | Nombre descriptivo del concepto |
| Código | Clave única (ISR_PROPIO, IVA_PAGAR, etc.) |
| Tipo | iva / isr / retencion |
| Naturaleza | liability (pasivo) / asset (acreditable) |
| Requiere reclasificación | Solo para IVA retenido; genera asiento atómico de 2 líneas |

### 4.3 Mapear cuentas contables por concepto

Ir a *Contabilidad → Configuración → Configuración de Liquidación*.

Para cada combinación compañía/concepto, configure:

| Campo | Descripción |
|---|---|
| Compañía | Empresa a la que aplica |
| Concepto fiscal | Concepto que se va a liquidar |
| Cuentas de pasivo | Una o más cuentas cuyo saldo HABER representa la obligación |
| Cuentas de compensación | (Opcional) Cuentas acreditables que reducen el monto a pagar (ej. IVA acreditable) |
| Cuenta fuente reclasificación | Obligatoria si el concepto tiene "Requiere reclasificación" activo |

> **Ejemplo:** Para IVA por pagar, las cuentas de pasivo serían `2160 IVA Trasladado`
> y las de compensación `1190 IVA Acreditable`. El sistema calculará:
> `monto_a_pagar = max(IVA_Trasladado - IVA_Acreditable, 0)`

---

## 5. Crear una liquidación mensual

1. Ir a *Contabilidad → Liquidación Fiscal → Liquidaciones*.
2. Hacer clic en **Nuevo**.
3. Completar los campos de la cabecera:

| Campo | Descripción |
|---|---|
| Período | Mes y año a liquidar (primer día del mes) |
| Fecha de corte | Fecha hasta la cual se consideran movimientos (normalmente el último día del mes) |
| Diario | Diario de liquidaciones configurado |
| Responsable | Usuario responsable de la declaración |

4. Opcionalmente agregar notas internas o adjuntar documentos preliminares.
5. **Guardar** (queda en estado *Borrador*).

---

## 6. Calcular saldos

Una vez en *Borrador*, hacer clic en **Calcular Saldos**.

El sistema ejecutará una consulta SQL contra `account_move_line` con los filtros:

- `state = 'posted'` (solo apuntes contabilizados)
- `company_id = su_empresa`
- `account_id` dentro de las cuentas configuradas para cada concepto
- `date <= fecha_de_corte`

Se crearán automáticamente las líneas de la liquidación, una por concepto activo
con su configuración correspondiente.

### Información de cada línea

| Columna | Descripción |
|---|---|
| Concepto | Nombre del concepto fiscal |
| Saldo Pasivo | Suma de créditos de las cuentas de pasivo |
| Saldo Compensación | Suma de créditos de las cuentas acreditables |
| Monto Determinado | `max(Pasivo - Compensación, 0)` |
| Monto a Pagar | Valor editable (arranca igual al Determinado) |
| Monto Pagado | Suma de pagos aplicados |
| Pendiente | `Monto a Pagar - Monto Pagado` |
| Estado Línea | Pendiente / Parcial / Pagado / Diferido / Cero |

> Si un concepto tiene saldo cero en sus cuentas, la línea mostrará estado **Cero**
> y no generará asiento al pagar.

---

## 7. Revisar y ajustar las líneas

Antes de confirmar, puede:

- **Modificar el Monto a Pagar**: si por alguna razón el monto real a enterar difiere
  del saldo calculado (pagos a cuenta anteriores, resoluciones SAT, etc.).
  La diferencia se registra automáticamente en la bitácora.

- **Diferir un concepto**: cambiar su Monto a Pagar a `0.00` con una nota explicativa.
  El concepto quedará en estado *Diferido* y no generará asiento.

- **Recalcular**: si modifica alguna cuenta o hace apuntes adicionales,
  puede hacer clic nuevamente en **Calcular Saldos** (solo en estado Borrador).
  Se eliminarán las líneas anteriores y se recalculará desde cero.

---

## 8. Confirmar la liquidación

Cuando los montos son correctos, hacer clic en **Confirmar**.

El sistema validará:

- Que no exista otra liquidación activa para el mismo período y compañía.
- Que el Monto a Pagar de cada línea sea ≥ 0.
- Que las diferencias entre saldo calculado y monto a pagar no superen el umbral configurado.
- Que los documentos requeridos estén adjuntos (si el ajuste está activo).

Si todo es correcto, la liquidación pasa a estado **Confirmado** y se bloquea la edición.

---

## 9. Registrar un pago

Desde la liquidación en estado *Confirmado* o *Pago Parcial*, hacer clic en **Pagar Impuestos**.

Se abrirá el asistente de pago con los campos:

| Campo | Descripción |
|---|---|
| Fecha de pago | Fecha efectiva del pago bancario |
| Monto total | Monto real transferido al SAT |
| Modo de distribución | **Automático** (prorrateo) o **Manual** (por concepto) |
| Cuenta bancaria | Cuenta origen del pago |
| Referencia bancaria | Folio / referencia SAT del pago |
| Notas | Observaciones adicionales |

### Modo Automático

El sistema distribuye el monto total entre los conceptos pendientes de forma proporcional:

```
monto_concepto = round(monto_total × (pendiente_concepto / total_pendiente))
```

El centavo residual se asigna al concepto con mayor monto pendiente.

### Modo Manual

Cada línea del asistente muestra el monto pendiente y permite ingresar directamente
el monto a aplicar por concepto. La suma de montos aplicados debe igualar el monto total.

### Asiento generado

Al confirmar el asistente:

- Se crea un `account.move` en estado *Publicado* con:
  - Una línea DEBE por cada cuenta de pasivo liquidada
  - Una línea HABER a la cuenta de liquidez del banco seleccionado
- Para conceptos con **reclasificación** (IVA retenido): el asiento tiene exactamente
  2 líneas: DEBE cuenta_fuente → HABER banco.

---

## 10. Pagos parciales

Si el monto pagado es menor al total pendiente, la liquidación pasa a estado
**Pago Parcial**. Puede registrar tantos pagos adicionales como necesite hasta
completar el total.

Cada pago genera su propio asiento contable independiente con:

- Su propia fecha y referencia bancaria
- Sus propias líneas de distribución

> **Restricciones:**
> - No se puede aplicar más del pendiente de una línea.
> - No se puede usar dos veces la misma referencia bancaria en la misma liquidación.

---

## 11. Consultar la bitácora de auditoría

La pestaña **Bitácora** en el formulario de la liquidación muestra todas las acciones
realizadas con:

- Fecha y hora exacta (UTC)
- Usuario que realizó la acción
- Descripción de la acción
- Valores antes y después (en JSON) para cambios de datos
- Dirección IP del usuario (cuando está disponible)

También puede consultar todas las entradas desde
*Contabilidad → Liquidación Fiscal → Bitácora de Auditoría*.

> La bitácora es **inmutable**: ningún usuario puede modificar ni eliminar registros de auditoría,
> ni siquiera el administrador.

---

## 12. Cancelar una liquidación

Desde el formulario, hacer clic en **Cancelar Liquidación** (requiere rol Gerente).

El asistente solicitará:

- **Motivo de cancelación** (mínimo 20 caracteres, obligatorio)

Si existen asientos de pago publicados, el sistema los **revertirá automáticamente**
creando asientos de contrapartida con fecha igual a la de cada pago original.

> Una liquidación cancelada no puede reabrirse. Si necesita liquidar el mismo período,
> cree una nueva liquidación.

---

## 13. Reportes

### Reporte de Liquidación

Desde el formulario, clic en **Imprimir → Reporte de Liquidación**.

Incluye:
- Encabezado con datos de empresa y período
- Tabla de conceptos con saldos y montos
- Tabla de eventos de pago
- Información de los asientos generados
- Área de firmas (Preparó / Autorizó)

### Reporte de Conciliación

Disponible desde la vista lista de liquidaciones.

Incluye semáforo visual por estado:
- ✅ Verde: diferencia ≤ 2 %
- ⚠️ Amarillo: diferencia entre 2 % y 5 %
- 🔴 Rojo: diferencia > 5 %
- ⬜ Gris: monto determinado = 0

---

## 14. Preguntas frecuentes

**¿Qué pasa si recalculo y los montos cambian?**  
Las líneas se eliminan y se recrean. Si ya confirmó, no puede recalcular; cancele y cree nueva.

**¿Puedo liquidar solo algunos conceptos y diferir otros?**  
Sí. Establezca el Monto a Pagar en `0.00` para los conceptos que desee diferir.
Quedarán en estado *Diferido* sin generar asiento.

**¿El módulo declara en el SAT?**  
No. El módulo solo gestiona el registro contable del pago. La declaración ante el SAT
se realiza por los canales oficiales (portal del SAT, software de declaraciones).

**¿Qué ocurre si el saldo calculado es negativo (saldo favor)?**  
El Monto Determinado se limita a `0.00` mediante la función `max(saldo, 0)`. El saldo
favor queda en la cuenta contable correspondiente para compensación futura.

**¿Puedo cambiar el monto a pagar por encima del saldo calculado?**  
Sí, pero el sistema mostrará advertencia si supera el umbral configurado. El pago en exceso
generará un abono de más en la cuenta de pasivo, que deberá ser revisado por el contador.

**¿Funciona con múltiples empresas?**  
Sí. Cada empresa tiene su propio espacio: configuraciones, liquidaciones, bitácoras y folios
son completamente independientes.

---

*Manual de Usuario — MX Tax Liquidation v17.0.1.0.0*  
*ANFEPI: Roberto Requejo Jiménez | https://www.anfepi.com*
