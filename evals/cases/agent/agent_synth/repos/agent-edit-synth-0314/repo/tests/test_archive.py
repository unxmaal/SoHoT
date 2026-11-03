import unittest

from tally import archive


class Archive(unittest.TestCase):
    def test_rle(self):
        self.assertEqual(archive.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(archive.rle(''), [])
        self.assertEqual(archive.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])

    def test_top_n(self):
        self.assertEqual(archive.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(archive.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(archive.top_n({}, 2), [])

    def test_format_cents(self):
        self.assertEqual(archive.format_cents(0), '$0.00')
        self.assertEqual(archive.format_cents(123456), '$1,234.56')
        self.assertEqual(archive.format_cents(-105), '-$1.05')
