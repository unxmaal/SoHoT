import unittest

from lantern import sensors
from lantern import pricing
from lantern import billing
from lantern import metrics
from lantern import archive


class Hidden(unittest.TestCase):
    def test_sensors_rle(self):
        self.assertEqual(sensors.rle('aaab'), [('a', 3), ('b', 1)])
        self.assertEqual(sensors.rle(''), [])
        self.assertEqual(sensors.rle('abc'), [('a', 1), ('b', 1), ('c', 1)])
        self.assertEqual(sensors.rle('zz'), [('z', 2)])

    def test_sensors_percent_change(self):
        self.assertEqual(sensors.percent_change(50, 75), 50.0)
        self.assertEqual(sensors.percent_change(200, 150), -25.0)
        self.assertEqual(sensors.percent_change(80, 80), 0.0)
        self.assertEqual(sensors.percent_change(3, 4), 33.33)
        with self.assertRaises(ValueError):
            sensors.percent_change(0, 5)
        self.assertEqual(sensors.percent_change(-10, -5), -50.0)

    def test_pricing_chunk(self):
        self.assertEqual(pricing.chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
        self.assertEqual(pricing.chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
        self.assertEqual(pricing.chunk([], 3), [])
        self.assertEqual(pricing.chunk(['a'], 1), [['a']])
        self.assertEqual(pricing.chunk([1, 2, 3], 5), [[1, 2, 3]])
        with self.assertRaises(ValueError):
            pricing.chunk([1, 2], 0)

    def test_pricing_moving_average(self):
        self.assertEqual(pricing.moving_average([1, 2, 3, 4], 2), [1.5, 2.5, 3.5])
        self.assertEqual(pricing.moving_average([5], 1), [5.0])
        self.assertEqual(pricing.moving_average([1, 2, 3], 3), [2.0])
        self.assertEqual(pricing.moving_average([2, 4, 6, 8, 10], 3), [4.0, 6.0, 8.0])
        with self.assertRaises(ValueError):
            pricing.moving_average([1, 2], 0)

    def test_pricing_truncate_words(self):
        self.assertEqual(pricing.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(pricing.truncate_words('tea time', 2), 'tea time')
        self.assertEqual(pricing.truncate_words('', 3), '')
        self.assertEqual(pricing.truncate_words('one two three', 1), 'one...')

    def test_billing_bucket(self):
        self.assertEqual(billing.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(billing.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(billing.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(billing.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(billing.bucket(7, []), 0)

    def test_billing_luhn_valid(self):
        self.assertEqual(billing.luhn_valid('4539 1488 0343 6467'), True)
        self.assertEqual(billing.luhn_valid('79927398713'), True)
        self.assertEqual(billing.luhn_valid('79927398710'), False)
        self.assertEqual(billing.luhn_valid(''), False)
        self.assertEqual(billing.luhn_valid('059'), True)

    def test_billing_grade(self):
        self.assertEqual(billing.grade(95), 'A')
        self.assertEqual(billing.grade(90), 'A')
        self.assertEqual(billing.grade(85), 'B')
        self.assertEqual(billing.grade(80), 'B')
        self.assertEqual(billing.grade(61), 'D')
        self.assertEqual(billing.grade(59), 'F')
        self.assertEqual(billing.grade(0), 'F')

    def test_metrics_dedupe(self):
        self.assertEqual(metrics.dedupe([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(metrics.dedupe(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(metrics.dedupe([]), [])
        self.assertEqual(metrics.dedupe([1, 1, 1]), [1])

    def test_metrics_clamp(self):
        self.assertEqual(metrics.clamp(5, 0, 10), 5)
        self.assertEqual(metrics.clamp(-3, 0, 10), 0)
        self.assertEqual(metrics.clamp(15, 0, 10), 10)
        self.assertEqual(metrics.clamp(10, 0, 10), 10)
        self.assertEqual(metrics.clamp(0, 0, 10), 0)
        self.assertEqual(metrics.clamp(7, 7, 7), 7)
        self.assertEqual(metrics.clamp(-20, -30, -10), -20)

    def test_archive_invert(self):
        self.assertEqual(archive.invert({'a': 1, 'b': 2, 'c': 1}), {1: ['a', 'c'], 2: ['b']})
        self.assertEqual(archive.invert({}), {})
        self.assertEqual(archive.invert({'x': 'y'}), {'y': ['x']})
        self.assertEqual(archive.invert({'q': 0, 'p': 0, 'r': 0}), {0: ['p', 'q', 'r']})

    def test_archive_top_n(self):
        self.assertEqual(archive.top_n({'tea': 3, 'milk': 3, 'jam': 1}, 2), ['milk', 'tea'])
        self.assertEqual(archive.top_n({'a': 1}, 5), ['a'])
        self.assertEqual(archive.top_n({}, 2), [])
        self.assertEqual(archive.top_n({'x': 2, 'y': 5, 'z': 2}, 2), ['y', 'x'])

    def test_archive_weighted_mean(self):
        self.assertEqual(archive.weighted_mean([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(archive.weighted_mean([10, 20], [1, 3]), 17.5)
        self.assertEqual(archive.weighted_mean([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            archive.weighted_mean([5, 5], [0, 0])
        self.assertEqual(archive.weighted_mean([1, 2], [0.5, 1.5]), 1.75)
