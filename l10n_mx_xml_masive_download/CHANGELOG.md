# Changelog - l10n_mx_xml_masive_download

## [19.0.31.0] - 2026-01-22

### Added
- **Reporte de Conciliación Mejorado**: Portadas funcionalidades avanzadas de V17 a V19
  - `action_view_differences`: Ver diferencias entre SAT y Odoo
  - `action_view_missing_sat`: Visualizar XMLs faltantes en SAT
  - `action_view_extra_odoo`: Visualizar documentos extras en Odoo
  - `action_view_odoo_documents`: Ver documentos relacionados de Odoo
  - `_compute_differences`: Cálculo automático de diferencias
  - `_get_invoice_mismatch`: Detección de desajustes en facturas
  - `_get_payment_mismatch`: Detección de desajustes en pagos
  - `_extract_payment_uuid`: Extracción de UUID de pagos

### Changed
- Actualizado reporte_conciliacion.py de 541 a 724 líneas
- Mejoradas vistas XML del reporte de conciliación

## [19.0.30.5] - 2026-01-22

### Changed
- Versión base del servidor actualizada
- Mejoras generales de estabilidad
