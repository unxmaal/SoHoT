import unittest

from depot import payroll
from depot import sensors
from depot import budget
from depot import survey


class Hidden(unittest.TestCase):
    def test_payroll_bucket(self):
        self.assertEqual(payroll.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(payroll.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(payroll.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(payroll.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(payroll.bucket(7, []), 0)

    def test_payroll_merge_ranges(self):
        self.assertEqual(payroll.merge_ranges([(1, 3), (3, 5)]), [(1, 5)])
        self.assertEqual(payroll.merge_ranges([(5, 6), (1, 2)]), [(1, 2), (5, 6)])
        self.assertEqual(payroll.merge_ranges([(1, 10), (2, 3)]), [(1, 10)])
        self.assertEqual(payroll.merge_ranges([]), [])
        self.assertEqual(payroll.merge_ranges([(4, 8), (1, 5)]), [(1, 8)])

    def test_sensors_percent_change(self):
        self.assertEqual(sensors.percent_change(50, 75), 50.0)
        self.assertEqual(sensors.percent_change(200, 150), -25.0)
        self.assertEqual(sensors.percent_change(80, 80), 0.0)
        self.assertEqual(sensors.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            sensors.percent_change(0, 5)
        self.assertEqual(sensors.percent_change(-10, -5), -50.0)

    def test_sensors_snake_case(self):
        self.assertEqual(sensors.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(sensors.snake_case('plain'), 'plain')
        self.assertEqual(sensors.snake_case('A'), 'a')
        self.assertEqual(sensors.snake_case('ShipToCity'), 'ship_to_city')

    def test_sensors_running_total(self):
        self.assertEqual(sensors.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(sensors.running_total([]), [])
        self.assertEqual(sensors.running_total([5]), [5])
        self.assertEqual(sensors.running_total([2, -2, 2]), [2, 0, 2])

    def test_budget_truncate_words(self):
        self.assertEqual(budget.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(budget.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(budget.truncate_words('', 3), '')
        self.assertEqual(budget.truncate_words('one two three', 1), 'one...')

    def test_budget_word_count(self):
        self.assertEqual(budget.word_count('a b'), 2)
        self.assertEqual(budget.word_count('  tea  and   milk '), 3)
        self.assertEqual(budget.word_count(''), 0)
        self.assertEqual(budget.word_count('one'), 1)

    def test_survey_clamp(self):
        self.assertEqual(survey.clamp(5, 0, 10), 5)
        self.assertEqual(survey.clamp(-3, 0, 10), 0)
        self.assertEqual(survey.clamp(15, 0, 10), 10)
        self.assertEqual(survey.clamp(10, 0, 10), 10)
        self.assertEqual(survey.clamp(0, 0, 10), 0)
        self.assertEqual(survey.clamp(7, 7, 7), 7)
        self.assertEqual(survey.clamp(-20, -30, -10), -20)

    def test_survey_dedupe(self):
        self.assertEqual(survey.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(survey.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(survey.dedupe([]), [])
        self.assertEqual(survey.dedupe([1, 1, 1]), [1])

    def test_survey_grade(self):
        self.assertEqual(survey.grade(95), 'A')
        self.assertEqual(survey.grade(90), 'A')
        self.assertEqual(survey.grade(85), 'B')
        self.assertEqual(survey.grade(80), 'B')
        self.assertEqual(survey.grade(61), 'D')
        self.assertEqual(survey.grade(59), 'F')
        self.assertEqual(survey.grade(0), 'F')

    def test_feature(self):
        self.assertEqual(payroll.merge_ranges([(1, 2), (3, 4)]), [(1, 4)])
        self.assertEqual(payroll.merge_ranges([(7, 9), (1, 6)]), [(1, 9)])
