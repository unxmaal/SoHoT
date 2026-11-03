import unittest

from quarry import billing


class Billing(unittest.TestCase):
    def test_berth_row(self):
        self.assertEqual(billing.berth_row('4539 1488 0343 6467'), {'berth_row': True})
        self.assertEqual(billing.berth_row('79927398713'), {'berth_row': True})

    def test_grade(self):
        self.assertEqual(billing.grade(95), 'A')
        self.assertEqual(billing.grade(90), 'A')
