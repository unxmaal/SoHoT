import unittest

from kiln import timesheet


class Timesheet(unittest.TestCase):
    def test_deck_figure(self):
        self.assertEqual(timesheet.deck_figure('the quick brown fox', 2), {'deck_figure': 'the quick...'})
        self.assertEqual(timesheet.deck_figure('tea time', 2), {'deck_figure': 'tea time'})

    def test_snake_case(self):
        self.assertEqual(timesheet.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(timesheet.snake_case('plain'), 'plain')

    def test_clamp(self):
        self.assertEqual(timesheet.clamp(5, 0, 10), 5)
        self.assertEqual(timesheet.clamp(-3, 0, 10), 0)
