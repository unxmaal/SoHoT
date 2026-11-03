import unittest

import ast
import pathlib

from depot import archive
from depot import budget
from depot import metrics
from depot import orders


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
        self.assertEqual(budget.weighted_average([1, 2, 3], [1, 1, 1]), 2.0)
        self.assertEqual(budget.weighted_average([10, 20], [1, 3]), 17.5)
        self.assertEqual(budget.weighted_average([4], [2]), 4.0)
        with self.assertRaises(ValueError):
            budget.weighted_average([5, 5], [0, 0])
        self.assertEqual(budget.weighted_average([1, 2], [0.5, 1.5]), 1.75)

    def test_metrics_berth_row(self):
        self.assertEqual(metrics.berth_row([1, 2, 3], [1, 1, 1]), {'berth_row': 2.0})
        self.assertEqual(metrics.berth_row([10, 20], [1, 3]), {'berth_row': 17.5})
        self.assertEqual(metrics.berth_row([4], [2]), {'berth_row': 4.0})
        with self.assertRaises(ValueError):
            metrics.berth_row([5, 5], [0, 0])
        self.assertEqual(metrics.berth_row([1, 2], [0.5, 1.5]), {'berth_row': 1.75})

    def test_orders_sail_check(self):
        self.assertEqual(orders.sail_check([1, 2, 3], [1, 1, 1]), {'sail_check': 2.0})
        self.assertEqual(orders.sail_check([10, 20], [1, 3]), {'sail_check': 17.5})
        self.assertEqual(orders.sail_check([4], [2]), {'sail_check': 4.0})
        with self.assertRaises(ValueError):
            orders.sail_check([5, 5], [0, 0])
        self.assertEqual(orders.sail_check([1, 2], [0.5, 1.5]), {'sail_check': 1.75})

    def test_archive_rope_summary(self):
        self.assertEqual(archive.rope_summary([1, 2, 3], [1, 1, 1]), {'rope_summary': 2.0})
        self.assertEqual(archive.rope_summary([10, 20], [1, 3]), {'rope_summary': 17.5})
        self.assertEqual(archive.rope_summary([4], [2]), {'rope_summary': 4.0})
        with self.assertRaises(ValueError):
            archive.rope_summary([5, 5], [0, 0])
        self.assertEqual(archive.rope_summary([1, 2], [0.5, 1.5]), {'rope_summary': 1.75})

    def test_old_name_gone(self):
        self.assertFalse(hasattr(budget, 'weighted_mean'))
        for f in [*pathlib.Path('depot').rglob("*.py"), *pathlib.Path("tests").rglob("*.py")]:
            self.assertNotIn('weighted_mean', names(f.read_text(encoding="utf-8")), f)
