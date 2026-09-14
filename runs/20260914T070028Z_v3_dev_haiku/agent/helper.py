"""Helper module for the DABstep agent, importable inside execute_python as `helper`.

v0 was deliberately thin: loaders and the one formula the manual states. v1 added
fee-rule matching, monthly bucketing, and a `best_matching_fee` primitive that picked
one "most specific" rule per transaction. v2 keeps everything from v1 EXCEPT
`best_matching_fee`, which cycle-2 diagnosis proved wrong: verified against task 1871
(delta if fee ID=384's rate changed), the merchant is charged under EVERY fees.json
rule whose criteria a transaction satisfies, not a single specificity-based "winner" -
fees are additive line items, not a competition. Using best_matching_fee to decide
"which rule applies" under-counted 4 of the 12 transactions that satisfy rule 384's own
criteria (a more specific rule, 231, also matched them and won the competition), which
is what turned task 1871 from a pass (under v0's ad hoc code) into a fail (under v1's
best_matching_fee). v2 replaces it with `transactions_matching_rule` /
`fee_total_for_rule` / `total_fees_paid`, which use the additive model directly.

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
#
# IMPORTANT (verified against task 1871): a transaction can satisfy more than
# one fee rule's criteria at once, and when that happens the merchant is charged
# under EVERY matching rule, not just the "most specific" one. There is no
# single-winner competition between rules - do not build one (best_matching_fee
# in v1 did, and it was wrong: it silently dropped transactions from a named
# rule's total whenever a more specific rule also happened to match them).
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


def transactions_matching_rule(
    rule: dict[str, Any],
    transactions: pd.DataFrame,
    *,
    account_type: str,
    mcc: int,
    capture_delay: str,
    monthly_fraud_level: str,
    monthly_volume: str,
) -> pd.DataFrame:
    """Rows of `transactions` that this ONE fees.json rule applies to: the merchant-level
    filters (account_type/mcc/capture_delay/monthly_fraud_level/monthly_volume - from
    get_merchant_info()/capture_delay_bucket()/monthly_merchant_stats() for the natural
    month containing the transactions) combined with each row's own
    card_scheme/is_credit/aci/intracountry.

    Use this - NOT a "pick the single most-specific rule per transaction" competition
    - to answer "what does the merchant currently pay under fee ID=X" or "what would
    the delta be if fee ID=X's rate/fixed_amount changed" questions (verified against
    task 1871). A transaction is charged under EVERY rule whose criteria it satisfies;
    do not exclude a transaction from rule X's matches merely because some other, more
    specific rule also happens to match it - that undercounts rule X's transactions.
    """
    if transactions.empty:
        return transactions
    mask = transactions.apply(
        lambda r: fee_rule_matches(
            rule,
            card_scheme=r["card_scheme"],
            is_credit=bool(r["is_credit"]),
            aci=r["aci"],
            intracountry=is_intracountry(r["issuing_country"], r["acquirer_country"]),
            account_type=account_type,
            mcc=mcc,
            capture_delay=capture_delay,
            monthly_fraud_level=monthly_fraud_level,
            monthly_volume=monthly_volume,
        ),
        axis=1,
    )
    return transactions[mask]


def fee_total_for_rule(
    rule: dict[str, Any],
    transactions: pd.DataFrame,
    *,
    account_type: str,
    mcc: int,
    capture_delay: str,
    monthly_fraud_level: str,
    monthly_volume: str,
    fixed_amount: float | None = None,
    rate: float | None = None,
) -> float:
    """Total EUR fee this ONE rule contributes across `transactions` it applies to
    (see transactions_matching_rule for the merchant-level filter kwargs).

    Pass `fixed_amount`/`rate` to override the rule's own values - e.g. to answer
    "what would the delta be if fee ID=384's rate changed to 1", compute
    fee_total_for_rule(rule, txns, ..., rate=1) - fee_total_for_rule(rule, txns, ...).
    The set of matching transactions is the same either way; only the formula's
    fixed_amount/rate change, never which rows match.
    """
    matched = transactions_matching_rule(
        rule,
        transactions,
        account_type=account_type,
        mcc=mcc,
        capture_delay=capture_delay,
        monthly_fraud_level=monthly_fraud_level,
        monthly_volume=monthly_volume,
    )
    if matched.empty:
        return 0.0
    fa = rule["fixed_amount"] if fixed_amount is None else fixed_amount
    r = rule["rate"] if rate is None else rate
    return sum(calculate_fee(fa, r, v) for v in matched["eur_amount"])


def total_fees_paid(
    fees: list[dict[str, Any]],
    transactions: pd.DataFrame,
    *,
    account_type: str,
    mcc: int,
    capture_delay: str,
    monthly_fraud_level: str,
    monthly_volume: str,
) -> dict[int, float]:
    """EUR fee contributed by each applicable fees.json rule, across `transactions`
    (already filtered to the merchant/period in question - see monthly_merchant_stats).

    Fees are additive line items, not a single most-specific-rule-wins pick per
    transaction (verified against task 1871): if more than one rule's criteria match
    a transaction, that transaction contributes to EVERY one of those rules' totals.
    Use this (or fee_total_for_rule for a single named rule) to answer "what does this
    merchant currently pay in fees", "how much does fee ID=X actually cost", or "what
    would change if fee ID=X's rate/fixed_amount changed".

    Returns {fee_id: total_eur} for every rule with at least one matching transaction;
    sum the values for the merchant's total fee bill over the period.
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
    totals: dict[int, float] = {}
    for f in merchant_level_fees:
        matched = transactions_matching_rule(
            f,
            transactions,
            account_type=account_type,
            mcc=mcc,
            capture_delay=capture_delay,
            monthly_fraud_level=monthly_fraud_level,
            monthly_volume=monthly_volume,
        )
        if not matched.empty:
            totals[f["ID"]] = sum(calculate_fee(f["fixed_amount"], f["rate"], v) for v in matched["eur_amount"])
    return totals


