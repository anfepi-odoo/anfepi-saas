# -*- coding: utf-8 -*-
from datetime import date

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase
from odoo.tests import tagged


@tagged('post_install', '-at_install', 'mx_tax_liquidation')
class TestSettlementFlow(TransactionCase):
    """
    Tests del flujo completo de liquidación fiscal:
    Borrador → Calcular → Confirmar → Pagar → Pagada
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.currency = cls.company.currency_id

        # Crear cuentas contables de prueba
        cls.account_isr = cls.env['account.account'].create({
            'name': 'ISR por Pagar (Test)',
            'code': 'TEST.2140',
            'account_type': 'liability_current',
            'company_id': cls.company.id,
        })
        cls.account_iva_trasladado = cls.env['account.account'].create({
            'name': 'IVA Trasladado Por Enterar (Test)',
            'code': 'TEST.2160',
            'account_type': 'liability_current',
            'company_id': cls.company.id,
        })
        cls.account_iva_acreditable = cls.env['account.account'].create({
            'name': 'IVA Acreditable (Test)',
            'code': 'TEST.1170',
            'account_type': 'asset_current',
            'company_id': cls.company.id,
        })
        cls.account_bank = cls.env['account.account'].create({
            'name': 'Bancos SAT (Test)',
            'code': 'TEST.1120',
            'account_type': 'asset_cash',
            'company_id': cls.company.id,
        })

        # Diario para liquidaciones
        cls.journal = cls.env['account.journal'].create({
            'name': 'Liquidaciones Fiscales SAT (Test)',
            'type': 'general',
            'code': 'LIQS',
            'company_id': cls.company.id,
        })

        # Diario bancario para pagos
        cls.bank_journal = cls.env['account.journal'].create({
            'name': 'Banco SAT Test',
            'type': 'bank',
            'code': 'BSAT',
            'company_id': cls.company.id,
            'default_account_id': cls.account_bank.id,
        })

        # Cuenta bancaria del socio empresa
        cls.partner_bank = cls.env['res.partner.bank'].create({
            'acc_number': '012345678901234567',
            'partner_id': cls.company.partner_id.id,
            'company_id': cls.company.id,
            'journal_id': cls.bank_journal.id,
        })

        # Conceptos fiscales de prueba
        cls.concept_isr = cls.env['mx.tax.concept'].search(
            [('code', '=', 'ISR_PROPIO')], limit=1
        )
        cls.concept_iva = cls.env['mx.tax.concept'].search(
            [('code', '=', 'IVA_PAGAR')], limit=1
        )

        # Configuración de liquidación para ISR
        cls.config_isr = cls.env['mx.tax.settlement.config'].create({
            'company_id': cls.company.id,
            'tax_concept_id': cls.concept_isr.id,
            'liability_account_ids': [(6, 0, [cls.account_isr.id])],
            'difference_threshold_pct': 5.0,
        })

        # Configuración de liquidación para IVA
        cls.config_iva = cls.env['mx.tax.settlement.config'].create({
            'company_id': cls.company.id,
            'tax_concept_id': cls.concept_iva.id,
            'liability_account_ids': [(6, 0, [cls.account_iva_trasladado.id])],
            'compensation_account_ids': [(6, 0, [cls.account_iva_acreditable.id])],
            'difference_threshold_pct': 5.0,
        })

        # Crear saldo en ISR por pagar (asiento previo)
        cls._create_seed_entry(
            cls.account_isr,
            debit=0.0,
            credit=50000.0,
            company=cls.company,
            journal=cls.journal,
        )

        # Crear saldo en IVA trasladado
        cls._create_seed_entry(
            cls.account_iva_trasladado,
            debit=0.0,
            credit=30000.0,
            company=cls.company,
            journal=cls.journal,
        )

        # Crear saldo en IVA acreditable
        cls._create_seed_entry(
            cls.account_iva_acreditable,
            debit=10000.0,
            credit=0.0,
            company=cls.company,
            journal=cls.journal,
        )

    @classmethod
    def _create_seed_entry(cls, account, debit, credit, company, journal):
        """Crea un asiento contable semilla para simular saldos."""
        account_income = cls.env['account.account'].search([
            ('company_id', '=', company.id),
            ('account_type', 'in', ['income', 'income_other']),
        ], limit=1)
        if not account_income:
            account_income = cls.env['account.account'].create({
                'name': 'Ingreso Prueba Semilla',
                'code': 'TEST.SEED',
                'account_type': 'income',
                'company_id': company.id,
            })
        move = cls.env['account.move'].create({
            'move_type': 'entry',
            'date': date(2026, 1, 31),
            'journal_id': journal.id,
            'company_id': company.id,
            'ref': 'Saldo semilla de prueba',
            'line_ids': [
                (0, 0, {
                    'account_id': account.id,
                    'debit': debit,
                    'credit': credit,
                    'name': 'Saldo semilla',
                }),
                (0, 0, {
                    'account_id': account_income.id,
                    'debit': credit,
                    'credit': debit,
                    'name': 'Contraparte semilla',
                }),
            ],
        })
        move.action_post()
        return move

    def _create_settlement(self, period_date=None):
        """Crea una liquidación en borrador."""
        if period_date is None:
            period_date = date(2026, 1, 1)
        return self.env['mx.tax.settlement'].create({
            'company_id': self.company.id,
            'period_date': period_date,
            'calculation_date': date(2026, 1, 31),
            'journal_id': self.journal.id,
            'responsible_id': self.env.user.id,
        })

    # =========================================================
    # TESTS DE FLUJO PRINCIPAL
    # =========================================================

    def test_01_create_settlement(self):
        """Un registro en borrador se crea con folio asignado."""
        settlement = self._create_settlement()
        self.assertNotEqual(settlement.name, '/')
        self.assertTrue(settlement.name.startswith('LIQS/'))
        self.assertEqual(settlement.state, 'draft')
        self.assertEqual(settlement.company_id, self.company)

    def test_02_calculate_balances(self):
        """El cálculo de saldos genera líneas con montos determinados correctos."""
        settlement = self._create_settlement()
        settlement.action_calculate_balances()

        self.assertTrue(len(settlement.line_ids) >= 2)

        isr_line = settlement.line_ids.filtered(
            lambda l: l.tax_concept_id.code == 'ISR_PROPIO'
        )
        iva_line = settlement.line_ids.filtered(
            lambda l: l.tax_concept_id.code == 'IVA_PAGAR'
        )

        self.assertTrue(isr_line, 'Debe existir línea de ISR')
        self.assertTrue(iva_line, 'Debe existir línea de IVA')

        # ISR: saldo acreedor de 50,000 → determinado = 50,000
        self.assertAlmostEqual(isr_line.amount_determined, 50000.0, places=2)

        # IVA: 30,000 trasladado - 10,000 acreditable = 20,000
        self.assertAlmostEqual(iva_line.amount_determined, 20000.0, places=2)

    def test_03_confirm_settlement(self):
        """La confirmación bloquea el registro y registra usuario/timestamp."""
        settlement = self._create_settlement()
        settlement.action_calculate_balances()
        settlement.action_confirm()

        self.assertEqual(settlement.state, 'confirmed')
        self.assertIsNotNone(settlement.confirmation_date)
        self.assertEqual(settlement.confirmation_uid, self.env.user)

    def test_04_confirm_without_lines_raises(self):
        """No se puede confirmar sin líneas calculadas."""
        settlement = self._create_settlement()
        with self.assertRaises(UserError):
            settlement.action_confirm()

    def test_05_duplicate_settlement_raises(self):
        """No puede existir una segunda liquidación activa para el mismo período."""
        settlement1 = self._create_settlement(period_date=date(2026, 2, 1))
        settlement1.action_calculate_balances()

        with self.assertRaises(UserError):
            settlement2 = self._create_settlement(period_date=date(2026, 2, 1))
            settlement2.action_calculate_balances()

    def test_06_negative_amount_to_pay_raises(self):
        """El monto a pagar no puede ser negativo."""
        settlement = self._create_settlement()
        settlement.action_calculate_balances()
        line = settlement.line_ids[0]
        with self.assertRaises(ValidationError):
            line.amount_to_pay = -100.0

    def test_07_full_payment_sets_state_paid(self):
        """Un pago completo mueve la liquidación a estado Pagada."""
        settlement = self._create_settlement(period_date=date(2026, 3, 1))
        settlement.action_calculate_balances()
        settlement.action_confirm()

        # Crear pago con distribución manual
        total = settlement.total_to_pay
        dist_lines = []
        for line in settlement.line_ids.filtered(lambda l: l.amount_to_pay > 0):
            dist_lines.append((0, 0, {
                'settlement_line_id': line.id,
                'amount_pending_before': line.amount_pending,
                'amount_applied': line.amount_to_pay,
            }))

        payment = self.env['mx.tax.settlement.payment'].create({
            'settlement_id': settlement.id,
            'payment_date': date(2026, 3, 17),
            'amount_total': total,
            'distribution_mode': 'manual',
            'bank_account_id': self.partner_bank.id,
            'bank_reference': 'REF-TEST-FULL-0001',
            'distribution_line_ids': dist_lines,
        })
        payment.action_generate_move()

        self.assertEqual(payment.state, 'posted')
        self.assertIsNotNone(payment.move_id)
        self.assertEqual(settlement.state, 'paid')

    def test_08_generated_move_is_balanced(self):
        """El asiento generado debe estar cuadrado (débitos = créditos)."""
        settlement = self._create_settlement(period_date=date(2026, 4, 1))
        settlement.action_calculate_balances()
        settlement.action_confirm()
        total = settlement.total_to_pay

        dist_lines = []
        for line in settlement.line_ids.filtered(lambda l: l.amount_to_pay > 0):
            dist_lines.append((0, 0, {
                'settlement_line_id': line.id,
                'amount_pending_before': line.amount_pending,
                'amount_applied': line.amount_to_pay,
            }))

        payment = self.env['mx.tax.settlement.payment'].create({
            'settlement_id': settlement.id,
            'payment_date': date(2026, 4, 17),
            'amount_total': total,
            'distribution_mode': 'manual',
            'bank_account_id': self.partner_bank.id,
            'bank_reference': 'REF-TEST-BALANCE-0001',
            'distribution_line_ids': dist_lines,
        })
        payment.action_generate_move()

        move = payment.move_id
        self.assertEqual(move.state, 'posted')

        total_debit = sum(move.line_ids.mapped('debit'))
        total_credit = sum(move.line_ids.mapped('credit'))
        self.assertAlmostEqual(total_debit, total_credit, places=2,
                               msg='El asiento debe estar cuadrado')

    def test_09_audit_log_created(self):
        """Se generan entradas de bitácora en cada acción relevante."""
        settlement = self._create_settlement(period_date=date(2026, 5, 1))
        settlement.action_calculate_balances()
        settlement.action_confirm()

        log_actions = settlement.log_ids.mapped('action')
        self.assertIn('create', log_actions)
        self.assertIn('calculate', log_actions)
        self.assertIn('confirm', log_actions)

    def test_10_log_immutability(self):
        """Los registros de bitácora no pueden ser modificados ni eliminados."""
        settlement = self._create_settlement(period_date=date(2026, 6, 1))
        settlement.action_calculate_balances()
        log = settlement.log_ids[0]

        from odoo.exceptions import AccessError
        with self.assertRaises(AccessError):
            log.write({'description': 'Intento de modificación'})

        with self.assertRaises(AccessError):
            log.unlink()

    def test_11_period_normalized_to_first_day(self):
        """El período se normaliza al primer día del mes automáticamente."""
        settlement = self.env['mx.tax.settlement'].create({
            'company_id': self.company.id,
            'period_date': date(2026, 7, 15),  # día 15
            'calculation_date': date(2026, 7, 31),
            'journal_id': self.journal.id,
            'responsible_id': self.env.user.id,
        })
        self.assertEqual(settlement.period_date.day, 1,
                         'El período debe normalizarse al primer día del mes')

    def test_12_cannot_delete_confirmed_settlement(self):
        """No se puede eliminar una liquidación confirmada."""
        settlement = self._create_settlement(period_date=date(2026, 8, 1))
        settlement.action_calculate_balances()
        settlement.action_confirm()

        with self.assertRaises(UserError):
            settlement.unlink()

    def test_13_settlement_line_moves_linked(self):
        """Las líneas del asiento tienen referencia a la línea de liquidación."""
        settlement = self._create_settlement(period_date=date(2026, 9, 1))
        settlement.action_calculate_balances()
        settlement.action_confirm()
        total = settlement.total_to_pay

        dist_lines = []
        for line in settlement.line_ids.filtered(lambda l: l.amount_to_pay > 0):
            dist_lines.append((0, 0, {
                'settlement_line_id': line.id,
                'amount_pending_before': line.amount_pending,
                'amount_applied': line.amount_to_pay,
            }))

        payment = self.env['mx.tax.settlement.payment'].create({
            'settlement_id': settlement.id,
            'payment_date': date(2026, 9, 17),
            'amount_total': total,
            'distribution_mode': 'manual',
            'bank_account_id': self.partner_bank.id,
            'bank_reference': 'REF-TEST-LINK-0001',
            'distribution_line_ids': dist_lines,
        })
        payment.action_generate_move()

        # Al menos una línea del asiento debe tener tax_settlement_line_id
        linked = payment.move_id.line_ids.filtered(
            lambda ml: ml.tax_settlement_line_id
        )
        self.assertTrue(len(linked) > 0,
                        'Debe haber líneas del asiento vinculadas a la liquidación')
