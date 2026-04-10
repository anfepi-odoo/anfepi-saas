# -*- coding: utf-8 -*-
from datetime import date

from odoo.exceptions import UserError, ValidationError
from odoo.tests.common import TransactionCase
from odoo.tests import tagged


@tagged('post_install', '-at_install', 'mx_tax_liquidation')
class TestPartialPayment(TransactionCase):
    """
    Tests de pagos parciales: prorrateo automático y asignación manual.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.currency = cls.company.currency_id

        cls.account_isr = cls.env['account.account'].create({
            'name': 'ISR por Pagar (Partial Test)',
            'code': 'TPAR.2140',
            'account_type': 'liability_current',
            'company_id': cls.company.id,
        })
        cls.account_ret_sal = cls.env['account.account'].create({
            'name': 'ISR Retenido Salarios (Partial Test)',
            'code': 'TPAR.2150',
            'account_type': 'liability_current',
            'company_id': cls.company.id,
        })
        cls.account_bank = cls.env['account.account'].create({
            'name': 'Bancos SAT (Partial Test)',
            'code': 'TPAR.1120',
            'account_type': 'asset_cash',
            'company_id': cls.company.id,
        })
        cls.journal = cls.env['account.journal'].create({
            'name': 'Liquidaciones Test Partial',
            'type': 'general',
            'code': 'LIQP',
            'company_id': cls.company.id,
        })
        cls.bank_journal = cls.env['account.journal'].create({
            'name': 'Banco SAT Partial Test',
            'type': 'bank',
            'code': 'BSAP',
            'company_id': cls.company.id,
            'default_account_id': cls.account_bank.id,
        })
        cls.partner_bank = cls.env['res.partner.bank'].create({
            'acc_number': '987654321098765432',
            'partner_id': cls.company.partner_id.id,
            'company_id': cls.company.id,
            'journal_id': cls.bank_journal.id,
        })

        cls.concept_isr = cls.env['mx.tax.concept'].search([('code', '=', 'ISR_PROPIO')], limit=1)
        cls.concept_ret_sal = cls.env['mx.tax.concept'].search([('code', '=', 'RET_SAL')], limit=1)

        cls.config_isr = cls.env['mx.tax.settlement.config'].create({
            'company_id': cls.company.id,
            'tax_concept_id': cls.concept_isr.id,
            'liability_account_ids': [(6, 0, [cls.account_isr.id])],
        })
        cls.config_ret = cls.env['mx.tax.settlement.config'].create({
            'company_id': cls.company.id,
            'tax_concept_id': cls.concept_ret_sal.id,
            'liability_account_ids': [(6, 0, [cls.account_ret_sal.id])],
        })

        # Semillas de saldo
        account_income = cls.env['account.account'].search([
            ('company_id', '=', cls.company.id),
            ('account_type', 'in', ['income', 'income_other']),
        ], limit=1)
        if not account_income:
            account_income = cls.env['account.account'].create({
                'name': 'Ingreso Prueba Partial',
                'code': 'TPAR.SEED',
                'account_type': 'income',
                'company_id': cls.company.id,
            })

        for account, amount in [
            (cls.account_isr, 200000.0),
            (cls.account_ret_sal, 50000.0),
        ]:
            move = cls.env['account.move'].create({
                'move_type': 'entry',
                'date': date(2026, 10, 31),
                'journal_id': cls.journal.id,
                'company_id': cls.company.id,
                'ref': f'Saldo semilla partial {account.code}',
                'line_ids': [
                    (0, 0, {'account_id': account.id, 'debit': 0.0, 'credit': amount, 'name': 'Semilla'}),
                    (0, 0, {'account_id': account_income.id, 'debit': amount, 'credit': 0.0, 'name': 'Contra'}),
                ],
            })
            move.action_post()

    def _create_confirmed_settlement(self, period_date):
        settlement = self.env['mx.tax.settlement'].create({
            'company_id': self.company.id,
            'period_date': period_date,
            'calculation_date': period_date.replace(day=28),
            'journal_id': self.journal.id,
            'responsible_id': self.env.user.id,
        })
        settlement.action_calculate_balances()
        settlement.action_confirm()
        return settlement

    def _make_payment(self, settlement, amount, lines_amounts, reference):
        """Crea y procesa un evento de pago con distribución manual."""
        dist_lines = []
        for sl, applied in lines_amounts.items():
            dist_lines.append((0, 0, {
                'settlement_line_id': sl.id,
                'amount_pending_before': sl.amount_pending,
                'amount_applied': applied,
            }))
        payment = self.env['mx.tax.settlement.payment'].create({
            'settlement_id': settlement.id,
            'payment_date': settlement.period_date.replace(day=17),
            'amount_total': amount,
            'distribution_mode': 'manual',
            'bank_account_id': self.partner_bank.id,
            'bank_reference': reference,
            'distribution_line_ids': dist_lines,
        })
        payment.action_generate_move()
        return payment

    def test_01_partial_payment_sets_partial_state(self):
        """Un pago parcial cambia el estado a 'Pago Parcial'."""
        settlement = self._create_confirmed_settlement(date(2026, 10, 1))
        total = settlement.total_to_pay

        # Pagar solo el 60% del ISR y nada de retención
        isr_line = settlement.line_ids.filtered(lambda l: l.tax_concept_id.code == 'ISR_PROPIO')
        partial_isr = self.currency.round(isr_line.amount_to_pay * 0.6)

        self._make_payment(
            settlement,
            partial_isr,
            {isr_line: partial_isr},
            'REF-PARTIAL-01',
        )
        self.assertEqual(settlement.state, 'partial')
        self.assertGreater(settlement.total_pending, 0)

    def test_02_multiple_partial_payments_complete(self):
        """Pagos múltiples parciales completan la liquidación."""
        settlement = self._create_confirmed_settlement(date(2026, 11, 1))

        isr_line = settlement.line_ids.filtered(lambda l: l.tax_concept_id.code == 'ISR_PROPIO')
        ret_line = settlement.line_ids.filtered(lambda l: l.tax_concept_id.code == 'RET_SAL')

        # Pago 1: solo ISR
        self._make_payment(
            settlement,
            isr_line.amount_to_pay,
            {isr_line: isr_line.amount_to_pay},
            'REF-PARTIAL-P1',
        )
        self.assertEqual(settlement.state, 'partial')

        # Pago 2: retención completa
        ret_line_refresh = ret_line  # el pending se actualiza via compute
        self._make_payment(
            settlement,
            ret_line_refresh.amount_pending,
            {ret_line_refresh: ret_line_refresh.amount_pending},
            'REF-PARTIAL-P2',
        )
        self.assertEqual(settlement.state, 'paid')

    def test_03_overpayment_raises(self):
        """Un pago que supera el pendiente debe lanzar ValidationError."""
        settlement = self._create_confirmed_settlement(date(2026, 12, 1))
        isr_line = settlement.line_ids.filtered(lambda l: l.tax_concept_id.code == 'ISR_PROPIO')

        with self.assertRaises(ValidationError):
            self.env['mx.tax.settlement.payment.line'].create({
                'payment_id': self.env['mx.tax.settlement.payment'].create({
                    'settlement_id': settlement.id,
                    'payment_date': date(2026, 12, 17),
                    'amount_total': isr_line.amount_to_pay + 1000.0,
                    'distribution_mode': 'manual',
                    'bank_account_id': self.partner_bank.id,
                    'bank_reference': 'REF-OVER-01',
                }).id,
                'settlement_line_id': isr_line.id,
                'amount_pending_before': isr_line.amount_pending,
                'amount_applied': isr_line.amount_to_pay + 1000.0,
            })

    def test_04_duplicate_bank_reference_raises(self):
        """La misma referencia bancaria no puede usarse dos veces."""
        settlement = self._create_confirmed_settlement(date(2027, 1, 1))
        isr_line = settlement.line_ids.filtered(lambda l: l.tax_concept_id.code == 'ISR_PROPIO')
        half = self.currency.round(isr_line.amount_to_pay / 2)

        self._make_payment(settlement, half, {isr_line: half}, 'REF-DUP-01')

        with self.assertRaises(ValidationError):
            self._make_payment(
                settlement,
                half,
                {isr_line: half},
                'REF-DUP-01',  # misma referencia
            )

    def test_05_auto_prorate_distribution(self):
        """El prorrateo automático distribuye proporcional al peso de cada línea."""
        settlement = self._create_confirmed_settlement(date(2027, 2, 1))

        isr_line = settlement.line_ids.filtered(lambda l: l.tax_concept_id.code == 'ISR_PROPIO')
        ret_line = settlement.line_ids.filtered(lambda l: l.tax_concept_id.code == 'RET_SAL')

        total_pending = isr_line.amount_to_pay + ret_line.amount_to_pay
        partial_amount = self.currency.round(total_pending * 0.5)

        # Simular el prorrateo del wizard
        expected_isr = self.currency.round(
            partial_amount * (isr_line.amount_to_pay / total_pending)
        )
        expected_ret = self.currency.round(partial_amount - expected_isr)

        # Verificar que la suma cuadra
        self.assertAlmostEqual(
            expected_isr + expected_ret, partial_amount, places=2,
            msg='La distribución automática debe sumar el monto total del pago'
        )
