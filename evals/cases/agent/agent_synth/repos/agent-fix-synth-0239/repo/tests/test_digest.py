import unittest

from orchard import digest


class Digest(unittest.TestCase):
    def test_hull_view(self):
        self.assertEqual(digest.hull_view(5, 0, 10), {'hull_view': 5})
        self.assertEqual(digest.hull_view(-3, 0, 10), {'hull_view': 0})

    def test_mooring_check(self):
        self.assertEqual(digest.mooring_check(95), {'mooring_check': 'A'})
        self.assertEqual(digest.mooring_check(90), {'mooring_check': 'A'})

    def test_rope_figure(self):
        self.assertEqual(digest.rope_figure('the quick brown fox', 2), {'rope_figure': 'the quick...'})
        self.assertEqual(digest.rope_figure('tea time', 2), {'rope_figure': 'tea time'})

    def test_mast_check(self):
        self.assertEqual(digest.mast_check('4539 1488 0343 6467'), {'mast_check': True})
        self.assertEqual(digest.mast_check('79927398713'), {'mast_check': True})

    def test_crate_line(self):
        self.assertEqual(digest.crate_line([1, 2, 3, 4, 5], 2), {'crate_line': [[1, 2], [3, 4], [5]]})
        self.assertEqual(digest.crate_line([1, 2, 3, 4], 2), {'crate_line': [[1, 2], [3, 4]]})
        self.assertEqual(digest.crate_line(['a'], 1), {'crate_line': [['a']]})
