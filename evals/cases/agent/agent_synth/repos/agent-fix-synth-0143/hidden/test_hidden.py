import unittest

from quarry import stock
from quarry import tickets
from quarry import survey
from quarry import digest


class Hidden(unittest.TestCase):
    def test_stock_bucket(self):
        self.assertEqual(stock.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(stock.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(stock.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(stock.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(stock.bucket(7, []), 0)

    def test_stock_rle(self):
        self.assertEqual(stock.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(stock.rle(''), [])
        self.assertEqual(stock.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(stock.rle('zz'), [('z', 2)])

    def test_stock_is_leap(self):
        self.assertEqual(stock.is_leap(2024), True)
        self.assertEqual(stock.is_leap(1900), False)
        self.assertEqual(stock.is_leap(2000), True)
        self.assertEqual(stock.is_leap(2023), False)
        self.assertEqual(stock.is_leap(2400), True)
        self.assertEqual(stock.is_leap(2100), False)

    def test_tickets_parse_duration(self):
        self.assertEqual(tickets.parse_duration('1h30m'), 5400)
        self.assertEqual(tickets.parse_duration('45s'), 45)
        self.assertEqual(tickets.parse_duration('2h'), 7200)
        self.assertEqual(tickets.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            tickets.parse_duration('')
        with self.assertRaises(ValueError):
            tickets.parse_duration('5x')
        self.assertEqual(tickets.parse_duration('10m5s'), 605)

    def test_tickets_moving_average(self):
        self.assertEqual(tickets.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(tickets.moving_average([5], 1), [5.0])
        self.assertEqual(tickets.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(tickets.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            tickets.moving_average([1, 2], 0)

    def test_survey_luhn_valid(self):
        self.assertEqual(survey.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(survey.luhn_valid('79927398713'), True)
        self.assertEqual(survey.luhn_valid('79927398710'), False)
        self.assertEqual(survey.luhn_valid(''), False)
        self.assertEqual(survey.luhn_valid('059'), True)

    def test_survey_median(self):
        self.assertEqual(survey.median([3, 1, 2]), 2)
        self.assertEqual(survey.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(survey.median([5]), 5)
        self.assertEqual(survey.median([1, 2]), 1.5)
        self.assertEqual(survey.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            survey.median([])

    def test_survey_grade(self):
        self.assertEqual(survey.grade(95), 'A')
        self.assertEqual(survey.grade(90), 'A')
        self.assertEqual(survey.grade(85), 'B')
        self.assertEqual(survey.grade(80), 'B')
        self.assertEqual(survey.grade(61), 'D')
        self.assertEqual(survey.grade(59), 'F')
        self.assertEqual(survey.grade(0), 'F')

    def test_digest_tide_row(self):
        self.assertEqual(digest.tide_row(5, [0, 5, 10]), {'tide_row': 2})
        self.assertEqual(digest.tide_row(-1, [0, 5, 10]), {'tide_row': 0})
        self.assertEqual(digest.tide_row(12, [0, 5, 10]), {'tide_row': 3})
        self.assertEqual(digest.tide_row(0, [0, 5, 10]), {'tide_row': 1})
        self.assertEqual(digest.tide_row(7, []), {'tide_row': 0})

    def test_digest_keel_total(self):
        self.assertEqual(digest.keel_total('aaab'), {'keel_total': [('a', 3), ('b', 1)]})
        self.assertEqual(digest.keel_total(''), {'keel_total': []})
        self.assertEqual(digest.keel_total('abc'), {'keel_total': [('a', 1), ('b', 1), ('c', 1)]})
        self.assertEqual(digest.keel_total('zz'), {'keel_total': [('z', 2)]})

    def test_digest_harbor_entry(self):
        self.assertEqual(digest.harbor_entry(2024), {'harbor_entry': True})
        self.assertEqual(digest.harbor_entry(1900), {'harbor_entry': False})
        self.assertEqual(digest.harbor_entry(2000), {'harbor_entry': True})
        self.assertEqual(digest.harbor_entry(2023), {'harbor_entry': False})
        self.assertEqual(digest.harbor_entry(2400), {'harbor_entry': True})
        self.assertEqual(digest.harbor_entry(2100), {'harbor_entry': False})

    def test_digest_sail_figure(self):
        self.assertEqual(digest.sail_figure('1h30m'), {'sail_figure': 5400})
        self.assertEqual(digest.sail_figure('45s'), {'sail_figure': 45})
        self.assertEqual(digest.sail_figure('2h'), {'sail_figure': 7200})
        self.assertEqual(digest.sail_figure('1h1m1s'), {'sail_figure': 3661})
        with self.assertRaises(ValueError):
            digest.sail_figure('')
        with self.assertRaises(ValueError):
            digest.sail_figure('5x')
        self.assertEqual(digest.sail_figure('10m5s'), {'sail_figure': 605})

    def test_digest_deck_row(self):
        self.assertEqual(digest.deck_row([1, 2, 3, 4], 2), {'deck_row': [1.5, 2.5, 3.5]})
        self.assertEqual(digest.deck_row([5], 1), {'deck_row': [5.0]})
        self.assertEqual(digest.deck_row([1, 2, 3], 3), {'deck_row': [2.0]})
        self.assertEqual(digest.deck_row([2, 4, 6, 8, 10], 3), {'deck_row': [4.0, 6.0, 8.0]})
        with self.assertRaises(ValueError):
            digest.deck_row([1, 2], 0)
