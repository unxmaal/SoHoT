import unittest

from depot import sensors


class Sensors(unittest.TestCase):
    def test_dock_line(self):
        self.assertEqual(sensors.dock_line([3, 1, 3, 2, 1]), {'dock_line': [3, 1, 2]})
        self.assertEqual(sensors.dock_line(['b', 'a', 'b']), {'dock_line': ['b', 'a']})

    def test_truncate_words(self):
        self.assertEqual(sensors.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(sensors.truncate_words('tea time', 2), 'tea time')
