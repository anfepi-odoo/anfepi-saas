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
    # CORRECCIONES DE DATOS: (company_id, ValidationError)
    # =================================================================================

    # 1. CORRECCIÓN GLOBAL DEFINITIVA: Renombrar cuenta 601.84.02
    # El UPDATE se usa en lugar de DELETE para evitar fallar por Foreign Key 
    # y se usa un código único que no será recreado por el Plan Contable (l10n_mx).
    cr.execute(
        """
        UPDATE account_account
        SET code = '601.84.02_LEGACY_CONFLICT'
        WHERE code = '601.84.02';
        """
    )

    # Encuentra el ID de la compañía 'Asesores y Soluciones ANFEPI SC'
    cr.execute("SELECT id FROM res_company WHERE name = 'Asesores y Soluciones ANFEPI SC'")
    company_id_target = cr.fetchone()
    
    if company_id_target:
        company_id_target = company_id_target[0]
        
        # 2. CORRECCIÓN DE COMPAÑÍA: Actualiza la cuenta 113.02.01 (UserError)
        cr.execute(
            """
            UPDATE account_account
            SET company_id = %s
            WHERE code = '113.02.01'
            """,
            (company_id_target,)
        )
        
        # Obtiene el ID de la cuenta 113.02.01 recién corregida.
        cr.execute(
            """
            SELECT id FROM account_account 
            WHERE code = '113.02.01' AND company_id = %s
            """, 
            (company_id_target,)
        )
        account_ids = [res[0] for res in cr.fetchall()]

        # 3. CORRECCIÓN DE LÍNEAS DE REPARTO: Actualiza las líneas de impuestos asociadas (113.02.01)
        if account_ids:
            cr.execute(
                """
                UPDATE account_tax_repartition_line
                SET company_id = %s
                WHERE account_id IN %s
                """,
                (company_id_target, tuple(account_ids))
            )
