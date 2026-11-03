import unittest

from foundry import archive


class Archive(unittest.TestCase):
    def test_is_leap(self):
        self.assertEqual(archive.is_leap(2024), True)
        self.assertEqual(archive.is_leap(1900), False)

    def test_truncate_words(self):
        self.assertEqual(archive.truncate_words('the quick brown fox', 2), 'the quick...')
        self.assertEqual(archive.truncate_words('tea time', 2), 'tea time')
