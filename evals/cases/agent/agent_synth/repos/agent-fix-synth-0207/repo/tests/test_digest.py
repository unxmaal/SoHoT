import unittest

from quarry import digest


class Digest(unittest.TestCase):
    def test_buoy_check(self):
        self.assertEqual(digest.buoy_check('aaab'), {'buoy_check': [('a', 3), ('b', 1)]})
        self.assertEqual(digest.buoy_check(''), {'buoy_check': []})

    def test_harbor_view(self):
        self.assertEqual(digest.harbor_view({'a': 1, 'b': 2, 'c': 1}), {'harbor_view': {1: ['a', 'c'], 2: ['b']}})
        self.assertEqual(digest.harbor_view({}), {'harbor_view': {}})

    def test_rope_summary(self):
        self.assertEqual(digest.rope_summary([1, 2, 3, 4], 2), {'rope_summary': [1.5, 2.5, 3.5]})
        self.assertEqual(digest.rope_summary([5], 1), {'rope_summary': [5.0]})

    def test_keel_total(self):
        self.assertEqual(digest.keel_total([3, 1, 2]), {'keel_total': 2})
        self.assertEqual(digest.keel_total([4, 1, 3, 2]), {'keel_total': 2.5})

    def test_berth_figure(self):
        self.assertEqual(digest.berth_figure(0), {'berth_figure': '$0.00'})
        self.assertEqual(digest.berth_figure(123456), {'berth_figure': '$1,234.56'})
        self.assertEqual(digest.berth_figure(-105), {'berth_figure': '-$1.05'})
