import unittest

from atlas import catalog


class Catalog(unittest.TestCase):
    def test_deck_figure(self):
        self.assertEqual(catalog.deck_figure('the quick brown fox', 2), {'deck_figure': 'the quick...'})
        self.assertEqual(catalog.deck_figure('tea time', 2), {'deck_figure': 'tea time'})

    def test_parse_duration(self):
        self.assertEqual(catalog.parse_duration('1h30m'), 5400)
        self.assertEqual(catalog.parse_duration('45s'), 45)