def fee_ids_by_attributes(fees: list[dict[str, Any]], **filters: Any) -> list[int]:
    """Fee IDs matching fee_rule_matches(rule, **filters), for questions that give only raw
    fees.json attributes (e.g. account_type + aci) with NO merchant or transactions dataframe -
    applicable_fee_ids doesn't fit this shape since it requires a transactions DataFrame.
    Wildcard rules (null/[] on the filtered fields) are included automatically via
    fee_rule_matches. Returns sorted IDs.
    """
    return sorted(f["ID"] for f in fees if fee_rule_matches(f, **filters))


# --------------------------------------------------------------------------
# F10: "move fraudulent transactions to a different ACI" questions
# (manual.md section 4 ACI table, section 7 fraud). verified against task 2697
# (Belles_cookbook_store, January, fraud txns) that the correct chosen letter is
# the cheapest ACI EXCLUDING the one(s) the fraud transactions are already using
# - two probe traces (2746, 2755) instead argmin'd over ALL candidates including
# the current one, re-selecting the status quo as their "different" choice, which
# contradicts the question ("a DIFFERENT interaction") and is the most likely
# cause of dev task 2697's wrong-letter-or-wrong-value failure. The per-ACI fee
# total itself uses the same additive every-matching-rule model as
# total_fees_paid/fee_total_for_rule (the model already verified against task
# 1871) - only the transactions' aci field is hypothetically overridden.
# --------------------------------------------------------------------------

KNOWN_ACIS = ("A", "B", "C", "D", "E", "F", "G")


