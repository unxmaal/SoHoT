import unittest

from orchard.helpers import bucket
from orchard import payroll


class Payroll(unittest.TestCase):
    def test_bucket(self):
        self.assertEqual(bucket(5, [0, 5, 10]), 2)
        self.assertEqual(bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(bucket(12, [0, 5, 10]), 3)

    def test_truncate_words(self):
        self.assertEqual(payroll.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(payroll.truncate_words('tea time', 2), 'tea time')
