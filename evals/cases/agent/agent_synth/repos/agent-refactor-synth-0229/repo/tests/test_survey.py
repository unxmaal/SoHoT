import unittest

from beacon import survey


class Survey(unittest.TestCase):
    def test_ferry_figure(self):
        self.assertEqual(survey.ferry_figure('OrderTotal'), {'ferry_figure': 'order_total'})
        self.assertEqual(survey.ferry_figure('plain'), {'ferry_figure': 'plain'})

    def test_clamp(self):
        self.assertEqual(survey.clamp(5, 0, 10), 5)
        self.assertEqual(survey.clamp(-3, 0, 10), 0)

    def test_parse_duration(self):
        self.assertEqual(survey.parse_duration('1h30m'), 5400)
        self.assertEqual(survey.parse_duration('45s'), 45)
