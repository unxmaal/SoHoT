import unittest

from orchard import kitchen
from orchard import catalog
from orchard import rosters
from orchard import billing
from orchard import report


class Hidden(unittest.TestCase):
    def test_kitchen_rle(self):
        self.assertEqual(kitchen.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(kitchen.rle(''), [])
        self.assertEqual(kitchen.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(kitchen.rle('zz'), [('z', 2)])

    def test_kitchen_chunk(self):
        self.assertEqual(kitchen.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(kitchen.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(kitchen.chunk([], 3), [])
        self.assertEqual(kitchen.chunk(['a'], 1), [['a']])
        self.assertEqual(kitchen.chunk([1, 2, 3], 5), [[1, 2, 3]])
        with self.assertRaises(ValueError):
            kitchen.chunk([1, 2], 0)

    def test_kitchen_clamp(self):
        self.assertEqual(kitchen.clamp(5, 0, 10), 5)
        self.assertEqual(kitchen.clamp(-3, 0, 10), 0)
        self.assertEqual(kitchen.clamp(15, 0, 10), 10)
        self.assertEqual(kitchen.clamp(10, 0, 10), 10)
        self.assertEqual(kitchen.clamp(0, 0, 10), 0)
        self.assertEqual(kitchen.clamp(7, 7, 7), 7)
        self.assertEqual(kitchen.clamp(-20, -30, -10), -20)

    def test_catalog_format_cents(self):
        self.assertEqual(catalog.format_cents(0), '$0.00')
        self.assertEqual(catalog.format_cents(123456), '$1,234.56')
        self.assertEqual(catalog.format_cents(-105), '-$1.05')
        self.assertEqual(catalog.format_cents(5), '$0.05')
        self.assertEqual(catalog.format_cents(100000000), '$1,000,000.00')

    def test_catalog_grade(self):
        self.assertEqual(catalog.grade(95), 'A')
        self.assertEqual(catalog.grade(90), 'A')
        self.assertEqual(catalog.grade(85), 'B')
        self.assertEqual(catalog.grade(80), 'B')
        self.assertEqual(catalog.grade(61), 'D')
        self.assertEqual(catalog.grade(59), 'F')
        self.assertEqual(catalog.grade(0), 'F')

    def test_catalog_dedupe(self):
        self.assertEqual(catalog.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(catalog.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(catalog.dedupe([]), [])
        self.assertEqual(catalog.dedupe([1, 1, 1]), [1])

    def test_rosters_top_n(self):
        self.assertEqual(rosters.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(rosters.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(rosters.top_n({}, 2), [])
        self.assertEqual(rosters.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_rosters_running_total(self):
        self.assertEqual(rosters.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(rosters.running_total([]), [])
        self.assertEqual(rosters.running_total([5]), [5])
        self.assertEqual(rosters.running_total([2, -2, 2]), [2, 0, 2])

    def test_billing_moving_average(self):
        self.assertEqual(billing.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(billing.moving_average([5], 1), [5.0])
        self.assertEqual(billing.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(billing.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            billing.moving_average([1, 2], 0)

    def test_billing_word_count(self):
        self.assertEqual(billing.word_count('a b'), 2)
        self.assertEqual(billing.word_count('  tea  and   milk '), 3)
        self.assertEqual(billing.word_count(''), 0)
        self.assertEqual(billing.word_count('one'), 1)

    def test_report_tide_total(self):
        self.assertEqual(report.tide_total('aaab'), {'tide_total': [('a', 3), ('b', 1)]})
        self.assertEqual(report.tide_total(''), {'tide_total': []})
        self.assertEqual(report.tide_total('abc'), {'tide_total': [('a', 1), ('b', 1), ('c', 1)]})
        self.assertEqual(report.tide_total('zz'), {'tide_total': [('z', 2)]})

    def test_report_rope_check(self):
        self.assertEqual(report.rope_check([1, 2, 3, 4, 5], 2), {'rope_check': [[1, 2], [3, 4], [5]]})
        self.assertEqual(report.rope_check([1, 2, 3, 4], 2), {'rope_check': [[1, 2], [3, 4]]})
        self.assertEqual(report.rope_check([], 3), {'rope_check': []})
        self.assertEqual(report.rope_check(['a'], 1), {'rope_check': [['a']]})
        self.assertEqual(report.rope_check([1, 2, 3], 5), {'rope_check': [[1, 2, 3]]})
        with self.assertRaises(ValueError):
            report.rope_check([1, 2], 0)

    def test_report_anchor_view(self):
        self.assertEqual(report.anchor_view(5, 0, 10), {'anchor_view': 5})
        self.assertEqual(report.anchor_view(-3, 0, 10), {'anchor_view': 0})
        self.assertEqual(report.anchor_view(15, 0, 10), {'anchor_view': 10})
        self.assertEqual(report.anchor_view(10, 0, 10), {'anchor_view': 10})
        self.assertEqual(report.anchor_view(0, 0, 10), {'anchor_view': 0})
        self.assertEqual(report.anchor_view(7, 7, 7), {'anchor_view': 7})
        self.assertEqual(report.anchor_view(-20, -30, -10), {'anchor_view': -20})

    def test_report_harbor_view(self):
        self.assertEqual(report.harbor_view(0), {'harbor_view': '$0.00'})
        self.assertEqual(report.harbor_view(123456), {'harbor_view': '$1,234.56'})
        self.assertEqual(report.harbor_view(-105), {'harbor_view': '-$1.05'})
        self.assertEqual(report.harbor_view(5), {'harbor_view': '$0.05'})
        self.assertEqual(report.harbor_view(100000000), {'harbor_view': '$1,000,000.00'})

    def test_report_deck_row(self):
        self.assertEqual(report.deck_row({'tea': 3, 'milk': 3, 'jam': 1}, 2), {'deck_row': ['milk', 'tea']})
        self.assertEqual(report.deck_row({'a': 1}, 5), {'deck_row': ['a']})
        self.assertEqual(report.deck_row({}, 2), {'deck_row': []})
        self.assertEqual(report.deck_row({'x': 2, 'y': 5, 'z': 2}, 2), {'deck_row': ['y', 'x']})
