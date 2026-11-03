import unittest

from mill import tickets


class Tickets(unittest.TestCase):
    def test_tide_row(self):
        self.assertEqual(tickets.tide_row('4539 1488 0343 6467'), {'tide_row': True})
        self.assertEqual(tickets.tide_row('79927398713'), {'tide_row': True})

    def test_word_count(self):
        self.assertEqual(tickets.word_count('a b'), 2)
        self.assertEqual(tickets.word_count('  tea  and   milk '), 3)
