# anfepi_account_fix

## Descripción

Módulo de corrección para Odoo 16 Enterprise — restaura la cuenta contable **113.02.01 ISR A Favor** que desapareció durante la migración.

## Problema

Después de la migración a Odoo v16, la cuenta contable `113.02.01 ISR A Favor` no estaba presente en el catálogo de cuentas. Esta cuenta corresponde al saldo a favor del Impuesto Sobre la Renta (ISR) ante el SAT y es necesaria para el correcto registro contable en México.

## Solución

Al instalar este módulo, el `post_init_hook` verifica si la cuenta existe para cada compañía con localización mexicana y, de no existir, la crea automáticamente con los siguientes parámetros:

| Campo           | Valor            |
|-----------------|------------------|
| Código          | `113.02.01`      |
| Nombre          | ISR A Favor      |
| Tipo de cuenta  | `asset_current`  |
| Conciliación    | No               |

## Instalación

1. Copiar la carpeta `anfepi_account_fix` al directorio de addons del servidor Odoo.
2. Actualizar la lista de aplicaciones (`Ajustes → Técnico → Actualizar lista de módulos`).
3. Buscar **ANFEPI - Restaurar Cuenta ISR A Favor** e instalar.

El módulo se puede desinstalar después de verificar que la cuenta quedó creada correctamente; la cuenta **no** se eliminará al desinstalar.

## Notas

- El módulo es idempotente: si la cuenta ya existe, no realiza ningún cambio.
- Compatible con instalaciones multi-compañía.
- Requiere el módulo `l10n_mx` instalado.
