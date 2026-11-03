import unittest

from harbor import overview


class Overview(unittest.TestCase):
    def test_ferry_row(self):
        self.assertEqual(overview.ferry_row([1, 2, 3, 4], 2), {'ferry_row': [1.5, 2.5, 3.5]})
        self.assertEqual(overview.ferry_row([5], 1), {'ferry_row': [5.0]})

    def test_quay_line(self):
        self.assertEqual(overview.quay_line('1h30m'), {'quay_line': 5400})
        self.assertEqual(overview.quay_line('45s'), {'quay_line': 45})

    def test_mooring_check(self):
        self.assertEqual(overview.mooring_check([(1, 3), (3, 5)]), {'mooring_check': [(1, 5)]})
        self.assertEqual(overview.mooring_check([(5, 6), (1, 2)]), {'mooring_check': [(1, 2), (5, 6)]})

    def test_harbor_entry(self):
        self.assertEqual(overview.harbor_entry([1, 2, 3, 4, 5], 2), {'harbor_entry': [[1, 2], [3, 4], [5]]})
        self.assertEqual(overview.harbor_entry([1, 2, 3, 4], 2), {'harbor_entry': [[1, 2], [3, 4]]})

    def test_rope_entry(self):
        self.assertEqual(overview.rope_entry(50, 75), {'rope_entry': 50.0})
        self.assertEqual(overview.rope_entry(200, 150), {'rope_entry': -25.0})
        self.assertEqual(overview.rope_entry(3, 4), {'rope_entry': 33.33})
