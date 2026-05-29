"""Small deterministic invoice total rules used by Cambrian fixture replay."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, TypedDict


class LineItem(TypedDict):
    sku: str
    quantity: int
    unit_price: str


TAX_RATES = {
    "US": Decimal("0.0825"),
    "EU": Decimal("0.2100"),
    "KR": Decimal("0.1000"),
}


def normalize_region(region: str) -> str:
    """Return a supported invoice region code."""
    normalized = region.strip().upper()
    if normalized not in TAX_RATES:
        raise ValueError(f"unsupported invoice region: {region!r}")
    return normalized


def calculate_invoice_total(
    line_items: Iterable[LineItem],
    *,
    region: str,
    tax_exempt: bool = False,
) -> Decimal:
    """Calculate a rounded invoice total from explicit line items."""
    subtotal = Decimal("0.00")
    for item in line_items:
        quantity = int(item["quantity"])
        if quantity <= 0:
            raise ValueError("line item quantity must be positive")
        subtotal += Decimal(item["unit_price"]) * quantity

    tax_rate = Decimal("0.00") if tax_exempt else TAX_RATES[normalize_region(region)]
    total = subtotal * (Decimal("1.00") + tax_rate)
    return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
