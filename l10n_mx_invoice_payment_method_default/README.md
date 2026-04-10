# MX: Heredar y Asignar Forma de Pago Correcta

## Problema Resuelto

Al crear facturas desde Órdenes de Venta o Traslados (PACK), el sistema no heredaba correctamente la forma de pago del cliente, causando que facturas **PUE** (Pago en Una Exhibición) tuvieran forma **"99 Por Definir"**, lo cual es **ilegal según el SAT**.

## Solución Implementada

Este módulo **reemplaza la Acción Automatizada ID 21** con una solución más eficiente y completa.

### ¿Qué hace el módulo?

### ¿Qué hace el módulo?

Al crear facturas:

1. **Hereda forma de pago del cliente** si está configurada
2. **Valida compatibilidad** entre Policy (PUE/PPD) y Forma de Pago
3. **Asigna default inteligente** según reglas SAT:
   - **PPD** → SIEMPRE forma "99 Por Definir"
   - **PUE** → NUNCA forma "99", default "03 Transferencia Electrónica"
4. **Valida al guardar** que no se usen combinaciones incorrectas (reemplaza Acción ID 21)

## Reglas SAT Aplicadas

### PPD (Pago en Parcialidades o Diferido)
- ✅ **DEBE** usar forma de pago "99 - Por Definir"
- Porque el pago se completará después, la forma exacta no se conoce al emitir

### PUE (Pago en Una Exhibición)
- ❌ **NUNCA** puede usar forma "99 - Por Definir"
- ✅ Debe usar forma específica: 01-Efectivo, 03-Transferencia, 04-Tarjeta, etc.
- Default: **"03 - Transferencia Electrónica de Fondos"** (más común)

## Funcionalidad

### Al Crear Factura (create)
```python
1. Detecta si es factura de cliente (out_invoice)
2. Obtiene partner y su forma de pago configurada
3. Determina Policy (PUE/PPD) del término de pago
4. Hereda forma de pago del cliente si existe
5. Si no hay forma de pago:
   - PPD → Asigna "99 Por Definir"
   - PUE → Asigna "03 Transferencia"
6. Valida: Si PUE tiene forma 99 → Corrige a 03 automáticamente
```

### Al Cambiar Cliente (onchange partner_id)
```python
1. Toma forma de pago del nuevo cliente
2. Valida compatibilidad con Policy actual
3. Si es incompatible, ajusta según reglas SAT
```

### Al Cambiar Policy (onchange payment_policy)
```python
1. Detecta cambio de PUE ↔ PPD
2. Ajusta forma de pago automáticamente:
   - Cambio a PPD → Forma 99
   - Cambio a PUE → Forma del cliente o 03
```

## Casos de Uso

### Caso 1: Factura desde SO con cliente configurado
```
Cliente: Juan Pérez
Forma pago cliente: 03 - Transferencia
Término pago: 30 días (PPD)

Resultado:
- Policy: PPD
- Forma pago: 99 (Por Definir) ← Sobrescribe la del cliente según regla SAT
```

### Caso 2: Factura desde PACK sin forma en cliente
```
Cliente: María González
Forma pago cliente: (vacío)
Término pago: Inmediato (PUE)

Resultado:
- Policy: PUE
- Forma pago: 03 (Transferencia) ← Default inteligente
```

### Caso 3: Factura directa PUE
```
Cliente: Carlos López
Forma pago cliente: 01 - Efectivo
Término pago: Inmediato (PUE)

Resultado:
- Policy: PUE
- Forma pago: 01 (Efectivo) ← Hereda del cliente
```

## Instalación

### Paso 1: Copiar módulo
```bash
# En servidor
cd /opt/odoo/custom/addons/
# Copiar carpeta l10n_mx_invoice_payment_method_default
```

### Paso 2: Actualizar lista
```bash
# Modo desarrollador en Odoo
Apps → Actualizar Lista de Aplicaciones

# O por línea de comandos
sudo -u odoo /opt/odoo/venv/bin/odoo-bin -c /etc/odoo/odoo.conf \
  -d DATABASE --update=l10n_mx_invoice_payment_method_default --stop-after-init
```


