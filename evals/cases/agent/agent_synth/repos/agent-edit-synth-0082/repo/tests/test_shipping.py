import unittest

from compass import shipping


class Shipping(unittest.TestCase):
    def test_grade(self):
        self.assertEqual(shipping.grade(95), 'A')
        self.assertEqual(shipping.grade(90), 'A')
        self.assertEqual(shipping.grade(85), 'B')

    def test_bucket(self):
        self.assertEqual(shipping.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(shipping.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(shipping.bucket(12, [0, 5, 10]), 3)

    def test_truncate_words(self):
        self.assertEqual(shipping.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(shipping.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(shipping.truncate_words('', 3), '')
