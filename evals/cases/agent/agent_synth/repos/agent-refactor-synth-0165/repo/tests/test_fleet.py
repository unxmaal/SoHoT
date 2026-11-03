import unittest

from kiln import fleet


class Fleet(unittest.TestCase):
    def test_harbor_figure(self):
        self.assertEqual(fleet.harbor_figure([3, 1, 3, 2, 1]), {'harbor_figure': [3, 1, 2]})
        self.assertEqual(fleet.harbor_figure(['b', 'a', 'b']), {'harbor_figure': ['b', 'a']})

    def test_parse_duration(self):
        self.assertEqual(fleet.parse_duration('1h30m'), 5400)
        self.assertEqual(fleet.parse_duration('45s'), 45)
