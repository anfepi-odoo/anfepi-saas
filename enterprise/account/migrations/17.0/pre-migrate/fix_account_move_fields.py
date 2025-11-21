from odoo.upgrade import util

def migrate(cr):
    # (Secciones 1 a 6 de create_column y CREATE TABLE se mantienen iguales)
    # ...

    # =================================================================================
    # CORRECCIONES DE DATOS: (company_id, ValidationError)
    # =================================================================================

    # 1. CORRECCIÓN GLOBAL DE UNICIDAD: ELIMINAR cuenta 601.84.02 (ValidationError)
    cr.execute(
        """
        DELETE FROM account_account
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
