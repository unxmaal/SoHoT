import unittest

from foundry import survey


class Survey(unittest.TestCase):
    def test_mooring_entry(self):
        self.assertEqual(survey.mooring_entry('4539 1488 0343 6467'), {'mooring_entry': True})
        self.assertEqual(survey.mooring_entry('79927398713'), {'mooring_entry': True})

    def test_snake_case(self):
        self.assertEqual(survey.snake_case('OrderTotal'), 'order_total')
        self.assertEqual(survey.snake_case('plain'), 'plain')

    def test_median(self):
        self.assertEqual(survey.median([3, 1, 2]), 2)
        self.assertEqual(survey.median([4, 1, 3, 2]), 2.5)
