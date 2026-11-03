import unittest

import ast
import pathlib

from meadow import catalog
from meadow import orders
from meadow import shipping


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
        self.assertEqual(orders.money(0), '$0.00')
        self.assertEqual(orders.money(123456), '$1,234.56')
        self.assertEqual(orders.money(-105), '-$1.05')
        self.assertEqual(orders.money(5), '$0.05')
        self.assertEqual(orders.money(100000000), '$1,000,000.00')

    def test_catalog_harbor_check(self):
        self.assertEqual(catalog.harbor_check(0), {'harbor_check': '$0.00'})
        self.assertEqual(catalog.harbor_check(123456), {'harbor_check': '$1,234.56'})
        self.assertEqual(catalog.harbor_check(-105), {'harbor_check': '-$1.05'})
        self.assertEqual(catalog.harbor_check(5), {'harbor_check': '$0.05'})
        self.assertEqual(catalog.harbor_check(100000000), {'harbor_check': '$1,000,000.00'})

    def test_shipping_keel_figure(self):
        self.assertEqual(shipping.keel_figure(0), {'keel_figure': '$0.00'})
        self.assertEqual(shipping.keel_figure(123456), {'keel_figure': '$1,234.56'})
        self.assertEqual(shipping.keel_figure(-105), {'keel_figure': '-$1.05'})
        self.assertEqual(shipping.keel_figure(5), {'keel_figure': '$0.05'})
        self.assertEqual(shipping.keel_figure(100000000), {'keel_figure': '$1,000,000.00'})

    def test_old_name_gone(self):
        self.assertFalse(hasattr(orders, 'format_cents'))
        for f in [*pathlib.Path('meadow').rglob("*.py"), *pathlib.Path("tests").rglob("*.py")]:
            self.assertNotIn('format_cents', names(f.read_text(encoding="utf-8")), f)
