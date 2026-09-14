"""Lens 1: every task lands in exactly one family, and the dev-10 anchors are where the plan says."""

from __future__ import annotations

from dabstep_loop.data.tasks import load_tasks
from dabstep_loop.loop.families import FAMILIES, assign, coverage, family_of, family_of_template


def test_every_task_has_one_family_and_the_table_sums_to_450() -> None:
    tasks = assign("all")
    assert len(tasks) == 450
    rows = coverage()
    assert sum(r["tasks"] for r in rows) == 450
    assert {r["id"] for r in rows} == {f.id for f in FAMILIES}


def test_dev_anchors() -> None:
    anchors = {r["id"]: set(r["dev_anchor"]) for r in coverage()}
    assert anchors["F01"] == {"1681", "1753"}
    assert anchors["F02"] == {"1464"}
    assert anchors["F04"] == {"1871"}
    assert anchors["F07"] == {"1273", "1305"}
    assert anchors["F10"] == {"2697"}
    assert anchors["F12"] == {"5", "49", "70"}
    unanchored = [fid for fid, a in anchors.items() if not a]
    assert sorted(unanchored) == ["F03", "F05", "F06", "F08", "F09", "F11"]


def test_family_patterns_are_specific() -> None:
    assert (
        family_of_template("what are the total fees (in euros) that <merchant> paid in <year>?").id
        == "F03"
    )
    assert (
        family_of_template(
            "in <month> <year> what delta would <merchant> pay if the relative fee of the fee with id=<n> changed to <n>?"
        ).id
        == "F04"
    )
    assert family_of("How many total transactions are there in the dataset?").id == "F12"
    hard_in_f12 = [
        t for t in load_tasks("all") if t.level == "hard" and family_of(t.question).id == "F12"
    ]
    assert hard_in_f12 == [], [t.question for t in hard_in_f12]


def test_agreement_maths() -> None:
    from dabstep_loop.loop.lenses import adjusted_rand_index, boundary_flags, majority_map

    a = ["x", "x", "y", "y", "z", "z"]
    assert adjusted_rand_index(a, a) == 1.0
    assert adjusted_rand_index(a, ["p", "p", "q", "q", "r", "r"]) == 1.0  # relabelled
    assert abs(adjusted_rand_index(a, ["x", "y", "x", "y", "x", "y"])) < 0.5
    l1 = {"1": "F03", "2": "F03", "3": "F04"}
    l2 = {"1": "C0", "2": "C0", "3": "C0"}
    c2f = majority_map(list(l2.values()), list(l1.values()))
    assert c2f == {"C0": "F03"}
    l3 = {
        "1": [{"cluster": "C0", "confidence": 0.9}],
        "2": [{"cluster": "C0", "confidence": 0.6}, {"cluster": "C1", "confidence": 0.4}],
        "3": [{"cluster": "C0", "confidence": 0.9}],
    }
    flags = boundary_flags(l1, l2, l3, c2f)
    assert flags["1"] == []
    assert any("split" in r for r in flags["2"])
    assert any("lens 2" in r for r in flags["3"]) and any("lens 3" in r for r in flags["3"])
