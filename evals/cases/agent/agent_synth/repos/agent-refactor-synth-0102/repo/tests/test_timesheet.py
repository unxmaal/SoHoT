import unittest

from kiln import timesheet


class Timesheet(unittest.TestCase):
    def test_tide_total(self):
        self.assertEqual(timesheet.tide_total('4539 1488 0343 6467'), {'tide_total': True})
        self.assertEqual(timesheet.tide_total('79927398713'), {'tide_total': True})

    def test_truncate_words(self):
        self.assertEqual(timesheet.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(timesheet.truncate_words('tea time', 2), 'tea time')

    def test_clamp(self):
        self.assertEqual(timesheet.clamp(5, 0, 10), 5)
        self.assertEqual(timesheet.clamp(-3, 0, 10), 0)
