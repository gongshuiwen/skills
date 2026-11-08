#!/usr/bin/env bash
set -euo pipefail
cat > /app/tests/test_workflow.py <<'PY'
import unittest
from workflow import Order

class OrderWorkflowTests(unittest.TestCase):
    def test_approve(self):
        self.assertEqual(Order().approve(), "approved")

    def test_ship(self):
        order = Order()
        order.approve()
        self.assertEqual(order.ship(), "shipped")

    def test_cancel(self):
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
PY
python3 -B -m unittest discover -s tests -v
