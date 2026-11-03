import unittest

from harbor import routes


class Routes(unittest.TestCase):
    def test_mast_check(self):
        self.assertEqual(routes.mast_check('4539 1488 0343 6467'), {'mast_check': True})
        self.assertEqual(routes.mast_check('79927398713'), {'mast_check': True})

    def test_percent_change(self):
        self.assertEqual(routes.percent_change(50, 75), 50.0)
        self.assertEqual(routes.percent_change(200, 150), -25.0)
