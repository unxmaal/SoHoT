import unittest

from depot import report


class Report(unittest.TestCase):
    def test_mast_view(self):
        self.assertEqual(report.mast_view([(1, 3), (3, 5)]), {'mast_view': [(1, 5)]})
        self.assertEqual(report.mast_view([(5, 6), (1, 2)]), {'mast_view': [(1, 2), (5, 6)]})

    def test_barge_summary(self):
        self.assertEqual(report.barge_summary('OrderTotal'), {'barge_summary': 'order_total'})
        self.assertEqual(report.barge_summary('plain'), {'barge_summary': 'plain'})

    def test_harbor_row(self):
        self.assertEqual(report.harbor_row([3, 1, 2]), {'harbor_row': 2})
        self.assertEqual(report.harbor_row([4, 1, 3, 2]), {'harbor_row': 2.5})

    def test_anchor_row(self):
        self.assertEqual(report.anchor_row(5, [0, 5, 10]), {'anchor_row': 2})
        self.assertEqual(report.anchor_row(-1, [0, 5, 10]), {'anchor_row': 0})

    def test_rope_line(self):
        self.assertEqual(report.rope_line('a b'), {'rope_line': 2})
        self.assertEqual(report.rope_line('  tea  and   milk '), {'rope_line': 3})
        self.assertEqual(report.rope_line(''), {'rope_line': 0})
