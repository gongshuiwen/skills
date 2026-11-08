#!/usr/bin/env bash
set -euo pipefail
cat > /app/pricing.py <<'PY'
from decimal import Decimal, ROUND_HALF_UP

def _total(lines, member=False):
    subtotal = Decimal("0")
    for price, quantity in lines:
        value = Decimal(str(price))
        if quantity <= 0 or value < 0:
            raise ValueError("invalid order line")
        subtotal += value * quantity
    if member:
        subtotal *= Decimal("0.95")
    return subtotal.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def quote_total(lines, member=False):
    return _total(lines, member=member)

def invoice_total(lines, member=False):
    return _total(lines, member=member)
PY
python3 -B -m unittest discover -s tests -v
