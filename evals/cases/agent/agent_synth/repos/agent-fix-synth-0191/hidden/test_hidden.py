import unittest

from atlas import shipping
from atlas import fleet
from atlas import archive
from atlas import catalog
from atlas import dashboard


class Hidden(unittest.TestCase):
    def test_shipping_format_cents(self):
        self.assertEqual(shipping.format_cents(0), '$0.00')
        self.assertEqual(shipping.format_cents(123456), '$1,234.56')
        self.assertEqual(shipping.format_cents(-105), '-$1.05')
        self.assertEqual(shipping.format_cents(5), '$0.05')
        self.assertEqual(shipping.format_cents(100000000), '$1,000,000.00')

    def test_shipping_chunk(self):
        self.assertEqual(shipping.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(shipping.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(shipping.chunk([], 3), [])
        self.assertEqual(shipping.chunk(['a'], 1), [['a']])
        self.assertEqual(shipping.chunk([1, 2, 3], 5), [[1, 2, 3]])
        with self.assertRaises(ValueError):
            shipping.chunk([1, 2], 0)

    def test_shipping_bucket(self):
        self.assertEqual(shipping.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(shipping.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(shipping.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(shipping.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(shipping.bucket(7, []), 0)

    def test_fleet_dedupe(self):
        self.assertEqual(fleet.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(fleet.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(fleet.dedupe([]), [])
        self.assertEqual(fleet.dedupe([1, 1, 1]), [1])

    def test_fleet_parse_duration(self):
        self.assertEqual(fleet.parse_duration('1h30m'), 5400)
        self.assertEqual(fleet.parse_duration('45s'), 45)
        self.assertEqual(fleet.parse_duration('2h'), 7200)
        self.assertEqual(fleet.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            fleet.parse_duration('')
        with self.assertRaises(ValueError):
            fleet.parse_duration('5x')
        self.assertEqual(fleet.parse_duration('10m5s'), 605)

    def test_archive_weighted_mean(self):
        self.assertEqual(archive.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(archive.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(archive.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            archive.weighted_mean([5, 5], [0, 0])
        self.assertEqual(archive.weighted_mean([1, 2], [0.5, 1.5]), 1.75)

    def test_archive_rle(self):
        self.assertEqual(archive.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(archive.rle(''), [])
        self.assertEqual(archive.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(archive.rle('zz'), [('z', 2)])

    def test_catalog_word_count(self):
        self.assertEqual(catalog.word_count('a b'), 2)
        self.assertEqual(catalog.word_count('  tea  and   milk '), 3)
        self.assertEqual(catalog.word_count(''), 0)
        self.assertEqual(catalog.word_count('one'), 1)

    def test_catalog_invert(self):
        self.assertEqual(catalog.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(catalog.invert({}), {})
        self.assertEqual(catalog.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(catalog.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_dashboard_lantern_line(self):
        self.assertEqual(dashboard.lantern_line(0), {'lantern_line': '$0.00'})
        self.assertEqual(dashboard.lantern_line(123456), {'lantern_line': '$1,234.56'})
        self.assertEqual(dashboard.lantern_line(-105), {'lantern_line': '-$1.05'})
        self.assertEqual(dashboard.lantern_line(5), {'lantern_line': '$0.05'})
        self.assertEqual(dashboard.lantern_line(100000000), {'lantern_line': '$1,000,000.00'})

    def test_dashboard_tide_figure(self):
        self.assertEqual(dashboard.tide_figure([1, 2, 3, 4, 5], 2), {'tide_figure': [[1, 2], [3, 4], [5]]})
        self.assertEqual(dashboard.tide_figure([1, 2, 3, 4], 2), {'tide_figure': [[1, 2], [3, 4]]})
        self.assertEqual(dashboard.tide_figure([], 3), {'tide_figure': []})
        self.assertEqual(dashboard.tide_figure(['a'], 1), {'tide_figure': [['a']]})
        self.assertEqual(dashboard.tide_figure([1, 2, 3], 5), {'tide_figure': [[1, 2, 3]]})
        with self.assertRaises(ValueError):
            dashboard.tide_figure([1, 2], 0)

    def test_dashboard_cargo_view(self):
        self.assertEqual(dashboard.cargo_view(5, [0, 5, 10]), {'cargo_view': 2})
        self.assertEqual(dashboard.cargo_view(-1, [0, 5, 10]), {'cargo_view': 0})
        self.assertEqual(dashboard.cargo_view(12, [0, 5, 10]), {'cargo_view': 3})
        self.assertEqual(dashboard.cargo_view(0, [0, 5, 10]), {'cargo_view': 1})
        self.assertEqual(dashboard.cargo_view(7, []), {'cargo_view': 0})

    def test_dashboard_lantern_total(self):
        self.assertEqual(dashboard.lantern_total([3, 1, 3, 2, 1]), {'lantern_total': [3, 1, 2]})
        self.assertEqual(dashboard.lantern_total(['b', 'a', 'b']), {'lantern_total': ['b', 'a']})
        self.assertEqual(dashboard.lantern_total([]), {'lantern_total': []})
        self.assertEqual(dashboard.lantern_total([1, 1, 1]), {'lantern_total': [1]})

    def test_dashboard_hull_row(self):
        self.assertEqual(dashboard.hull_row({'a': 1, 'b': 2, 'c': 1}), {'hull_row': {1: ['a', 'c'], 2: ['b']}})
        self.assertEqual(dashboard.hull_row({}), {'hull_row': {}})
        self.assertEqual(dashboard.hull_row({'x': 'y'}), {'hull_row': {'y': ['x']}})
        self.assertEqual(dashboard.hull_row({'q': 0, 'p': 0, 'r': 0}), {'hull_row': {0: ['p', 'q', 'r']}})
