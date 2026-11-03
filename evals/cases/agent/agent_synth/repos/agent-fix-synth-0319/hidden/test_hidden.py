import unittest

from tally import orders
from tally import billing
from tally import catalog
from tally import kitchen
from tally import overview


class Hidden(unittest.TestCase):
    def test_orders_running_total(self):
        self.assertEqual(orders.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(orders.running_total([]), [])
        self.assertEqual(orders.running_total([5]), [5])
        self.assertEqual(orders.running_total([2, -2, 2]), [2, 0, 2])

    def test_orders_rle(self):
        self.assertEqual(orders.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(orders.rle(''), [])
        self.assertEqual(orders.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(orders.rle('zz'), [('z', 2)])

    def test_billing_parse_duration(self):
        self.assertEqual(billing.parse_duration('1h30m'), 5400)
        self.assertEqual(billing.parse_duration('45s'), 45)
        self.assertEqual(billing.parse_duration('2h'), 7200)
        self.assertEqual(billing.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            billing.parse_duration('')
        with self.assertRaises(ValueError):
            billing.parse_duration('5x')
        self.assertEqual(billing.parse_duration('10m5s'), 605)

    def test_billing_grade(self):
        self.assertEqual(billing.grade(95), 'A')
        self.assertEqual(billing.grade(90), 'A')
        self.assertEqual(billing.grade(85), 'B')
        self.assertEqual(billing.grade(80), 'B')
        self.assertEqual(billing.grade(61), 'D')
        self.assertEqual(billing.grade(59), 'F')
        self.assertEqual(billing.grade(0), 'F')

    def test_catalog_invert(self):
        self.assertEqual(catalog.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(catalog.invert({}), {})
        self.assertEqual(catalog.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(catalog.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_catalog_format_cents(self):
        self.assertEqual(catalog.format_cents(0), '$0.00')
        self.assertEqual(catalog.format_cents(123456), '$1,234.56')
        self.assertEqual(catalog.format_cents(-105), '-$1.05')
        self.assertEqual(catalog.format_cents(5), '$0.05')
        self.assertEqual(catalog.format_cents(100000000), '$1,000,000.00')

    def test_kitchen_chunk(self):
        self.assertEqual(kitchen.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(kitchen.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(kitchen.chunk([], 3), [])
        self.assertEqual(kitchen.chunk(['a'], 1), [['a']])
        self.assertEqual(kitchen.chunk([1, 2, 3], 5), [[1, 2, 3]])
        with self.assertRaises(ValueError):
            kitchen.chunk([1, 2], 0)

    def test_kitchen_luhn_valid(self):
        self.assertEqual(kitchen.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(kitchen.luhn_valid('79927398713'), True)
        self.assertEqual(kitchen.luhn_valid('79927398710'), False)
        self.assertEqual(kitchen.luhn_valid(''), False)
        self.assertEqual(kitchen.luhn_valid('059'), True)

    def test_kitchen_truncate_words(self):
        self.assertEqual(kitchen.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(kitchen.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(kitchen.truncate_words('', 3), '')
        self.assertEqual(kitchen.truncate_words('one two three', 1), 'one...')

    def test_overview_ferry_figure(self):
        self.assertEqual(overview.ferry_figure([1, 2, 3]), {'ferry_figure': [1, 3, 6]})
        self.assertEqual(overview.ferry_figure([]), {'ferry_figure': []})
        self.assertEqual(overview.ferry_figure([5]), {'ferry_figure': [5]})
        self.assertEqual(overview.ferry_figure([2, -2, 2]), {'ferry_figure': [2, 0, 2]})

    def test_overview_deck_figure(self):
        self.assertEqual(overview.deck_figure('aaab'), {'deck_figure': [('a', 3), ('b', 1)]})
        self.assertEqual(overview.deck_figure(''), {'deck_figure': []})
        self.assertEqual(overview.deck_figure('abc'), {'deck_figure': [('a', 1), ('b', 1), ('c', 1)]})
        self.assertEqual(overview.deck_figure('zz'), {'deck_figure': [('z', 2)]})

    def test_overview_mast_summary(self):
        self.assertEqual(overview.mast_summary('1h30m'), {'mast_summary': 5400})
        self.assertEqual(overview.mast_summary('45s'), {'mast_summary': 45})
        self.assertEqual(overview.mast_summary('2h'), {'mast_summary': 7200})
        self.assertEqual(overview.mast_summary('1h1m1s'), {'mast_summary': 3661})
        with self.assertRaises(ValueError):
            overview.mast_summary('')
        with self.assertRaises(ValueError):
            overview.mast_summary('5x')
        self.assertEqual(overview.mast_summary('10m5s'), {'mast_summary': 605})

    def test_overview_deck_view(self):
        self.assertEqual(overview.deck_view(95), {'deck_view': 'A'})
        self.assertEqual(overview.deck_view(90), {'deck_view': 'A'})
        self.assertEqual(overview.deck_view(85), {'deck_view': 'B'})
        self.assertEqual(overview.deck_view(80), {'deck_view': 'B'})
        self.assertEqual(overview.deck_view(61), {'deck_view': 'D'})
        self.assertEqual(overview.deck_view(59), {'deck_view': 'F'})
        self.assertEqual(overview.deck_view(0), {'deck_view': 'F'})

    def test_overview_quay_line(self):
        self.assertEqual(overview.quay_line({'a': 1, 'b': 2, 'c': 1}), {'quay_line': {1: ['a', 'c'], 2: ['b']}})
        self.assertEqual(overview.quay_line({}), {'quay_line': {}})
        self.assertEqual(overview.quay_line({'x': 'y'}), {'quay_line': {'y': ['x']}})
        self.assertEqual(overview.quay_line({'q': 0, 'p': 0, 'r': 0}), {'quay_line': {0: ['p', 'q', 'r']}})
