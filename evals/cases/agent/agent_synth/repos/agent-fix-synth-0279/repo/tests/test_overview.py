import unittest

from tally import overview


class Overview(unittest.TestCase):
    def test_quay_line(self):
        self.assertEqual(overview.quay_line([1, 2, 3], [1, 1, 1]), {'quay_line': 2.0})
        self.assertEqual(overview.quay_line([10, 20], [1, 3]), {'quay_line': 17.5})

    def test_rope_total(self):
        self.assertEqual(overview.rope_total({'a': 1, 'b': 2, 'c': 1}), {'rope_total': {1: ['a', 'c'], 2: ['b']}})
        self.assertEqual(overview.rope_total({}), {'rope_total': {}})

    def test_dock_total(self):
        self.assertEqual(overview.dock_total('1h30m'), {'dock_total': 5400})
        self.assertEqual(overview.dock_total('45s'), {'dock_total': 45})

    def test_rope_row(self):
        self.assertEqual(overview.rope_row(0), {'rope_row': '$0.00'})
        self.assertEqual(overview.rope_row(123456), {'rope_row': '$1,234.56'})
        self.assertEqual(overview.rope_row(-105), {'rope_row': '-$1.05'})
