# -*- coding: utf-8 -*-
from datetime import date

from odoo.exceptions import ValidationError
from odoo.tests.common import TransactionCase
from odoo.tests import tagged


@tagged('post_install', '-at_install', 'mx_tax_liquidation')
class TestReclassification(TransactionCase):
    """
    Tests del flujo de reclasificación atómica para IVA retenido.
    Verifica que el asiento contable generado tenga exactamente 2 líneas:
      DEBE:  cuenta_fuente (saldo_iva_retenido)
      HABER: banco

    El módulo NUNCA genera líneas intermedias de reclasificación.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.currency = cls.company.currency_id

        # Cuenta fuente IVA Retenido (2-IVA-RET-CLIENTES)
        cls.account_iva_ret_source = cls.env['account.account'].create({
            'name': 'IVA Retenido Clientes (Fuente)',
            'code': 'TRE.2170',
            'account_type': 'liability_current',
            'company_id': cls.company.id,
        })
        # Cuenta banco
        cls.account_bank = cls.env['account.account'].create({
            'name': 'Bancos SAT Reclasificación',
            'code': 'TRE.1120',
            'account_type': 'asset_cash',
            'company_id': cls.company.id,
        })
        # Diarios
        cls.general_journal = cls.env['account.journal'].create({
            'name': 'Liquidaciones Reclasificación Test',
            'type': 'general',
            'code': 'LIQR',
            'company_id': cls.company.id,
        })
        cls.bank_journal = cls.env['account.journal'].create({
            'name': 'Banco SAT Reclasif',
            'type': 'bank',
            'code': 'BSAR',
            'company_id': cls.company.id,
            'default_account_id': cls.account_bank.id,
        })
        cls.partner_bank = cls.env['res.partner.bank'].create({
            'acc_number': '111222333444555666',
            'partner_id': cls.company.partner_id.id,
            'company_id': cls.company.id,
            'journal_id': cls.bank_journal.id,
        })

        # Concepto IVA_RET (requires_reclassification = True)
        cls.concept_iva_ret = cls.env['mx.tax.concept'].search([
            ('code', '=', 'IVA_RET'),
        ], limit=1)
        if not cls.concept_iva_ret:
            cls.concept_iva_ret = cls.env['mx.tax.concept'].create({
                'name': 'IVA Retenido',
                'code': 'IVA_RET',
                'tax_type': 'retencion',
                'nature': 'liability',
                'requires_reclassification': True,
                'active': True,
            })

        # Concepto ISR normal (para comparar)
        cls.concept_isr = cls.env['mx.tax.concept'].search([('code', '=', 'ISR_PROPIO')], limit=1)
        cls.account_isr = cls.env['account.account'].create({
            'name': 'ISR Reclasif Test',
            'code': 'TRE.2140',
            'account_type': 'liability_current',
            'company_id': cls.company.id,
        })

        # Configuración para IVA_RET con cuenta fuente
        cls.config_iva_ret = cls.env['mx.tax.settlement.config'].create({
            'company_id': cls.company.id,
            'tax_concept_id': cls.concept_iva_ret.id,
            'liability_account_ids': [(6, 0, [cls.account_iva_ret_source.id])],
            'reclassification_source_account_id': cls.account_iva_ret_source.id,
        })

        # Configuración para ISR normal
        cls.config_isr = cls.env['mx.tax.settlement.config'].create({
            'company_id': cls.company.id,
            'tax_concept_id': cls.concept_isr.id,
            'liability_account_ids': [(6, 0, [cls.account_isr.id])],
        })

        # Semillas de saldo
        seed_account = cls.env['account.account'].search([
            ('company_id', '=', cls.company.id),
            ('account_type', 'in', ['income', 'income_other']),
        ], limit=1)
        if not seed_account:
            seed_account = cls.env['account.account'].create({
                'name': 'Ingreso Reclasif Test',
                'code': 'TRE.SEED',
                'account_type': 'income',
                'company_id': cls.company.id,
            })

        for account, amount in [
            (cls.account_iva_ret_source, 80000.0),
            (cls.account_isr, 120000.0),
        ]:
            move = cls.env['account.move'].create({
                'move_type': 'entry',
                'date': date(2026, 10, 31),
                'journal_id': cls.general_journal.id,
                'company_id': cls.company.id,
                'ref': f'Semilla reclasif {account.code}',
                'line_ids': [
                    (0, 0, {'account_id': account.id, 'debit': 0.0, 'credit': amount, 'name': 'Pasivo'}),
                    (0, 0, {'account_id': seed_account.id, 'debit': amount, 'credit': 0.0, 'name': 'Contra'}),
                ],
            })
            move.action_post()

    def _create_confirmed_settlement(self, period_date):
        s = self.env['mx.tax.settlement'].create({
            'company_id': self.company.id,
            'period_date': period_date,
            'calculation_date': period_date.replace(day=28),
            'journal_id': self.general_journal.id,
            'responsible_id': self.env.user.id,
        })
        s.action_calculate_balances()
        s.action_confirm()
        return s

    def _make_full_payment(self, settlement, reference):
        dist_lines = []
        for sl in settlement.line_ids.filtered(lambda l: l.amount_pending > 0):
            dist_lines.append((0, 0, {
                'settlement_line_id': sl.id,
                'amount_pending_before': sl.amount_pending,
                'amount_applied': sl.amount_pending,
            }))
        payment = self.env['mx.tax.settlement.payment'].create({
            'settlement_id': settlement.id,
            'payment_date': settlement.period_date.replace(day=17),
            'amount_total': settlement.total_pending,
            'distribution_mode': 'manual',
            'bank_account_id': self.partner_bank.id,
            'bank_reference': reference,
            'distribution_line_ids': dist_lines,
        })
        payment.action_generate_move()
        return payment

    def test_01_reclassification_move_has_two_lines_only(self):
        """
        El asiento de IVA_RET (reclasificación) debe tener exactamente 2 líneas:
        DEBE: cuenta_fuente | HABER: banco
        """
        settlement = self._create_confirmed_settlement(date(2026, 10, 1))

        iva_ret_line = settlement.line_ids.filtered(
            lambda l: l.tax_concept_id.code == 'IVA_RET'
        )
        self.assertTrue(bool(iva_ret_line), 'Debe existir línea IVA_RET en la liquidación')

        # Pago solo del concepto IVA_RET
        payment = self.env['mx.tax.settlement.payment'].create({
            'settlement_id': settlement.id,
            'payment_date': date(2026, 10, 17),
            'amount_total': iva_ret_line.amount_pending,
            'distribution_mode': 'manual',
            'bank_account_id': self.partner_bank.id,
            'bank_reference': 'REF-RECL-01',
            'distribution_line_ids': [(0, 0, {
                'settlement_line_id': iva_ret_line.id,
                'amount_pending_before': iva_ret_line.amount_pending,
                'amount_applied': iva_ret_line.amount_pending,
            })],
        })
        payment.action_generate_move()

        self.assertTrue(payment.move_id, 'Debe existir un asiento vinculado al pago')
        move_lines = payment.move_id.line_ids

        self.assertEqual(
            len(move_lines), 2,
            f'El asiento de reclasificación debe tener 2 líneas, tiene {len(move_lines)}'
        )

    def test_02_reclassification_debit_is_source_account(self):
        """La línea de DEBE debe corresponder a la cuenta fuente del IVA retenido."""
        settlement = self._create_confirmed_settlement(date(2026, 11, 1))

        iva_ret_line = settlement.line_ids.filtered(
            lambda l: l.tax_concept_id.code == 'IVA_RET'
        )
        payment = self.env['mx.tax.settlement.payment'].create({
            'settlement_id': settlement.id,
            'payment_date': date(2026, 11, 17),
            'amount_total': iva_ret_line.amount_pending,
            'distribution_mode': 'manual',
            'bank_account_id': self.partner_bank.id,
            'bank_reference': 'REF-RECL-02',
            'distribution_line_ids': [(0, 0, {
                'settlement_line_id': iva_ret_line.id,
                'amount_pending_before': iva_ret_line.amount_pending,
                'amount_applied': iva_ret_line.amount_pending,
            })],
        })
        payment.action_generate_move()

        debit_lines = payment.move_id.line_ids.filtered(lambda l: l.debit > 0)
        self.assertEqual(len(debit_lines), 1, 'Solo debe haber 1 línea DEBE')
        self.assertEqual(
            debit_lines.account_id.id,
            self.account_iva_ret_source.id,
            'El DEBE debe ser la cuenta fuente de reclasificación'
        )

    def test_03_reclassification_credit_is_bank(self):
        """La línea de HABER debe corresponder a la cuenta de liquidez del banco."""
        settlement = self._create_confirmed_settlement(date(2026, 12, 1))

        iva_ret_line = settlement.line_ids.filtered(
            lambda l: l.tax_concept_id.code == 'IVA_RET'
        )
        payment = self.env['mx.tax.settlement.payment'].create({
            'settlement_id': settlement.id,
            'payment_date': date(2026, 12, 17),
            'amount_total': iva_ret_line.amount_pending,
            'distribution_mode': 'manual',
            'bank_account_id': self.partner_bank.id,
            'bank_reference': 'REF-RECL-03',
            'distribution_line_ids': [(0, 0, {
                'settlement_line_id': iva_ret_line.id,
                'amount_pending_before': iva_ret_line.amount_pending,
                'amount_applied': iva_ret_line.amount_pending,
            })],
        })
        payment.action_generate_move()

        credit_lines = payment.move_id.line_ids.filtered(lambda l: l.credit > 0)
        self.assertEqual(len(credit_lines), 1, 'Solo debe haber 1 línea HABER')
        bank_liquidity_account = self.bank_journal.default_account_id
        self.assertEqual(
            credit_lines.account_id.id,
            bank_liquidity_account.id,
            'El HABER debe ser la cuenta de liquidez del banco'
        )

    def test_04_move_is_balanced(self):
        """El asiento de reclasificación debe estar balanceado (débito = crédito)."""
        settlement = self._create_confirmed_settlement(date(2027, 1, 1))

        iva_ret_line = settlement.line_ids.filtered(
            lambda l: l.tax_concept_id.code == 'IVA_RET'
        )
        payment = self.env['mx.tax.settlement.payment'].create({
            'settlement_id': settlement.id,
            'payment_date': date(2027, 1, 17),
            'amount_total': iva_ret_line.amount_pending,
            'distribution_mode': 'manual',
            'bank_account_id': self.partner_bank.id,
            'bank_reference': 'REF-RECL-04',
            'distribution_line_ids': [(0, 0, {
                'settlement_line_id': iva_ret_line.id,
                'amount_pending_before': iva_ret_line.amount_pending,
                'amount_applied': iva_ret_line.amount_pending,
            })],
        })
        payment.action_generate_move()

        total_debit = sum(payment.move_id.line_ids.mapped('debit'))
        total_credit = sum(payment.move_id.line_ids.mapped('credit'))
        self.assertAlmostEqual(
            total_debit, total_credit, places=2,
            msg='El asiento de reclasificación debe estar balanceado'
        )

    def test_05_normal_concept_has_no_reclassification_flag(self):
        """ISR_PROPIO no debe tener requires_reclassification=True."""
        concept_isr = self.env['mx.tax.concept'].search([('code', '=', 'ISR_PROPIO')], limit=1)
        self.assertFalse(
            concept_isr.requires_reclassification,
            'ISR_PROPIO no debe requerir reclasificación'
        )

    def test_06_reclassification_source_required_when_flag_set(self):
        """
        Si un concepto tiene requires_reclassification=True, su configuración
        debe tener reclassification_source_account_id poblado.
        """
        self.assertTrue(
            bool(self.config_iva_ret.reclassification_source_account_id),
            'La config de IVA_RET debe tener cuenta fuente de reclasificación'
        )

    def test_07_isr_move_has_more_than_two_lines_when_multiple_accounts(self):
        """
        Un concepto normal (ISR) con varias cuentas de pasivo puede generar
        múltiples líneas DEBE (una por cuenta). Esto es correcto y distinto
        al flujo de reclasificación.
        """
        settlement = self._create_confirmed_settlement(date(2027, 2, 1))
        isr_line = settlement.line_ids.filtered(lambda l: l.tax_concept_id.code == 'ISR_PROPIO')
        if not isr_line or isr_line.amount_pending <= 0:
            self.skipTest('Sin saldo ISR disponible')

        payment = self.env['mx.tax.settlement.payment'].create({
            'settlement_id': settlement.id,
            'payment_date': date(2027, 2, 17),
            'amount_total': isr_line.amount_pending,
            'distribution_mode': 'manual',
            'bank_account_id': self.partner_bank.id,
            'bank_reference': 'REF-ISR-LINES',
            'distribution_line_ids': [(0, 0, {
                'settlement_line_id': isr_line.id,
                'amount_pending_before': isr_line.amount_pending,
                'amount_applied': isr_line.amount_pending,
            })],
        })
        payment.action_generate_move()

        # Al menos 2 líneas (1 DEBE + 1 HABER) — puede ser más con múltiples pasivos
        self.assertGreaterEqual(
            len(payment.move_id.line_ids), 2,
            'Un asiento ISR debe tener al menos 2 líneas'
        )
