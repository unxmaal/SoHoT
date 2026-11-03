import unittest

from granary import summary


class Summary(unittest.TestCase):
    def test_cargo_check(self):
        self.assertEqual(summary.cargo_check('the quick brown fox', 2), {'cargo_check': 'the quick...'})
        self.assertEqual(summary.cargo_check('tea time', 2), {'cargo_check': 'tea time'})

    def test_mooring_entry(self):
        self.assertEqual(summary.mooring_entry(0), {'mooring_entry': '$0.00'})
        self.assertEqual(summary.mooring_entry(123456), {'mooring_entry': '$1,234.56'})

    def test_sail_total(self):
        self.assertEqual(summary.sail_total([1, 2, 3], [1, 1, 1]), {'sail_total': 2.0})
        self.assertEqual(summary.sail_total([10, 20], [1, 3]), {'sail_total': 17.5})

    def test_sail_check(self):
        self.assertEqual(summary.sail_check({'tea': 3, 'milk': 3, 'jam': 1}, 2), {'sail_check': ['milk', 'tea']})
        self.assertEqual(summary.sail_check({'a': 1}, 5), {'sail_check': ['a']})

    def test_cargo_summary(self):
        self.assertEqual(summary.cargo_summary([3, 1, 3, 2, 1]), {'cargo_summary': [3, 1, 2]})
        self.assertEqual(summary.cargo_summary(['b', 'a', 'b']), {'cargo_summary': ['b', 'a']})
