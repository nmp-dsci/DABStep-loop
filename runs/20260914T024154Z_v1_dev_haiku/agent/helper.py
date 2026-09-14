"""Helper module for the DABstep agent, importable inside execute_python as `helper`.

v0 was deliberately thin: loaders and the one formula the manual states. v1 adds the
computational primitives that dev-split failures showed the agent kept reinventing
ad hoc (and getting subtly wrong): fee-rule matching with null/[]-as-wildcard
semantics (including for `is_credit` and `card_scheme`, not just the list fields),
monthly fraud-rate/volume bucketing per manual.md section 5, the merchant
capture_delay -> fee capture_delay bucket mapping, and the intracountry flag
(issuing_country vs acquirer_country, per manual.md section 5 — NOT ip_country).

None of this is specific to one merchant/month/fee id: every function takes the
merchant/period/rule as arguments so it generalizes across permutations of the
dev-split questions (other merchants, other months, other card schemes).
"""

from __future__ import annotations

import datetime
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


# --------------------------------------------------------------------------
# Fraud rate: manual.md section 7 defines fraud as a RATE, not a count.
# "Fraud is defined as the ratio of fraudulent volume over total volume."
# Ranking things "by fraud" (top country, top merchant, ...) means ranking by
# this ratio, not by the raw count of fraudulent transactions - the busiest
# country/merchant will usually have the most fraud cases in absolute terms
# without having the worst fraud *rate*.
# --------------------------------------------------------------------------


def fraud_rate(df: pd.DataFrame) -> float:
    """Fraction (0-1) of eur_amount volume in df that is fraudulent (manual.md section 7)."""
    total = df["eur_amount"].sum()
    if total == 0:
        return 0.0
    fraud = df.loc[df["has_fraudulent_dispute"].astype(bool), "eur_amount"].sum()
    return fraud / total


def fraud_rate_by(df: pd.DataFrame, group_col: str) -> pd.Series:
    """Fraud rate (fraudulent volume / total volume) per value of group_col, sorted descending.

    Use this - not `value_counts()` of has_fraudulent_dispute - to answer "top X for
    fraud" questions; the top raw fraud *count* is often a different answer than the
    top fraud *rate*, and the manual defines fraud as the rate.
    """
    return df.groupby(group_col, observed=True).apply(fraud_rate).sort_values(ascending=False)


# --------------------------------------------------------------------------
# Monthly aggregates and bucketing (manual.md section 5).
# --------------------------------------------------------------------------


def day_of_year_to_month(day_of_year: int, year: int) -> int:
    """Convert payments.csv's (year, day_of_year) into a calendar month (1-12)."""
    return (datetime.date(year, 1, 1) + datetime.timedelta(days=int(day_of_year) - 1)).month


def capture_delay_bucket(merchant_capture_delay: str) -> str:
    """Map a merchant_data.json capture_delay ('immediate', 'manual', or a day count
    like '1', '2', '7') onto the bucket strings used in fees.json's capture_delay
    field: 'immediate', 'manual', '<3', '3-5', '>5'.
    """
    if merchant_capture_delay in ("immediate", "manual"):
        return merchant_capture_delay
    days = int(merchant_capture_delay)
    if days < 3:
        return "<3"
    if days <= 5:
        return "3-5"
    return ">5"


def fraud_level_bucket(fraud_rate_pct: float) -> str:
    """Map a fraud rate in PERCENT (e.g. 8.0 for 8%) onto fees.json's monthly_fraud_level bucket."""
    if fraud_rate_pct < 7.2:
        return "<7.2%"
    if fraud_rate_pct < 7.7:
        return "7.2%-7.7%"
    if fraud_rate_pct < 8.3:
        return "7.7%-8.3%"
    return ">8.3%"


