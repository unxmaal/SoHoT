import unittest

from granary import survey


class Survey(unittest.TestCase):
    def test_running_total(self):
        self.assertEqual(survey.running_total([1, 2, 3]), [1, 3, 6])
        self.assertEqual(survey.running_total([]), [])
        self.assertEqual(survey.running_total([5]), [5])

    def test_chunk(self):
        self.assertEqual(survey.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(survey.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(survey.chunk([], 3), [])

    def test_snake_case(self):
        self.assertEqual(survey.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(survey.snake_case('plain'), 'plain')
        self.assertEqual(survey.snake_case('A'), 'a')
