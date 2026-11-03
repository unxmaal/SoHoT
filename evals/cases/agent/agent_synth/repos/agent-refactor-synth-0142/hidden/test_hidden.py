import unittest

import ast
import pathlib

from kiln import kitchen
from kiln import routes
from kiln import weather


def names(text):
    out = set()
    for n in ast.walk(ast.parse(text)):
        if isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, ast.Attribute):
            out.add(n.attr)
        elif isinstance(n, (ast.FunctionDef, ast.ClassDef)):
            out.add(n.name)
        elif isinstance(n, ast.alias):
            out.update({n.name.split(".")[-1], n.asname})
    return out


class Hidden(unittest.TestCase):
    def test_target(self):
        self.assertEqual(routes.shorten('the quick brown fox', 2), 'the quick...')
        self.assertEqual(routes.shorten('tea time', 2), 'tea time')
        self.assertEqual(routes.shorten('', 3), '')
        self.assertEqual(routes.shorten('one two three', 1), 'one...')

    def test_weather_cargo_entry(self):
        self.assertEqual(weather.cargo_entry('the quick brown fox', 2), {'cargo_entry': 'the quick...'})
        self.assertEqual(weather.cargo_entry('tea time', 2), {'cargo_entry': 'tea time'})
        self.assertEqual(weather.cargo_entry('', 3), {'cargo_entry': ''})
        self.assertEqual(weather.cargo_entry('one two three', 1), {'cargo_entry': 'one...'})

    def test_kitchen_sail_view(self):
        self.assertEqual(kitchen.sail_view('the quick brown fox', 2), {'sail_view': 'the quick...'})
        self.assertEqual(kitchen.sail_view('tea time', 2), {'sail_view': 'tea time'})
        self.assertEqual(kitchen.sail_view('', 3), {'sail_view': ''})
        self.assertEqual(kitchen.sail_view('one two three', 1), {'sail_view': 'one...'})

    def test_old_name_gone(self):
        self.assertFalse(hasattr(routes, 'truncate_words'))
        for f in [*pathlib.Path('kiln').rglob("*.py"), *pathlib.Path("tests").rglob("*.py")]:
            self.assertNotIn('truncate_words', names(f.read_text(encoding="utf-8")), f)
