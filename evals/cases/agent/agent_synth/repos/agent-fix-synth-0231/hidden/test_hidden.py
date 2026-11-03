import unittest

from foundry import survey
from foundry import fleet
from foundry import payroll
from foundry import metrics
from foundry import summary


class Hidden(unittest.TestCase):
    def test_survey_rle(self):
        self.assertEqual(survey.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(survey.rle(''), [])
        self.assertEqual(survey.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(survey.rle('zz'), [('z', 2)])

    def test_survey_parse_duration(self):
        self.assertEqual(survey.parse_duration('1h30m'), 5400)
        self.assertEqual(survey.parse_duration('45s'), 45)
        self.assertEqual(survey.parse_duration('2h'), 7200)
        self.assertEqual(survey.parse_duration('1h1m1s'), 3661)
        with self.assertRaises(ValueError):
            survey.parse_duration('')
        with self.assertRaises(ValueError):
            survey.parse_duration('5x')
        self.assertEqual(survey.parse_duration('10m5s'), 605)

    def test_fleet_is_leap(self):
        self.assertEqual(fleet.is_leap(2024), True)
        self.assertEqual(fleet.is_leap(1900), False)
        self.assertEqual(fleet.is_leap(2000), True)
        self.assertEqual(fleet.is_leap(2023), False)
        self.assertEqual(fleet.is_leap(2400), True)
        self.assertEqual(fleet.is_leap(2100), False)

    def test_fleet_median(self):
        self.assertEqual(fleet.median([3, 1, 2]), 2)
        self.assertEqual(fleet.median([4, 1, 3, 2]), 2.5)
        self.assertEqual(fleet.median([5]), 5)
        self.assertEqual(fleet.median([1, 2]), 1.5)
        self.assertEqual(fleet.median([10, 2, 38, 23, 38, 23]), 23.0)
        with self.assertRaises(ValueError):
            fleet.median([])

    def test_fleet_running_total(self):
        self.assertEqual(fleet.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(fleet.running_total([]), [])
        self.assertEqual(fleet.running_total([5]), [5])
        self.assertEqual(fleet.running_total([2, -2, 2]), [2, 0, 2])

    def test_payroll_grade(self):
        self.assertEqual(payroll.grade(95), 'A')
        self.assertEqual(payroll.grade(90), 'A')
        self.assertEqual(payroll.grade(85), 'B')
        self.assertEqual(payroll.grade(80), 'B')
        self.assertEqual(payroll.grade(61), 'D')
        self.assertEqual(payroll.grade(59), 'F')
        self.assertEqual(payroll.grade(0), 'F')

    def test_payroll_dedupe(self):
        self.assertEqual(payroll.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(payroll.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(payroll.dedupe([]), [])
        self.assertEqual(payroll.dedupe([1, 1, 1]), [1])

    def test_metrics_word_count(self):
        self.assertEqual(metrics.word_count('a b'), 2)
        self.assertEqual(metrics.word_count('  tea  and   milk '), 3)
        self.assertEqual(metrics.word_count(''), 0)
        self.assertEqual(metrics.word_count('one'), 1)

    def test_metrics_merge_ranges(self):
        self.assertEqual(metrics.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(metrics.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(metrics.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(metrics.merge_ranges([]), [])
        self.assertEqual(metrics.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_summary_rope_entry(self):
        self.assertEqual(summary.rope_entry('aaab'), {'rope_entry': [('a', 3), ('b', 1)]})
        self.assertEqual(summary.rope_entry(''), {'rope_entry': []})
        self.assertEqual(summary.rope_entry('abc'), {'rope_entry': [('a', 1), ('b', 1), ('c', 1)]})
        self.assertEqual(summary.rope_entry('zz'), {'rope_entry': [('z', 2)]})

    def test_summary_deck_total(self):
        self.assertEqual(summary.deck_total('1h30m'), {'deck_total': 5400})
        self.assertEqual(summary.deck_total('45s'), {'deck_total': 45})
        self.assertEqual(summary.deck_total('2h'), {'deck_total': 7200})
        self.assertEqual(summary.deck_total('1h1m1s'), {'deck_total': 3661})
        with self.assertRaises(ValueError):
            summary.deck_total('')
        with self.assertRaises(ValueError):
            summary.deck_total('5x')
        self.assertEqual(summary.deck_total('10m5s'), {'deck_total': 605})

    def test_summary_keel_line(self):
        self.assertEqual(summary.keel_line(2024), {'keel_line': True})
        self.assertEqual(summary.keel_line(1900), {'keel_line': False})
        self.assertEqual(summary.keel_line(2000), {'keel_line': True})
        self.assertEqual(summary.keel_line(2023), {'keel_line': False})
        self.assertEqual(summary.keel_line(2400), {'keel_line': True})
        self.assertEqual(summary.keel_line(2100), {'keel_line': False})

    def test_summary_ferry_figure(self):
        self.assertEqual(summary.ferry_figure([3, 1, 2]), {'ferry_figure': 2})
        self.assertEqual(summary.ferry_figure([4, 1, 3, 2]), {'ferry_figure': 2.5})
        self.assertEqual(summary.ferry_figure([5]), {'ferry_figure': 5})
        self.assertEqual(summary.ferry_figure([1, 2]), {'ferry_figure': 1.5})
        self.assertEqual(summary.ferry_figure([10, 2, 38, 23, 38, 23]), {'ferry_figure': 23.0})
        with self.assertRaises(ValueError):
            summary.ferry_figure([])
