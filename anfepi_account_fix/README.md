# anfepi_account_fix

## Descripción

Módulo de corrección para Odoo 16 Enterprise — restaura la cuenta contable **113.02.01 ISR A Favor** que desapareció durante la migración.

## Problema

Después de la migración a Odoo v16, la cuenta contable `113.02.01 ISR A Favor` no estaba presente en el catálogo de cuentas. Esta cuenta corresponde al saldo a favor del Impuesto Sobre la Renta (ISR) ante el SAT y es necesaria para el correcto registro contable en México.

## Solución

Al instalar este módulo, el `post_init_hook` ejecuta **tres pasos** por cada compañía con localización mexicana:

### 1. Crea la cuenta (si no existe)

| Campo           | Valor            |
|-----------------|------------------|
| Código          | `113.02.01`      |
| Nombre          | ISR A Favor      |
| Tipo de cuenta  | `asset_current`  |
| Conciliación    | No               |

### 2. Repara líneas de asiento huérfanas

Durante la migración, al eliminar la cuenta del catálogo, las líneas de los
asientos contables (`account.move.line`) que la referenciaban pueden haber
quedado con `account_id = NULL` o apuntando a un `id` ya inexistente.

El módulo detecta ambos casos mediante SQL directo y reasigna esas líneas a
la cuenta recién creada, **restableciendo el cuadre de los asientos**.

> **Nota:** El log de Odoo registrará con nivel `WARNING` cuántas líneas
> fueron reasignadas para que puedas confirmar que el mapeo es correcto.

### 3. Reporta asientos que aún queden descuadrados

Después de la reparación, el hook busca asientos registrados cuya diferencia
débito/crédito sea mayor a 0.01 MXN y los lista con nivel `ERROR` en el log,
indicando su nombre, id y diferencia. Esos asientos requerirán revisión manual.

## Instalación

1. Copiar la carpeta `anfepi_account_fix` al directorio de addons del servidor Odoo.
2. Actualizar la lista de aplicaciones (`Ajustes → Técnico → Actualizar lista de módulos`).
3. Buscar **ANFEPI - Restaurar Cuenta ISR A Favor** e instalar.

El módulo se puede desinstalar después de verificar que la cuenta quedó creada correctamente; la cuenta **no** se eliminará al desinstalar.

## Notas

- El módulo es idempotente: si la cuenta ya existe, no realiza ningún cambio.
- Compatible con instalaciones multi-compañía.
- Requiere el módulo `l10n_mx` instalado.