def volume_bucket(monthly_volume_eur: float) -> str:
    """Map a monthly EUR volume onto fees.json's monthly_volume bucket."""
    if monthly_volume_eur < 100_000:
        return "<100k"
    if monthly_volume_eur < 1_000_000:
        return "100k-1m"
    if monthly_volume_eur < 5_000_000:
        return "1m-5m"
    return ">5m"


def monthly_merchant_stats(payments: pd.DataFrame, merchant: str, year: int, month: int) -> dict[str, Any]:
    """Natural-month stats for one merchant, per manual.md section 5 ("Monthly volumes
    and rates are computed always in natural months").

    Returns the merchant's transactions for that (year, month) plus the monthly
    total volume, fraud rate (%), and the fees.json bucket strings for both -
    everything needed as the merchant-level filters for fee_rule_matches().
    """
    sub = payments[payments["merchant"] == merchant].copy()
    sub["month"] = sub["day_of_year"].apply(lambda d: day_of_year_to_month(d, year))
    sub = sub[(sub["year"] == year) & (sub["month"] == month)].drop(columns="month")
    total_volume = sub["eur_amount"].sum()
    rate_pct = fraud_rate(sub) * 100
    return {
        "transactions": sub,
        "total_volume": total_volume,
        "fraud_rate_pct": rate_pct,
        "monthly_volume_bucket": volume_bucket(total_volume),
        "monthly_fraud_level_bucket": fraud_level_bucket(rate_pct),
    }


def is_intracountry(issuing_country: str, acquirer_country: str) -> bool:
    """manual.md section 5: intracountry (domestic) means issuer country == acquirer
    country. payments.csv carries both per transaction as 'issuing_country' and
    'acquirer_country' - do NOT substitute 'ip_country', that's a different field
    (where the shopper physically was, not who issued the card or acquired the tx).
    """
    return issuing_country == acquirer_country


# --------------------------------------------------------------------------
# Fee-rule matching. manual.md section 5: "If a field is set to null it means
# that it applies to all possible values of that field" - and empirically this
# wildcard convention also holds for fields typed bool/str (is_credit,
# card_scheme, capture_delay, ...), not just the list-typed fields, and an
# empty list [] is the list-typed spelling of the same wildcard.
# --------------------------------------------------------------------------


def _field_matches(rule_value: Any, actual_value: Any) -> bool:
    if actual_value is None:
        return True  # caller isn't filtering on this field
    if rule_value is None:
        return True  # null = wildcard, matches everything
    if isinstance(rule_value, list):
        if len(rule_value) == 0:
            return True  # [] = wildcard, matches everything
        return actual_value in rule_value
    return rule_value == actual_value  # works for bool/float intracountry vs bool actual too


def fee_rule_matches(
    rule: dict[str, Any],
    *,
    card_scheme: str | None = None,
    account_type: str | None = None,
    mcc: int | None = None,
    capture_delay: str | None = None,
    monthly_fraud_level: str | None = None,
    monthly_volume: str | None = None,
    is_credit: bool | None = None,
    aci: str | None = None,
    intracountry: bool | None = None,
) -> bool:
    """Does this fees.json rule apply, given these merchant/transaction characteristics?

    Pass only the fields you know/care about; omitted (None) fields are not checked.
    For a merchant-level pre-filter, pass account_type/mcc/capture_delay/monthly_*
    and leave card_scheme/is_credit/aci/intracountry as None. For a specific
    transaction's fee, pass all nine fields.
    """
    return (
        _field_matches(rule["card_scheme"], card_scheme)
        and _field_matches(rule["account_type"], account_type)
        and _field_matches(rule["merchant_category_code"], mcc)
        and _field_matches(rule["capture_delay"], capture_delay)
        and _field_matches(rule["monthly_fraud_level"], monthly_fraud_level)
        and _field_matches(rule["monthly_volume"], monthly_volume)
        and _field_matches(rule["is_credit"], is_credit)
        and _field_matches(rule["aci"], aci)
        and _field_matches(rule["intracountry"], intracountry)
    )


