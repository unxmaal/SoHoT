import unittest

from granary import payroll


class Payroll(unittest.TestCase):
    def test_top_n(self):
        self.assertEqual(payroll.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(payroll.top_n({'a': 1}, 5), ['a'])

    def test_word_count(self):
        self.assertEqual(payroll.word_count('a b'), 2)
        self.assertEqual(payroll.word_count('  tea  and   milk '), 3)
        self.assertEqual(payroll.word_count(''), 0)

    def test_grade(self):
        self.assertEqual(payroll.grade(95), 'A')
        self.assertEqual(payroll.grade(90), 'A')
