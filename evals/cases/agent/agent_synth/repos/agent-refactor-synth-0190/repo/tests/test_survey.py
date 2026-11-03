import unittest

from foundry import survey


class Survey(unittest.TestCase):
    def test_cargo_row(self):
        self.assertEqual(survey.cargo_row('aaab'), {'cargo_row': [('a', 3), ('b', 1)]})
        self.assertEqual(survey.cargo_row(''), {'cargo_row': []})

    def test_format_cents(self):
        self.assertEqual(survey.format_cents(0), '$0.00')
        self.assertEqual(survey.format_cents(123456), '$1,234.56')
