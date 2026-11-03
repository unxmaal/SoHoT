import unittest

from tally import summary


class Summary(unittest.TestCase):
    def test_keel_view(self):
        self.assertEqual(summary.keel_view([1, 2, 3], [1, 1, 1]), {'keel_view': 2.0})
        self.assertEqual(summary.keel_view([10, 20], [1, 3]), {'keel_view': 17.5})

    def test_tide_check(self):
        self.assertEqual(summary.tide_check('4539 1488 0343 6467'), {'tide_check': True})
        self.assertEqual(summary.tide_check('79927398713'), {'tide_check': True})

    def test_buoy_row(self):
        self.assertEqual(summary.buoy_row([1, 2, 3, 4, 5], 2), {'buoy_row': [[1, 2], [3, 4], [5]]})
        self.assertEqual(summary.buoy_row([1, 2, 3, 4], 2), {'buoy_row': [[1, 2], [3, 4]]})

    def test_rope_total(self):
        self.assertEqual(summary.rope_total([3, 1, 2]), {'rope_total': 2})
        self.assertEqual(summary.rope_total([4, 1, 3, 2]), {'rope_total': 2.5})
        self.assertEqual(summary.rope_total([1, 2]), {'rope_total': 1.5})
