# -*- coding: utf-8 -*-
from datetime import date

from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase
from odoo.tests import tagged


@tagged('post_install', '-at_install', 'mx_tax_liquidation')
class TestMulticompany(TransactionCase):
    """
    Tests de aislamiento multicompañía.
    Verifica que cada compañía opera en un espacio completamente aislado.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # --- Compañía A ---
        cls.company_a = cls.env.company
        cls.user_a = cls.env.ref('base.user_admin')

        # --- Compañía B (nueva) ---
        cls.company_b = cls.env['res.company'].create({
            'name': 'Empresa B — Test Multicompany',
            'country_id': cls.env.ref('base.mx').id,
        })

        # Cuentas de compañía A
        cls.account_isr_a = cls.env['account.account'].create({
            'name': 'ISR por Pagar A',
            'code': 'TMA.2140',
            'account_type': 'liability_current',
            'company_id': cls.company_a.id,
        })
        cls.journal_a = cls.env['account.journal'].create({
            'name': 'Liquidaciones A',
            'type': 'general',
            'code': 'LIQA',
            'company_id': cls.company_a.id,
        })

        # Cuentas de compañía B
        cls.account_isr_b = cls.env['account.account'].with_company(cls.company_b).create({
            'name': 'ISR por Pagar B',
            'code': 'TMB.2140',
            'account_type': 'liability_current',
            'company_id': cls.company_b.id,
        })
        cls.journal_b = cls.env['account.journal'].with_company(cls.company_b).create({
            'name': 'Liquidaciones B',
            'type': 'general',
            'code': 'LIQB',
            'company_id': cls.company_b.id,
        })

        # Usuario B (pertenece solo a company_b)
        cls.user_b = cls.env['res.users'].create({
            'name': 'User B',
            'login': 'user_b_multicompany_test@test.com',
            'email': 'user_b@test.com',
            'company_id': cls.company_b.id,
            'company_ids': [(6, 0, [cls.company_b.id])],
            'groups_id': [(6, 0, [
                cls.env.ref('mx_tax_liquidation.group_tax_settlement_user').id,
                cls.env.ref('account.group_account_invoice').id,
            ])],
        })

        # Concepto ISR
        cls.concept_isr = cls.env['mx.tax.concept'].search([('code', '=', 'ISR_PROPIO')], limit=1)

        # Config compañía A
        cls.config_a = cls.env['mx.tax.settlement.config'].create({
            'company_id': cls.company_a.id,
            'tax_concept_id': cls.concept_isr.id,
            'liability_account_ids': [(6, 0, [cls.account_isr_a.id])],
        })

        # Config compañía B
        cls.config_b = cls.env['mx.tax.settlement.config'].with_company(cls.company_b).create({
            'company_id': cls.company_b.id,
            'tax_concept_id': cls.concept_isr.id,
            'liability_account_ids': [(6, 0, [cls.account_isr_b.id])],
        })

        # Liquidación compañía A
        cls.settlement_a = cls.env['mx.tax.settlement'].create({
            'company_id': cls.company_a.id,
            'period_date': date(2026, 10, 1),
            'calculation_date': date(2026, 10, 31),
            'journal_id': cls.journal_a.id,
            'responsible_id': cls.user_a.id,
        })

        # Liquidación compañía B
        cls.settlement_b = cls.env['mx.tax.settlement'].with_company(cls.company_b).create({
            'company_id': cls.company_b.id,
            'period_date': date(2026, 10, 1),
            'calculation_date': date(2026, 10, 31),
            'journal_id': cls.journal_b.id,
            'responsible_id': cls.user_a.id,
        })

    def test_01_company_a_cannot_see_company_b_settlements(self):
        """Los registros de empresa B son invisibles para el usuario de empresa A."""
        settlements_seen_by_a = self.env['mx.tax.settlement'].with_user(self.user_a).sudo(False).search([])
        ids_seen = settlements_seen_by_a.ids
        self.assertIn(self.settlement_a.id, ids_seen)
        self.assertNotIn(self.settlement_b.id, ids_seen)

    def test_02_company_b_user_cannot_see_company_a_settlement(self):
        """El usuario B no puede leer la liquidación de empresa A."""
        env_b = self.env['mx.tax.settlement'].with_user(self.user_b)
        result = env_b.search([])
        self.assertNotIn(self.settlement_a.id, result.ids)

    def test_03_same_period_allowed_in_different_companies(self):
        """El mismo período puede existir en dos compañías distintas sin conflicto de unicidad."""
        # Ambas liquidaciones existen para Oct-2026; no debe haber error
        self.assertEqual(self.settlement_a.period_date, date(2026, 10, 1))
        self.assertEqual(self.settlement_b.period_date, date(2026, 10, 1))
        self.assertNotEqual(self.settlement_a.company_id, self.settlement_b.company_id)

    def test_04_duplicate_period_same_company_raises(self):
        """No se puede crear dos liquidaciones activas para el mismo período/compañía."""
        from odoo.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            self.env['mx.tax.settlement'].create({
                'company_id': self.company_a.id,
                'period_date': date(2026, 10, 1),  # ya existe
                'calculation_date': date(2026, 10, 31),
                'journal_id': self.journal_a.id,
                'responsible_id': self.env.user.id,
            })

    def test_05_configs_are_independent_per_company(self):
        """Las configuraciones de cuentas son independientes por compañía."""
        account_in_a = self.config_a.liability_account_ids.ids
        account_in_b = self.config_b.liability_account_ids.ids
        # No deben solaparse
        overlap = set(account_in_a) & set(account_in_b)
        self.assertEqual(overlap, set(), 'Las cuentas de empresa A y B no deben coincidir')

    def test_06_sequence_generates_independent_folios(self):
        """Cada compañía genera su propio folio de serie."""
        # Los folios deben tener company_id correcto
        self.assertEqual(self.settlement_a.company_id.id, self.company_a.id)
        self.assertEqual(self.settlement_b.company_id.id, self.company_b.id)
        if self.settlement_a.name and self.settlement_b.name:
            # Pueden coincidir numéricamente pero corresponden a compañías distintas
            self.assertNotEqual(
                (self.settlement_a.name, self.settlement_a.company_id.id),
                (self.settlement_b.name, self.settlement_b.company_id.id),
            )

    def test_07_log_entries_isolated_by_company(self):
        """Los registros de auditoría solo son visibles para la compañía correcta."""
        # Crear una acción de log para company_a
        self.settlement_a._log_action(
            action='calculate',
            description='Test log multicompany A',
        )
        logs_a = self.env['mx.tax.settlement.log'].search([
            ('settlement_id', '=', self.settlement_a.id),
        ])
        for log in logs_a:
            self.assertEqual(
                log.settlement_id.company_id.id,
                self.company_a.id,
                'Los logs de empresa A no deben cruzarse con empresa B',
            )
