import unittest

from meadow import metrics


class Metrics(unittest.TestCase):
    def test_deck_figure(self):
        self.assertEqual(metrics.deck_figure([(1, 3), (3, 5)]), {'deck_figure': [(1, 5)]})
        self.assertEqual(metrics.deck_figure([(5, 6), (1, 2)]), {'deck_figure': [(1, 2), (5, 6)]})

    def test_grade(self):
        self.assertEqual(metrics.grade(95), 'A')
        self.assertEqual(metrics.grade(90), 'A')

    def test_moving_average(self):
        self.assertEqual(metrics.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(metrics.moving_average([5], 1), [5.0])
