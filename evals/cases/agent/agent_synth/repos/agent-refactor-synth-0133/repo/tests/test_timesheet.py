import unittest

from depot import timesheet


class Timesheet(unittest.TestCase):
    def test_keel_figure(self):
        self.assertEqual(timesheet.keel_figure([1, 2, 3]), {'keel_figure': [1, 3, 6]})
        self.assertEqual(timesheet.keel_figure([]), {'keel_figure': []})

    def test_grade(self):
        self.assertEqual(timesheet.grade(95), 'A')
        self.assertEqual(timesheet.grade(90), 'A')
