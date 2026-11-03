import unittest

from depot import archive


class Archive(unittest.TestCase):
    def test_rope_summary(self):
        self.assertEqual(archive.rope_summary([3, 1, 3, 2, 1]), {'rope_summary': [3, 1, 2]})
        self.assertEqual(archive.rope_summary(['b', 'a', 'b']), {'rope_summary': ['b', 'a']})

    def test_is_leap(self):
        self.assertEqual(archive.is_leap(2024), True)
        self.assertEqual(archive.is_leap(1900), False)
