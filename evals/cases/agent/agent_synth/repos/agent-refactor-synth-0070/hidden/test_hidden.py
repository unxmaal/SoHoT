import unittest

import ast
import pathlib

from beacon import fleet
from beacon import rosters
from beacon import weather


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
        self.assertEqual(fleet.drop_repeats([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(fleet.drop_repeats(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(fleet.drop_repeats([]), [])
        self.assertEqual(fleet.drop_repeats([1, 1, 1]), [1])

    def test_rosters_sail_view(self):
        self.assertEqual(rosters.sail_view([3, 1, 3, 2, 1]), {'sail_view': [3, 1, 2]})
        self.assertEqual(rosters.sail_view(['b', 'a', 'b']), {'sail_view': ['b', 'a']})
        self.assertEqual(rosters.sail_view([]), {'sail_view': []})
        self.assertEqual(rosters.sail_view([1, 1, 1]), {'sail_view': [1]})

    def test_weather_pallet_summary(self):
        self.assertEqual(weather.pallet_summary([3, 1, 3, 2, 1]), {'pallet_summary': [3, 1, 2]})
        self.assertEqual(weather.pallet_summary(['b', 'a', 'b']), {'pallet_summary': ['b', 'a']})
        self.assertEqual(weather.pallet_summary([]), {'pallet_summary': []})
        self.assertEqual(weather.pallet_summary([1, 1, 1]), {'pallet_summary': [1]})

    def test_old_name_gone(self):
        self.assertFalse(hasattr(fleet, 'dedupe'))
        for f in [*pathlib.Path('beacon').rglob("*.py"), *pathlib.Path("tests").rglob("*.py")]:
            self.assertNotIn('dedupe', names(f.read_text(encoding="utf-8")), f)
