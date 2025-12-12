# tests/test_core_session_loader.py

import pytest

from aico.session import expand_index_ranges


@pytest.mark.parametrize(
    "input_indices, expected_output",
    [
        # 1. Empty Input Default
        ([], ["-1"]),
        # 2. Single Items (Identity)
        (["1"], ["1"]),
        (["-1"], ["-1"]),
        (["1", "5", "10"], ["1", "5", "10"]),
        # 3. Simple Ranges (Inclusive)
        (["1..3"], ["1", "2", "3"]),
        (["0..2"], ["0", "1", "2"]),
        # 4. Negative Ranges (Allowed)
        (["-3..-1"], ["-3", "-2", "-1"]),
        (["-5..-3"], ["-5", "-4", "-3"]),
        # 5. Single-Step Ranges (Start == End)
        (["5..5"], ["5"]),
        (["-1..-1"], ["-1"]),
        # 6. Reverse Ranges (High..Low, same sign)
        (["3..1"], ["3", "2", "1"]),
        (["-1..-3"], ["-1", "-2", "-3"]),
        # 7. Mixed Types (Ranges + Singles)
        (["1", "5..7"], ["1", "5", "6", "7"]),
        (["0..2", "9"], ["0", "1", "2", "9"]),
        (["1..2", "5..6"], ["1", "2", "5", "6"]),
        # 8. Mixed Signs (Safety: Passthrough as literal)
        (["-1..1"], ["-1..1"]),
        (["2..-2"], ["2..-2"]),
        (["0..-1"], ["0..-1"]),
        # 9. Malformed / Non-Matching Strings (Fallback to Literal)
        (["1...3"], ["1...3"]),  # Too many dots
        (["1.3"], ["1.3"]),  # Not enough dots
        (["a..z"], ["a..z"]),  # Non-digits
        (["1.."], ["1.."]),  # Missing end
        (["..2"], ["..2"]),  # Missing start
    ],
)
def test_expand_index_ranges(input_indices: list[str], expected_output: list[str]) -> None:
    """
    Verifies that Git-style ranges (start..end) are expanded correctly into
    lists of individual index strings, while preserving non-range inputs.

    Safety constraint: Mixed sign ranges (e.g., "1..-1") are treated as literals
    to avoid ambiguous wrapping behavior.
    """
    assert expand_index_ranges(input_indices) == expected_output
