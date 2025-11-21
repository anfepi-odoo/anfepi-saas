from odoo.upgrade import util

def migrate(cr):
    # =================================================================================
    # CORRECCIONES PARA TABLA: account_move (Errores de columna)
    # =================================================================================
    
    # 1. New stored field: account.move/extract_state (type: varchar, default: 'no_extract_requested')
    util.create_column(
        cr,
        'account_move',
        'extract_state',
        'varchar',
        default="'no_extract_requested'"
    )

    # 2. New computed-stored field: account.move/is_in_extractable_state (type: bool)
    util.create_column(
        cr,
        'account_move',
        'is_in_extractable_state',
        'bool'
    )

    # 3. New computed-stored field: account.move/extract_state_processed (type: bool)
    util.create_column(
        cr,
        'account_move',
        'extract_state_processed',
        'bool'
    )
    
    # =================================================================================
    # CORRECCIONES PARA TABLA: account_move_line (Errores de columna)
    # =================================================================================

    # 4. New stored field: account.move.line/extract_state (type: varchar, default: 'no_extract_requested')
    util.create_column(
        cr,
        'account_move_line',
        'extract_state',
        'varchar',
        default="'no_extract_requested'"
    )

    # 5. New many2one field: account.move.line/tax_line_id (type: integer)
    util.create_column(
        cr,
        'account_move_line',
        'tax_line_id',
        'int'
    )

    # 6. New many2many field: account.move.line/tag_ids (M2M)
    # Crea la tabla de relación Many2many si no existe.
    cr.execute(
        """
        CREATE TABLE IF NOT EXISTS account_move_line_account_account_tag_rel
        (
            account_move_line_id INTEGER NOT NULL,
            account_account_tag_id INTEGER NOT NULL,
            UNIQUE (account_move_line_id, account_account_tag_id)
        );
        """
    )
    
    # =================================================================================
    # CORRECCIONES DE DATOS CRÍTICOS: (Unicidad y Compañía)
    # =================================================================================

    # 1. CORRECCIÓN DE UNICIDAD: Renombrar cuenta 601.84.02
    # El UPDATE se usa para evitar fallar por Foreign Key y se usa un código único 
    # que no será recreado por el Plan Contable (l10n_mx).
    cr.execute(
        """
        UPDATE account_account
        SET code = '601.84.02_LEGACY_CONFLICT'
        WHERE code = '601.84.02';
        """
    )
    
    # 2. CORRECCIÓN DE COMPAÑÍA: Eliminar líneas de reparto fiscal conflictivas (113.02.01)
    # Eliminamos las líneas de reparto (tax repartition lines) asociadas a la cuenta '113.02.01'. 
    # Esto resuelve el UserError de compañía. Las líneas correctas serán recreadas 
    # por la migración del módulo l10n_mx.
    cr.execute(
        """
        DELETE FROM account_tax_repartition_line
        WHERE account_id IN (
            SELECT id FROM account_account
            WHERE code = '113.02.01'
        );
        """
    )
