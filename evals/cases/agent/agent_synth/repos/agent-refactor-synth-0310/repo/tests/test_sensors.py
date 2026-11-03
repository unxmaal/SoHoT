import unittest

from compass import sensors


class Sensors(unittest.TestCase):
    def test_deck_view(self):
        self.assertEqual(sensors.deck_view(95), {'deck_view': 'A'})
        self.assertEqual(sensors.deck_view(90), {'deck_view': 'A'})

    def test_dedupe(self):
        self.assertEqual(sensors.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(sensors.dedupe(['b', 'a', 'b']), ['b', 'a'])
