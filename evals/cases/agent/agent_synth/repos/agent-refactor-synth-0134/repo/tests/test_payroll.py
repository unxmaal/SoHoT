import unittest

from granary import payroll


class Payroll(unittest.TestCase):
    def test_rope_total(self):
        self.assertEqual(payroll.rope_total(5, 0, 10), {'rope_total': 5})
        self.assertEqual(payroll.rope_total(-3, 0, 10), {'rope_total': 0})

    def test_truncate_words(self):
        self.assertEqual(payroll.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(payroll.truncate_words('tea time', 2), 'tea time')
