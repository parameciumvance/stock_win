from datetime import date
from decimal import Decimal
import unittest

from .paid_subscription_scenario_v15 import SubscriptionTerms, subscribe


class SubscriptionScenarioTests(unittest.TestCase):
    def setUp(self):
        self.terms = SubscriptionTerms(
            "exrights:2540:20250205", date(2025, 2, 5), Decimal("60.00864364"),
            Decimal("83"), date(2025, 2, 14), date(2025, 3, 14))

    def test_integer_entitlement_and_cash_constraint(self):
        result = subscribe(self.terms, 1000, Decimal("1000"), date(2025, 2, 14))
        self.assertEqual(result.eligible_whole_shares, 60)
        self.assertEqual(result.subscribed_whole_shares, 12)
        self.assertEqual(result.cash_reserved, Decimal("996"))
        self.assertEqual(result.cash_after_payment, Decimal("4"))
        self.assertEqual(result.forfeited_whole_shares, 48)
        self.assertEqual(result.pending_shares, 12)
        self.assertIsNone(result.delivery_date)
        self.assertEqual(result.status, "awaiting_verified_delivery")

    def test_payment_window_and_delivery_chronology(self):
        with self.assertRaisesRegex(ValueError, "Payment outside"):
            subscribe(self.terms, 1000, Decimal("10000"), date(2025, 2, 10))
        terms = SubscriptionTerms(**{**self.terms.__dict__,
                                     "delivery_date": date(2025, 2, 14)})
        with self.assertRaisesRegex(ValueError, "Delivery must follow"):
            subscribe(terms, 1000, Decimal("10000"), date(2025, 2, 14))

    def test_normalized_one_unit_portfolio_cannot_fake_real_subscription(self):
        result = subscribe(self.terms, 0, Decimal("1"), date(2025, 2, 14))
        self.assertEqual(result.subscribed_whole_shares, 0)
        self.assertEqual(result.cash_after_payment, Decimal("1"))


if __name__ == "__main__":
    unittest.main()
