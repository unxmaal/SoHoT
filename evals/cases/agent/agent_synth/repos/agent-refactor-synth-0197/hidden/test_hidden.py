import unittest

import ast
import pathlib

from granary import catalog
from granary import ledger
from granary import orders
from granary import payroll
from granary import stock
from granary import toolkit


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
        self.assertEqual(toolkit.bucket(5, [0, 5, 10]), 2)
        self.assertEqual(toolkit.bucket(-1, [0, 5, 10]), 0)
        self.assertEqual(toolkit.bucket(12, [0, 5, 10]), 3)
        self.assertEqual(toolkit.bucket(0, [0, 5, 10]), 1)
        self.assertEqual(toolkit.bucket(7, []), 0)

    def test_payroll_ferry_summary(self):
        self.assertEqual(payroll.ferry_summary(5, [0, 5, 10]), {'ferry_summary': 2})
        self.assertEqual(payroll.ferry_summary(-1, [0, 5, 10]), {'ferry_summary': 0})
        self.assertEqual(payroll.ferry_summary(12, [0, 5, 10]), {'ferry_summary': 3})
        self.assertEqual(payroll.ferry_summary(0, [0, 5, 10]), {'ferry_summary': 1})
        self.assertEqual(payroll.ferry_summary(7, []), {'ferry_summary': 0})

    def test_orders_ferry_entry(self):
        self.assertEqual(orders.ferry_entry(5, [0, 5, 10]), {'ferry_entry': 2})
        self.assertEqual(orders.ferry_entry(-1, [0, 5, 10]), {'ferry_entry': 0})
        self.assertEqual(orders.ferry_entry(12, [0, 5, 10]), {'ferry_entry': 3})
        self.assertEqual(orders.ferry_entry(0, [0, 5, 10]), {'ferry_entry': 1})
        self.assertEqual(orders.ferry_entry(7, []), {'ferry_entry': 0})

    def test_stock_mast_summary(self):
        self.assertEqual(stock.mast_summary(5, [0, 5, 10]), {'mast_summary': 2})
        self.assertEqual(stock.mast_summary(-1, [0, 5, 10]), {'mast_summary': 0})
        self.assertEqual(stock.mast_summary(12, [0, 5, 10]), {'mast_summary': 3})
        self.assertEqual(stock.mast_summary(0, [0, 5, 10]), {'mast_summary': 1})
        self.assertEqual(stock.mast_summary(7, []), {'mast_summary': 0})

    def test_ledger_barge_entry(self):
        self.assertEqual(ledger.barge_entry(5, [0, 5, 10]), {'barge_entry': 2})
        self.assertEqual(ledger.barge_entry(-1, [0, 5, 10]), {'barge_entry': 0})
        self.assertEqual(ledger.barge_entry(12, [0, 5, 10]), {'barge_entry': 3})
        self.assertEqual(ledger.barge_entry(0, [0, 5, 10]), {'barge_entry': 1})
        self.assertEqual(ledger.barge_entry(7, []), {'barge_entry': 0})

    def test_moved(self):
        new = pathlib.Path('granary/toolkit.py').read_text(encoding="utf-8")
        self.assertTrue(any(isinstance(n, ast.FunctionDef) and n.name == 'bucket' for n in ast.walk(ast.parse(new))))
        text = pathlib.Path('granary/catalog.py').read_text(encoding="utf-8")
        self.assertNotIn('bucket', names(text))
