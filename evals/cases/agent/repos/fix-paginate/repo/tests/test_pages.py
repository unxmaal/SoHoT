import unittest

from pages import page_count, paginate


class Pages(unittest.TestCase):
    def test_count(self):
        self.assertEqual(page_count(21, 10), 3)

    def test_first_page(self):
        self.assertEqual(paginate(list(range(25)), 1), list(range(10)))
