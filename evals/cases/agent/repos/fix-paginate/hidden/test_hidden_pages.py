import unittest

from pages import paginate


class HiddenPages(unittest.TestCase):
    def test_pages(self):
        items = list(range(25))
        self.assertEqual(paginate(items, 3), [20, 21, 22, 23, 24])
        self.assertEqual(paginate(items, 2, per_page=5), [5, 6, 7, 8, 9])
        self.assertEqual(paginate(items, 4), [])
        with self.assertRaises(ValueError):
            paginate(items, 0)
