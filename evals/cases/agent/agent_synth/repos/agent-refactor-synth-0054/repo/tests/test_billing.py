import unittest

from kiln import billing


class Billing(unittest.TestCase):
    def test_dock_entry(self):
        self.assertEqual(billing.dock_entry('aaab'), {'dock_entry': [('a', 3), ('b', 1)]})
        self.assertEqual(billing.dock_entry(''), {'dock_entry': []})

    def test_grade(self):
        self.assertEqual(billing.grade(95), 'A')
        self.assertEqual(billing.grade(90), 'A')
