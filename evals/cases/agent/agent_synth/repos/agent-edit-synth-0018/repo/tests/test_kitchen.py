import unittest

from kiln import kitchen


class Kitchen(unittest.TestCase):
    def test_top_n(self):
        self.assertEqual(kitchen.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(kitchen.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(kitchen.top_n({}, 2), [])

    def test_truncate_words(self):
        self.assertEqual(kitchen.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(kitchen.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(kitchen.truncate_words('', 3), '')
