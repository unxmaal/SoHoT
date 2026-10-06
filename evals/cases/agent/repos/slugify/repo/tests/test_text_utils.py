import unittest

from text_utils import slugify, truncate


class TextUtils(unittest.TestCase):
    def test_truncate(self):
        self.assertEqual(truncate("abcdef", 5), "ab...")

    def test_slugify_basic(self):
        self.assertEqual(slugify("Hello, World!"), "hello-world")


if __name__ == "__main__":
    unittest.main()
