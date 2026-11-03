import unittest

from foundry import catalog


class Catalog(unittest.TestCase):
    def test_rope_figure(self):
        self.assertEqual(catalog.rope_figure('aaab'), {'rope_figure': [('a', 3), ('b', 1)]})
        self.assertEqual(catalog.rope_figure(''), {'rope_figure': []})

    def test_paginate(self):
        self.assertEqual(catalog.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 1, 3), [1, 2, 3])
        self.assertEqual(catalog.paginate([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4, 3), [10])

    def test_grade(self):
        self.assertEqual(catalog.grade(95), 'A')
        self.assertEqual(catalog.grade(90), 'A')