def fraud_fee_by_aci(
    fees: list[dict[str, Any]],
    fraud_transactions: pd.DataFrame,
    *,
    account_type: str,
    mcc: int,
    capture_delay: str,
    monthly_fraud_level: str,
    monthly_volume: str,
    candidate_acis: tuple[str, ...] = KNOWN_ACIS,
) -> dict[str, float]:
    """Total EUR fee `fraud_transactions` would incur, per candidate ACI, if every row's
    aci were hypothetically overridden to that value - everything else about each row
    (card_scheme, is_credit, intracountry, eur_amount) stays as-is.

    `fraud_transactions` should already be filtered to the merchant/period AND
    has_fraudulent_dispute == True (this family only concerns the fraudulent subset -
    manual.md section 7). account_type/mcc/capture_delay/monthly_fraud_level/monthly_volume
    are the same merchant-level filters as total_fees_paid (see get_merchant_info,
    capture_delay_bucket, monthly_merchant_stats for the natural month(s) covering the period).

    Uses the additive model (every fees.json rule whose criteria the overridden row
    satisfies contributes to that ACI's total - no single "most specific rule" pick),
    the same model verified against task 1871 for total_fees_paid/fee_total_for_rule.
    A candidate ACI can legitimately cost 0 for a given card scheme if no fee rule at
    all matches that combination - that isn't a bug, it means that scheme/ACI pairing
    is simply free for this merchant's characteristics.

    Returns {aci: total_eur}, one entry per candidate_acis. Does NOT exclude the
    transactions' actual current aci - use cheapest_alternative_aci for "a DIFFERENT
    ACI" questions.
    """
    costs: dict[str, float] = {}
    if fraud_transactions.empty:
        return {aci: 0.0 for aci in candidate_acis}
    for aci in candidate_acis:
        total = 0.0
        for _, r in fraud_transactions.iterrows():
            intracountry = is_intracountry(r["issuing_country"], r["acquirer_country"])
            for f in fees:
                if fee_rule_matches(
                    f,
                    account_type=account_type,
                    mcc=mcc,
                    capture_delay=capture_delay,
                    monthly_fraud_level=monthly_fraud_level,
                    monthly_volume=monthly_volume,
                    card_scheme=r["card_scheme"],
                    is_credit=bool(r["is_credit"]),
                    aci=aci,
                    intracountry=intracountry,
                ):
                    total += calculate_fee(f["fixed_amount"], f["rate"], r["eur_amount"])
        costs[aci] = total
    return costs


def cheapest_alternative_aci(
    fees: list[dict[str, Any]],
    fraud_transactions: pd.DataFrame,
    *,
    account_type: str,
    mcc: int,
    capture_delay: str,
    monthly_fraud_level: str,
    monthly_volume: str,
    candidate_acis: tuple[str, ...] = KNOWN_ACIS,
) -> tuple[str, float, dict[str, float]]:
    """The cheapest ACI to move `fraud_transactions` to, EXCLUDING whichever ACI(s) they
    are already using (a "move towards a DIFFERENT ACI" question - manual.md section 4/7).

    See fraud_fee_by_aci for the cost model and argument meanings. Raises ValueError if
    every candidate ACI is already in use (no alternative exists).

    Returns (best_aci, best_cost, full_cost_table) - full_cost_table has one entry per
    candidate_aci (including the excluded current one(s), for inspection/formatting),
    but best_aci/best_cost are the argmin over ALTERNATIVES only.
    """
    current = set(fraud_transactions["aci"].dropna().unique())
    costs = fraud_fee_by_aci(
        fees,
        fraud_transactions,
        account_type=account_type,
        mcc=mcc,
        capture_delay=capture_delay,
        monthly_fraud_level=monthly_fraud_level,
        monthly_volume=monthly_volume,
        candidate_acis=candidate_acis,
    )
    alternatives = {aci: cost for aci, cost in costs.items() if aci not in current}
    if not alternatives:
        raise ValueError(f"no alternative ACI outside current={current!r} among candidates={candidate_acis!r}")
    best_aci = min(alternatives, key=alternatives.get)
    return best_aci, alternatives[best_aci], costs


def average_fee_across_rules(fees: list[dict[str, Any]], transaction_value: float, **filters: Any) -> float:
    """Average fee, at the given transaction_value, across every fee rule matching
    fee_rule_matches(rule, **filters) - e.g. average_fee_across_rules(fees, 10,
    card_scheme="GlobalCard", is_credit=True) averages over every GlobalCard rule
    that applies to credit transactions, INCLUDING rules whose is_credit is null
    (applies to both credit and debit) - do not filter those out by hand, that
    under-counts the matching rules.

    Use this ONLY when a question literally asks for an "average fee" across rules
    (e.g. "what would be the average fee GlobalCard would charge") - it is not a way
    to price one real transaction. For "what does this merchant actually pay" or
    "what would change if fee ID=X changed", use total_fees_paid/fee_total_for_rule
    instead: those sum every matching rule's own fee, not an average across them.
    """
    matching = [f for f in fees if fee_rule_matches(f, **filters)]
    if not matching:
        raise ValueError(f"no fee rule matches filters={filters!r}")
    values = [calculate_fee(f["fixed_amount"], f["rate"], transaction_value) for f in matching]
    return sum(values) / len(values)
