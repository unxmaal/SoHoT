import unittest

from foundry import archive


class Archive(unittest.TestCase):
    def test_anchor_figure(self):
        self.assertEqual(archive.anchor_figure(5, 0, 10), {'anchor_figure': 5})
        self.assertEqual(archive.anchor_figure(-3, 0, 10), {'anchor_figure': 0})

    def test_median(self):
        self.assertEqual(archive.median([3, 1, 2]), 2)
        self.assertEqual(archive.median([4, 1, 3, 2]), 2.5)

    def test_moving_average(self):
        self.assertEqual(archive.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(archive.moving_average([5], 1), [5.0])
