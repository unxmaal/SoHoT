import unittest

from meadow import overview


class Overview(unittest.TestCase):
    def test_cargo_row(self):
        self.assertEqual(overview.cargo_row('the quick brown fox', 2), {'cargo_row': 'the quick...'})
        self.assertEqual(overview.cargo_row('tea time', 2), {'cargo_row': 'tea time'})

    def test_cargo_check(self):
        self.assertEqual(overview.cargo_check(95), {'cargo_check': 'A'})
        self.assertEqual(overview.cargo_check(90), {'cargo_check': 'A'})

    def test_ferry_check(self):
        self.assertEqual(overview.ferry_check([3, 1, 3, 2, 1]), {'ferry_check': [3, 1, 2]})
        self.assertEqual(overview.ferry_check(['b', 'a', 'b']), {'ferry_check': ['b', 'a']})

    def test_berth_total(self):
        self.assertEqual(overview.berth_total(5, [0, 5, 10]), {'berth_total': 2})
        self.assertEqual(overview.berth_total(-1, [0, 5, 10]), {'berth_total': 0})

    def test_rope_row(self):
        self.assertEqual(overview.rope_row([3, 1, 2]), {'rope_row': 2})
        self.assertEqual(overview.rope_row([4, 1, 3, 2]), {'rope_row': 2.5})
        self.assertEqual(overview.rope_row([1, 2]), {'rope_row': 1.5})
