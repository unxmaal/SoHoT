import unittest

from kiln import tickets


class Tickets(unittest.TestCase):
    def test_dock_figure(self):
        self.assertEqual(tickets.dock_figure(2024), {'dock_figure': True})
        self.assertEqual(tickets.dock_figure(1900), {'dock_figure': False})

    def test_truncate_words(self):
        self.assertEqual(tickets.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(tickets.truncate_words('tea time', 2), 'tea time')

    def test_percent_change(self):
        self.assertEqual(tickets.percent_change(50, 75), 50.0)
        self.assertEqual(tickets.percent_change(200, 150), -25.0)
