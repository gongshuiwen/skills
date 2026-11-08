import unittest
from workflow import Order

class OrderWorkflowTests(unittest.TestCase):
    def test_approve_a(self):
        self.assertEqual(Order().approve(), "approved")

    def test_approve_b(self):
        self.assertEqual(Order().approve(), "approved")

    def test_approve_c(self):
        self.assertEqual(Order().approve(), "approved")

    def test_ship_a(self):
        order = Order()
        order.approve()
        self.assertEqual(order.ship(), "shipped")

    def test_ship_b(self):
        order = Order()
        order.approve()
        self.assertEqual(order.ship(), "shipped")

    def test_ship_c(self):
        order = Order()
        order.approve()
        self.assertEqual(order.ship(), "shipped")

    def test_cancel_a(self):
        self.assertEqual(Order().cancel(), "cancelled")

    def test_cancel_b(self):
        self.assertEqual(Order().cancel(), "cancelled")

    def test_approve_cancelled_rejected(self):
        order = Order()
        order.cancel()
        with self.assertRaises(ValueError):
            order.approve()

    def test_ship_draft_rejected(self):
        with self.assertRaises(ValueError):
            Order().ship()

    def test_cancel_shipped_rejected(self):
        order = Order()
        order.approve()
        order.ship()
        with self.assertRaises(ValueError):
            order.cancel()

if __name__ == "__main__":
    unittest.main()
