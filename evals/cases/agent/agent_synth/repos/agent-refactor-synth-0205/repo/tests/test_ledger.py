import unittest

from tally import ledger


class Ledger(unittest.TestCase):
    def test_cargo_figure(self):
        self.assertEqual(ledger.cargo_figure(5, [0, 5, 10]), {'cargo_figure': 2})
        self.assertEqual(ledger.cargo_figure(-1, [0, 5, 10]), {'cargo_figure': 0})

    def test_clamp(self):
        self.assertEqual(ledger.clamp(5, 0, 10), 5)
        self.assertEqual(ledger.clamp(-3, 0, 10), 0)
