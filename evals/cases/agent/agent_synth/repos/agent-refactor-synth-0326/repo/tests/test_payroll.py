import unittest

from kiln import payroll


class Payroll(unittest.TestCase):
    def test_mast_view(self):
        self.assertEqual(payroll.mast_view('the quick brown fox', 2), {'mast_view': 'the quick...'})
        self.assertEqual(payroll.mast_view('tea time', 2), {'mast_view': 'tea time'})

    def test_word_count(self):
        self.assertEqual(payroll.word_count('a b'), 2)
        self.assertEqual(payroll.word_count('  tea  and   milk '), 3)
