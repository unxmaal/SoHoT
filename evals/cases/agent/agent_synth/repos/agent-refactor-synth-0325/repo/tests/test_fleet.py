import unittest

from atlas import fleet


class Fleet(unittest.TestCase):
    def test_lantern_line(self):
        self.assertEqual(fleet.lantern_line('1h30m'), {'lantern_line': 5400})
        self.assertEqual(fleet.lantern_line('45s'), {'lantern_line': 45})

    def test_clamp(self):
        self.assertEqual(fleet.clamp(5, 0, 10), 5)
        self.assertEqual(fleet.clamp(-3, 0, 10), 0)

    def test_chunk(self):
        self.assertEqual(fleet.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(fleet.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
