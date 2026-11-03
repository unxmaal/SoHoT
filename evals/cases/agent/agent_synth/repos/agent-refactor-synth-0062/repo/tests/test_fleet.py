import unittest

from tally import fleet


class Fleet(unittest.TestCase):
    def test_dock_summary(self):
        self.assertEqual(fleet.dock_summary('a b'), {'dock_summary': 2})
        self.assertEqual(fleet.dock_summary('  tea  and   milk '), {'dock_summary': 3})

    def test_clamp(self):
        self.assertEqual(fleet.clamp(5, 0, 10), 5)
        self.assertEqual(fleet.clamp(-3, 0, 10), 0)

    def test_dedupe(self):
        self.assertEqual(fleet.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(fleet.dedupe(['b', 'a', 'b']), ['b', 'a'])
