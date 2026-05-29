from __future__ import annotations

from decimal import Decimal

import pytest

from src.invoice_rules import calculate_invoice_total, normalize_region


def test_calculates_taxed_us_invoice_total() -> None:
    total = calculate_invoice_total(
        [
            {"sku": "seat", "quantity": 2, "unit_price": "19.99"},
            {"sku": "setup", "quantity": 1, "unit_price": "10.00"},
        ],
        region="us",
    )

    assert total == Decimal("54.10")


def test_tax_exempt_invoice_uses_subtotal() -> None:
    total = calculate_invoice_total(
        [{"sku": "credit", "quantity": 3, "unit_price": "7.50"}],
        region="EU",
        tax_exempt=True,
    )

    assert total == Decimal("22.50")


def test_rejects_unknown_region() -> None:
    with pytest.raises(ValueError, match="unsupported invoice region"):
        normalize_region("moon")


def test_rejects_non_positive_quantity() -> None:
    with pytest.raises(ValueError, match="quantity"):
        calculate_invoice_total(
            [{"sku": "bad", "quantity": 0, "unit_price": "1.00"}],
            region="KR",
        )