### Paso 4: Desactivar Acción Automatizada ID 21
```sql
-- Ejecutar DESPUÉS de instalar y probar el módulo
-- Ver archivo: post_install_desactivar_accion_21.sql

UPDATE base_automation 
SET active = false 
WHERE id = 21;
```

⚠️ **IMPORTANTE**: Desactivar la acción ID 21 solo DESPUÉS de:
1. Instalar el módulo
2. Probar que funciona correctamente
3. Verificar validaciones en facturas PUE y PPD
### Paso 3: Instalar
```
Apps → Buscar "Heredar y Asignar Forma de Pago"
→ Instalar
```

## TestingValidación Manual (Bloqueo)
1. Crear factura PUE
2. Intentar cambiar forma a 99 manualmente
3. Intentar guardar
4. ✅ Verificar: Error claro indicando que PUE no puede usar forma 99

### Test 5: Validación PPD
1. Crear factura PPD con término 30 días
2. Intentar cambiar forma a 03 (Transferencia) manualmente
3. Intentar guardar
4. ✅ Verificar: Error indicando que PPD debe usar forma 99

## Por Qué Este Módulo en Lugar de Acción Automatizada

### Ventajas vs Acción ID 21

| Aspecto | Acción ID 21 | Este Módulo |
|---------|--------------|-------------|
| **Rendimiento** | Se ejecuta en CADA write | Solo en create + validación write |
| **Lógica** | Dispersa en BD | Centralizada en código |
| **Mantenibilidad** | Difícil modificar | Fácil modificar en Python |
| **Corrección** | Solo bloquea | Corrige automáticamente |
| **Mensajes** | Genéricos | Claros y específicos |
| **Testing** | Difícil probar | Fácil con tests unitarios |

### Migración Segura

1. **Instalar módulo en QA** → Probar funcionamiento
2. **Mantener acción ID 21 activa** → Doble validación durante pruebas
3. **Validar todas las combinaciones** → Asegurar que funciona
4. **Desactivar acción ID 21** → Solo después de confirmar
5. **Monitorear logs** → Verificar que no hay errores
6. **Repetir en producción** → Mismo proceso
2. Término pago: Inmediato
3. Crear SO y facturar
4. ✅ Verificar: Factura tiene forma 03

### Test 2: SO → Factura (PPD)
1. Cliente con forma 03 (Transferencia)
2. Término pago: 30 días
3. Crear SO y facturar
4. ✅ Verificar: Factura tiene forma 99 (no 03)

### Test 3: Cliente sin forma configurada
1. Cliente sin forma de pago
2. Término pago: Inmediato (PUE)
3. Crear factura manual
4. ✅ Verificar: Forma 03 asignada automáticamente

### Test 4: Cambio de Policy
1. Crear factura PUE (debería tener forma ≠ 99)
2. Cambiar policy a PPD
3. ✅ Verificar: Forma cambia a 99 automáticamente

## Compatibilidad

- Odoo 17 Enterprise
- Módulos requeridos: `account`, `l10n_mx_edi`, `sale`
- Compatible con módulos custom de facturación

## Logs

El módulo registra en logs:
```
✅ Factura INV/2026/001: Heredando forma de pago del cliente Juan Pérez
✅ Factura INV/2026/002 PUE: Asignando forma 03 (Transferencia) por defecto
✅ Factura INV/2026/003 PPD: Asignando forma 99 (Por Definir)
⚠️ Factura DRAFT PUE tenía forma 99, corregida a 03 (Transferencia)
```

Revisar: `/var/log/odoo/odoo.log`

## Notas Importantes

1. **No modifica facturas existentes** - Solo aplica a nuevas
2. **Respeta configuración del cliente** cuando es compatible con SAT
3. **Corrige automáticamente** combinaciones incorrectas (PUE + 99)
4. **Funciona con** facturación desde SO, PACK, y manual

## Autor

Industrias Cosal - Localización México
Versión: 17.0.1.0.0
License: LGPL-3
