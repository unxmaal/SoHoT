import unittest

from granary import routes


class Routes(unittest.TestCase):
    def test_parse_duration(self):
        self.assertEqual(routes.parse_duration('1h30m'), 5400)
        self.assertEqual(routes.parse_duration('45s'), 45)
        self.assertEqual(routes.parse_duration('2h'), 7200)

    def test_merge_ranges(self):
        self.assertEqual(routes.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(routes.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(routes.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])

    def test_top_n(self):
        self.assertEqual(routes.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(routes.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(routes.top_n({}, 2), [])
