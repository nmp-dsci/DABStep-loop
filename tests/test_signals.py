"""Invariants and format checks on synthetic answers, both directions; the sampler's guarantees."""

from __future__ import annotations

from dabstep_loop.data.tasks import Task, load_tasks
from dabstep_loop.loop.invariants import Answer, run_checks
from dabstep_loop.loop.sampler import draw
from dabstep_loop.loop.signals import format_of, format_ok, method_signature
from dabstep_loop.loop.slots import Slots, parse


def _a(tid: str, text: str, **slots: object) -> Answer:
    return Answer(tid, text, Slots(**slots))  # type: ignore[arg-type]


def test_f01_subset_both_ways() -> None:
    day = _a("d", "1, 2, 3", merchant="M", year=2023, day_of_year=40)  # 9 Feb
    month = _a("m", "1, 2, 3, 9", merchant="M", year=2023, month=2)
    year = _a("y", "1, 2, 3, 9, 20", merchant="M", year=2023)
    st = {c.name: c.status for c in run_checks("F01", [day, month, year])}
    assert st == {
        "ids(day) ⊆ ids(month)": "passed",
        "ids(day) ⊆ ids(year)": "passed",
        "ids(month) ⊆ ids(year)": "passed",
    }
    bad_month = _a("m", "1, 2", merchant="M", year=2023, month=2)
    st = {c.name: c.status for c in run_checks("F01", [day, bad_month])}
    assert st["ids(day) ⊆ ids(month)"] == "failed"
    skipped = run_checks(
        "F01", [_a("d", "Not Applicable", merchant="M", year=2023, day_of_year=40), month]
    )
    assert all(c.status == "skipped" for c in skipped)


def test_f03_ordering() -> None:
    day = _a("d", "10.50", merchant="M", year=2023, day_of_year=1)
    month = _a("m", "300.00", merchant="M", year=2023, month=1)
    year = _a("y", "200.00", merchant="M", year=2023)
    st = {(c.name, tuple(c.tasks)): c.status for c in run_checks("F03", [day, month, year])}
    assert st[("fees(day) ≤ fees(month)", ("d", "m"))] == "passed"
    assert st[("fees(month) ≤ fees(year)", ("m", "y"))] == "failed"
    assert st[("total is a number ≥ 0", ("y",))] == "passed"


def test_f04_sign_and_magnitude() -> None:
    m = _a("m", "-0.5", merchant="M", year=2023, month=1, fee_id=384, new_rate=1.0)
    y = _a("y", "-3.0", merchant="M", year=2023, fee_id=384, new_rate=1.0)
    assert run_checks("F04", [m, y])[0].status == "passed"
    y2 = _a("y", "0.2", merchant="M", year=2023, fee_id=384, new_rate=1.0)
    assert run_checks("F04", [m, y2])[0].status == "failed"


def test_f06_and_minmax() -> None:
    r = _a("r", "A, B", fee_id=17, year=2023, account_type="O")
    p = _a("p", "A, B, C", fee_id=17, year=2023)
    assert run_checks("F06", [r, p])[0].status == "passed"
    p2 = _a("p", "A", fee_id=17, year=2023)
    assert run_checks("F06", [r, p2])[0].status == "failed"
    lo = Answer("lo", "NexPay:12.5", Slots(merchant="M", year=2023, target="min"), {"shape": "s"})
    hi = Answer(
        "hi", "GlobalCard:20.0", Slots(merchant="M", year=2023, target="max"), {"shape": "s"}
    )
    assert run_checks("F09", [lo, hi])[0].status == "passed"
    same = Answer("hi", "NexPay:9.0", Slots(merchant="M", year=2023, target="max"), {"shape": "s"})
    assert run_checks("F09", [lo, same])[0].status == "failed"


def test_f07_monotone_and_f11_sorted() -> None:
    a = _a("a", "0.10", scheme="GlobalCard", value=10.0)
    b = _a("b", "0.30", scheme="GlobalCard", value=100.0)
    assert run_checks("F07", [a, b])[0].status == "passed"
    assert (
        run_checks("F07", [_a("a", "0.50", scheme="GlobalCard", value=10.0), b])[0].status
        == "failed"
    )
    assert run_checks("F11", [_a("g", "[A: 1.0, B: 2.5]")])[0].status == "passed"
    assert run_checks("F11", [_a("g", "[A: 3.0, B: 2.5]")])[0].status == "failed"


def test_formats_cover_every_guideline_in_the_450_and_accept_the_dev_gold() -> None:
    merchants = ["Belles_cookbook_store"]
    for t in load_tasks("all"):
        assert format_of(t.guidelines) != "" and isinstance(
            format_ok(format_of(t.guidelines), "Not Applicable", merchants), bool
        )
    for t in load_tasks("dev"):
        assert format_ok(format_of(t.guidelines), t.answer, merchants), (t.task_id, t.answer)
    assert not format_ok("scheme:cost", "12.5", merchants)
    assert not format_ok("number", "about 12", merchants)
    assert format_ok("aci:cost", "E:13.57", merchants)


def test_method_signature_reads_helper_calls() -> None:
    trace = [
        {
            "role": "assistant",
            "content": "[{'type': 'tool_use', 'input': {'code': 'from helper import *\\nhelper.total_fees_paid(p, f)'}}]",
        },
        {"role": "tool", "content": "…"},
    ]
    assert method_signature(trace) == ("helper.total_fees_paid", "helper:import")
    bare = [
        {"role": "assistant", "content": "x = applicable_fee_ids(p, f, 'M', 2023); df.groupby('a')"}
    ]
    assert method_signature(bare, {"applicable_fee_ids", "total_fees_paid"}) == (
        "helper.applicable_fee_ids",
        "pd:groupby",
    )


def test_sampler_is_seeded_and_never_draws_dev() -> None:
    a, b = draw(3, 7), draw(3, 7)
    assert a.task_ids == b.task_ids and len(a.task_ids) > 30
    dev = {t.task_id for t in load_tasks("dev")}
    assert not (set(a.task_ids) & dev)
    assert all(len(v) >= 3 for v in a.drawn.values())
    assert draw(3, 8).task_ids != a.task_ids


def test_slots_parse() -> None:
    t = Task(
        "x",
        "In May 2023 what delta would Rafa_AI pay if the relative fee of the fee with ID=787 changed to 1?",
        "",
        "hard",
        "",
    )
    s = parse(t, ["Rafa_AI"])
    assert (s.merchant, s.year, s.month, s.fee_id, s.new_rate, s.period) == (
        "Rafa_AI",
        2023,
        5,
        787,
        1.0,
        "month",
    )
    d = parse(
        Task(
            "y",
            "For the 40th of the year 2023, what are the Fee IDs applicable to Rafa_AI?",
            "",
            "hard",
            "",
        ),
        ["Rafa_AI"],
    )
    assert d.period == "day" and d.month_of_day == 2
