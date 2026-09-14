"""Helper module for the DABstep agent, importable inside execute_python as `helper`.

v0 is deliberately thin: loaders and the one formula the manual states. The
loop's optimiser grows this file from the failures it diagnoses — matching
semantics for fee rules, monthly metrics, intracountry flags — the way the
NVIDIA recipe distilled its helper from learning traces.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

DATA_DIR = Path("data/context") if Path("data/context/payments.csv").exists() else Path("data/samples")


def load_payments() -> pd.DataFrame:
    """The transactions table (payments.csv)."""
    return pd.read_csv(DATA_DIR / "payments.csv")


def load_fees() -> list[dict[str, Any]]:
    """The 1000 fee rules (fees.json); null or [] in a field means the rule applies to all values."""
    with (DATA_DIR / "fees.json").open() as f:
        return list(json.load(f))


def load_merchants() -> list[dict[str, Any]]:
    """Merchant metadata (merchant_data.json): capture_delay, acquirer, MCC, account_type."""
    with (DATA_DIR / "merchant_data.json").open() as f:
        return list(json.load(f))


def load_acquirer_countries() -> pd.DataFrame:
    """acquirer -> country_code (acquirer_countries.csv)."""
    return pd.read_csv(DATA_DIR / "acquirer_countries.csv")


def load_mcc() -> pd.DataFrame:
    """mcc -> description (merchant_category_codes.csv)."""
    return pd.read_csv(DATA_DIR / "merchant_category_codes.csv")


def get_merchant_info(name: str) -> dict[str, Any]:
    """The merchant_data.json record for one merchant."""
    for m in load_merchants():
        if m["merchant"] == name:
            return m
    raise KeyError(name)


def calculate_fee(fixed_amount: float, rate: float, transaction_value: float) -> float:
    """manual.md: fee = fixed_amount + rate * transaction_value / 10000."""
    return fixed_amount + rate * transaction_value / 10000
