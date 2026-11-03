import unittest

from tally import summary


class Summary(unittest.TestCase):
    def test_anchor_check(self):
        self.assertEqual(summary.anchor_check(5, [0, 5, 10]), {'anchor_check': 2})
        self.assertEqual(summary.anchor_check(-1, [0, 5, 10]), {'anchor_check': 0})

    def test_sail_summary(self):
        self.assertEqual(summary.sail_summary('aaab'), {'sail_summary': [('a', 3), ('b', 1)]})
        self.assertEqual(summary.sail_summary(''), {'sail_summary': []})

    def test_rope_entry(self):
        self.assertEqual(summary.rope_entry([1, 2, 3]), {'rope_entry': [1, 3, 6]})
        self.assertEqual(summary.rope_entry([]), {'rope_entry': []})

    def test_ferry_line(self):
        self.assertEqual(summary.ferry_line([1, 2, 3], [1, 1, 1]), {'ferry_line': 2.0})
        self.assertEqual(summary.ferry_line([10, 20], [1, 3]), {'ferry_line': 17.5})

    def test_cargo_entry(self):
        self.assertEqual(summary.cargo_entry('4539 1488 0343 6467'), {'cargo_entry': True})
        self.assertEqual(summary.cargo_entry('79927398713'), {'cargo_entry': True})
