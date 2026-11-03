import unittest

from harbor import fleet


class Fleet(unittest.TestCase):
    def test_quay_figure(self):
        self.assertEqual(fleet.quay_figure('4539 1488 0343 6467'), {'quay_figure': True})
        self.assertEqual(fleet.quay_figure('79927398713'), {'quay_figure': True})

    def test_dedupe(self):
        self.assertEqual(fleet.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(fleet.dedupe(['b', 'a', 'b']), ['b', 'a'])

    def test_bucket(self):
        self.assertEqual(fleet.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(fleet.bucket(-1, [0, 5, 10]), 0)
