BEGIN;

-- Tabla con todas las líneas que modificamos
CREATE TEMP TABLE rev AS
-- +DIOT:Refunds que pasamos a -DIOT:Refunds (tag 1169→1170)
SELECT rel.account_move_line_id AS aml_id, 1169 AS old_tag, 1170 AS new_tag
FROM account_account_tag_account_move_line_rel rel
JOIN account_move_line aml ON aml.id = rel.account_move_line_id
WHERE rel.account_account_tag_id = 1169 AND aml.tax_tag_invert = FALSE
UNION ALL
-- +DIOT:16% que pasamos a -DIOT:16% (tag 1127→1128)
SELECT rel.account_move_line_id, 1127, 1128
FROM account_account_tag_account_move_line_rel rel
JOIN account_move_line aml ON aml.id = rel.account_move_line_id
JOIN account_move am ON am.id = aml.move_id
WHERE rel.account_account_tag_id = 1127 AND aml.tax_tag_invert = FALSE
  AND am.company_id IN (6, 15)
UNION ALL
-- +DIOT:Retención que pasamos a -DIOT:Retención (tag 1167→1168)
SELECT rel.account_move_line_id, 1167, 1168
FROM account_account_tag_account_move_line_rel rel
WHERE rel.account_move_line_id IN (208592,208937,211491,211547)
  AND rel.account_account_tag_id = 1167;

-- Quitar tags negativos que pusimos
DELETE FROM account_account_tag_account_move_line_rel
WHERE (account_move_line_id, account_account_tag_id) IN (
  SELECT aml_id, old_tag FROM rev
);

-- Poner tags positivos originales
INSERT INTO account_account_tag_account_move_line_rel (account_move_line_id, account_account_tag_id)
SELECT aml_id, new_tag FROM rev
ON CONFLICT DO NOTHING;

-- Restaurar tax_tag_invert = TRUE
UPDATE account_move_line SET tax_tag_invert = TRUE
WHERE id IN (SELECT DISTINCT aml_id FROM rev);

-- La 1 línea in_refund company=15 que pasamos de -DIOT:Ret(1167) a +DIOT:Ret(1168)
-- Está ahora en tag 1168, in_refund, co=15, invert=FALSE — revertir a 1167, invert=TRUE
DELETE FROM account_account_tag_account_move_line_rel
WHERE account_account_tag_id = 1168
  AND account_move_line_id IN (
    SELECT aml.id FROM account_move_line aml
    JOIN account_move am ON am.id = aml.move_id
    WHERE am.move_type = 'in_refund' AND am.company_id = 15 AND aml.tax_tag_invert = FALSE
  );

INSERT INTO account_account_tag_account_move_line_rel (account_move_line_id, account_account_tag_id)
SELECT aml.id, 1167 FROM account_move_line aml
JOIN account_move am ON am.id = aml.move_id
WHERE am.move_type = 'in_refund' AND am.company_id = 15 AND aml.tax_tag_invert = FALSE
  AND NOT EXISTS (
    SELECT 1 FROM account_account_tag_account_move_line_rel r
    WHERE r.account_move_line_id = aml.id AND r.account_account_tag_id = 1167
  )
ON CONFLICT DO NOTHING;

UPDATE account_move_line SET tax_tag_invert = TRUE
WHERE id IN (
  SELECT aml.id FROM account_move_line aml
  JOIN account_move am ON am.id = aml.move_id
  WHERE am.move_type = 'in_refund' AND am.company_id = 15 AND aml.tax_tag_invert = FALSE
);

-- Verificar: deben quedar 656 líneas DIOT con invert=TRUE (estado original)
SELECT COUNT(*) AS diot_invert_true_restored
FROM account_account_tag_account_move_line_rel rel
JOIN account_account_tag aat ON aat.id = rel.account_account_tag_id
JOIN account_move_line aml ON aml.id = rel.account_move_line_id
WHERE aat.name::text LIKE '%DIOT%' AND aml.tax_tag_invert = TRUE;

COMMIT;
