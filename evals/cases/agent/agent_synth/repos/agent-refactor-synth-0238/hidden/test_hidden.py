import unittest

import ast
import pathlib

from orchard import fleet
from orchard import payroll
from orchard import routes
from orchard import weather


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
        self.assertEqual(payroll.drop_repeats([3, 1, 3, 2, 1]), [3, 1, 2])
        self.assertEqual(payroll.drop_repeats(['b', 'a', 'b']), ['b', 'a'])
        self.assertEqual(payroll.drop_repeats([]), [])
        self.assertEqual(payroll.drop_repeats([1, 1, 1]), [1])

    def test_routes_cargo_view(self):
        self.assertEqual(routes.cargo_view([3, 1, 3, 2, 1]), {'cargo_view': [3, 1, 2]})
        self.assertEqual(routes.cargo_view(['b', 'a', 'b']), {'cargo_view': ['b', 'a']})
        self.assertEqual(routes.cargo_view([]), {'cargo_view': []})
        self.assertEqual(routes.cargo_view([1, 1, 1]), {'cargo_view': [1]})

    def test_weather_mooring_summary(self):
        self.assertEqual(weather.mooring_summary([3, 1, 3, 2, 1]), {'mooring_summary': [3, 1, 2]})
        self.assertEqual(weather.mooring_summary(['b', 'a', 'b']), {'mooring_summary': ['b', 'a']})
        self.assertEqual(weather.mooring_summary([]), {'mooring_summary': []})
        self.assertEqual(weather.mooring_summary([1, 1, 1]), {'mooring_summary': [1]})

    def test_fleet_crate_entry(self):
        self.assertEqual(fleet.crate_entry([3, 1, 3, 2, 1]), {'crate_entry': [3, 1, 2]})
        self.assertEqual(fleet.crate_entry(['b', 'a', 'b']), {'crate_entry': ['b', 'a']})
        self.assertEqual(fleet.crate_entry([]), {'crate_entry': []})
        self.assertEqual(fleet.crate_entry([1, 1, 1]), {'crate_entry': [1]})

    def test_old_name_gone(self):
        self.assertFalse(hasattr(payroll, 'dedupe'))
        for f in [*pathlib.Path('orchard').rglob("*.py"), *pathlib.Path("tests").rglob("*.py")]:
            self.assertNotIn('dedupe', names(f.read_text(encoding="utf-8")), f)
