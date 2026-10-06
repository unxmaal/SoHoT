import unittest

from text_utils import slugify


class HiddenSlugify(unittest.TestCase):
    def test_cases(self):
        for given, want in [("Hello, World!", "hello-world"),
                            ("  A  B  ", "a-b"), ("", ""),
                            ("Ready? Set... GO!!", "ready-set-go"),
                            ("v2.0 release_notes", "v2-0-release-notes"),
                            ("---", ""), ("Cafe 42", "cafe-42")]:
            self.assertEqual(slugify(given), want, given)