def applicable_fee_ids(
    fees: list[dict[str, Any]],
    transactions: pd.DataFrame,
    *,
    account_type: str,
    mcc: int,
    capture_delay: str,
    monthly_fraud_level: str,
    monthly_volume: str,
) -> list[int]:
    """Fee IDs that apply to a merchant over a period: every rule for which AT LEAST
    ONE row in `transactions` matches, combining the fixed merchant/period-level
    filters with each row's own card_scheme/is_credit/aci/intracountry.

    `transactions` should already be filtered to the merchant and period in
    question (see monthly_merchant_stats, or filter payments.csv yourself e.g. by
    day_of_year for a single-day question). account_type/mcc/capture_delay come
    from get_merchant_info() (run capture_delay through capture_delay_bucket()
    first); monthly_fraud_level/monthly_volume come from monthly_merchant_stats()
    for the natural month containing the period.
    """
    merchant_level_fees = [
        f
        for f in fees
        if fee_rule_matches(
            f,
            account_type=account_type,
            mcc=mcc,
            capture_delay=capture_delay,
            monthly_fraud_level=monthly_fraud_level,
            monthly_volume=monthly_volume,
        )
    ]
    applicable: set[int] = set()
    for _, txn in transactions.iterrows():
        intracountry = is_intracountry(txn["issuing_country"], txn["acquirer_country"])
        for f in merchant_level_fees:
            if f["ID"] in applicable:
                continue
            if fee_rule_matches(
                f,
                card_scheme=txn["card_scheme"],
                is_credit=bool(txn["is_credit"]),
                aci=txn["aci"],
                intracountry=intracountry,
            ):
                applicable.add(f["ID"])
    return sorted(applicable)


def best_matching_fee(fees: list[dict[str, Any]], **filters: Any) -> dict[str, Any] | None:
    """The single fee rule that would actually be charged for one fully-specified
    transaction: among all rules matching fee_rule_matches(rule, **filters), the
    MOST SPECIFIC one (fewest wildcard fields) - e.g. a rule naming this exact aci
    beats a rule whose aci is a wildcard. Ties broken by lowest fee at a 1 EUR
    transaction value, then by ID, for determinism. Returns None if no rule matches.

    Use this (not applicable_fee_ids, which returns the whole matching *set*) when
    you need to actually charge one fee to one transaction - e.g. simulating "what
    would this transaction cost if its ACI were X instead".
    """
    candidates = [f for f in fees if fee_rule_matches(f, **filters)]
    if not candidates:
        return None

    def specificity(f: dict[str, Any]) -> int:
        fields = (
            "account_type",
            "capture_delay",
            "monthly_fraud_level",
            "monthly_volume",
            "merchant_category_code",
            "is_credit",
            "aci",
            "intracountry",
        )
        return sum(1 for k in fields if f[k] is not None and f[k] != [])

    return max(
        candidates,
        key=lambda f: (specificity(f), -calculate_fee(f["fixed_amount"], f["rate"], 1.0), -f["ID"]),
    )


def average_fee_across_rules(fees: list[dict[str, Any]], transaction_value: float, **filters: Any) -> float:
    """Average fee, at the given transaction_value, across every fee rule matching
    fee_rule_matches(rule, **filters) - e.g. average_fee_across_rules(fees, 10,
    card_scheme="GlobalCard", is_credit=True) averages over every GlobalCard rule
    that applies to credit transactions, INCLUDING rules whose is_credit is null
    (applies to both credit and debit) - do not filter those out by hand, that
    under-counts the matching rules.
    """
    matching = [f for f in fees if fee_rule_matches(f, **filters)]
    if not matching:
        raise ValueError(f"no fee rule matches filters={filters!r}")
    values = [calculate_fee(f["fixed_amount"], f["rate"], transaction_value) for f in matching]
    return sum(values) / len(values)
