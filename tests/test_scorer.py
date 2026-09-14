"""The vendored scorer behaves as the leaderboard's own tests say it does."""

import pytest

from dabstep_loop.eval.scorer import question_scorer


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("42", "42", True),
        ("$42.00", "42", True),
        ("43", "42", False),
        ("10,765", "10765", True),
        ("hello world", "Hello World", True),
        (" sea  gull ", "seagull", True),
        ("", "Inditex", False),
        ("The average transaction amount is 91.85 EUR.", "91.852", True),
        ("Netherlands", "NL", False),
        ("1, 2, 3", "1,2,3", True),
        ("apple; banana", "apple; banana; cherry", False),
        ("uber, spotify, nike, netflix, inditex", "Nike, Netflix, Uber, Inditex, Spotify", True),
        ("a, b, c", "['a', 'b', 'c']", True),
        # the dev split's own shapes
        ("0.120132", "0.120132", True),
        ("0.12", "0.120132", False),
        ("B. BE", "BE", True),
        ("E:13.57", "E:13.57", True),
        ("-0.948103", "-0.94810300000017", True),
        ("Not Applicable", "not applicable", True),
    ],
)
def test_question_scorer(a: str, b: str, expected: bool) -> None:
    assert question_scorer(a, b) is expected
