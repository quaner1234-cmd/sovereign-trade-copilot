"""Offline regression coverage for semantic value matching; no API calls."""
import unittest
import pipeline_v3 as P


class MatcherTests(unittest.TestCase):
    def test_date_requires_its_date_tokens(self):
        self.assertFalse(P._value_in("款号 TS-201", "Dec 20"))
        self.assertTrue(P._value_in("delivery before Dec 20", "Dec 20"))
        self.assertTrue(P._value_in("delivery before Dec 20.", "Dec 20"))
        self.assertFalse(P._value_in("delivery before Dec 201", "Dec 20"))
        self.assertFalse(P._value_in("delivery before Nov 20", "Dec 20"))
        self.assertFalse(P._value_in("SKU AB-Dec20", "Dec 20"))

    def test_whole_numbers_and_thousands_separators(self):
        self.assertFalse(P._value_in("3000 pcs", "300"))
        self.assertFalse(P._value_in("1300 pcs", "300"))
        for text, value in (("3,000 pcs", "3000"), ("3000 pcs", "3,000"),
                            ("3,000 pcs", "3,000 pcs"), ("数量300件", "300")):
            with self.subTest(text=text, value=value):
                self.assertTrue(P._value_in(text, value))

    def test_money_keeps_decimal_shape_and_normal_reformatting(self):
        for text, value in (("2.00/件", "USD 2.00"), ("USD2.00", "USD 2.00"),
                            ("18.50/pc", "USD 18.50/pc"), ("USD 4,200", "USD 4200"),
                            ("价格USD 5", "USD 5"), ("USD 2.00.", "USD 2.00")):
            with self.subTest(text=text, value=value):
                self.assertTrue(P._value_in(text, value))
        for text, value in (("USD 20.00", "USD 2.00"), ("USD 2.001", "USD 2.00"),
                            ("USD 200", "USD 2.00"), ("USD 50", "USD 5")):
            with self.subTest(text=text, value=value):
                self.assertFalse(P._value_in(text, value))

    def test_percent_matching_has_numeric_boundaries(self):
        for text, value in (("discount 5%", "5%"), ("discount 5%", "5 percent"),
                            ("deposit 30%", "30%"), ("discount 12.5%", "12.5%")):
            with self.subTest(text=text, value=value):
                self.assertTrue(P._value_in(text, value))
        for text, value in (("discount 15%", "5%"), ("deposit 300%", "30%")):
            with self.subTest(text=text, value=value):
                self.assertFalse(P._value_in(text, value))

    def test_identifier_digits_are_not_numeric_evidence(self):
        for ident in ("TS-201", "AB300", "PO-300", "PI 300", "INV-2.05", "ABCDEF-300", "300ABC"):
            for value in ("Dec 20", "300", "USD 2.05", "30%"):
                with self.subTest(ident=ident, value=value):
                    self.assertFalse(P._value_in(ident, value))
        self.assertTrue(P._value_in("款号 TS-201；价格 USD 2.05", "USD 2.05"))

    def test_existing_one_digit_date_translation_and_conservative_bare_digit(self):
        self.assertTrue(P._value_in("交期11月1日", "Nov 1"))
        self.assertTrue(P._value_in("要求交期10 月 20 日", "10 月 20 日"))
        self.assertFalse(P._value_in("1", "1"))

    def test_requested_date_does_not_reject_compliant_fallback_identifier(self):
        email = ("Our target price is USD 45 for around 300 pcs TS-201 fleece jackets. "
                 "We need delivery before Dec 20.")
        result = P._demo(email)
        attempts = result["raw_model"]["fallback_attempts"]
        self.assertEqual(attempts[0]["template"], "role_aware")
        self.assertTrue(attempts[0]["passed"], attempts[0]["issues"])
        self.assertEqual(len(attempts), 1)
        self.assertIn("TS-201", result["draft"])
        self.assertIn("Dec 20", result["draft"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
