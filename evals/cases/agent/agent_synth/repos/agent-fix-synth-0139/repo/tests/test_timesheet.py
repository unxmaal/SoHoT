import unittest

from compass import timesheet


class Timesheet(unittest.TestCase):
    def test_truncate_words(self):
        self.assertEqual(timesheet.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(timesheet.truncate_words('tea time', 2), 'tea time')

    def test_luhn_valid(self):
        self.assertEqual(timesheet.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(timesheet.luhn_valid('79927398713'), True)

    def test_dedupe(self):
        self.assertEqual(timesheet.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(timesheet.dedupe(['b', 'a', 'b']), ['b', 'a'])
