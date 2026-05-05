"""Unit tests for the cost_tables module."""
from __future__ import annotations

import pytest

from riverbank.cost_tables import COST_PER_1K_TOKENS, estimate_cost, format_cost


class TestEstimateCost:
    def test_gpt4o_mini_has_nonzero_rate(self) -> None:
        cost = estimate_cost(1000, 500, "gpt-4o-mini")
        assert cost > 0

    def test_ollama_local_model_is_free(self) -> None:
        cost = estimate_cost(5000, 2000, "llama3.2")
        assert cost == 0.0

    def test_unknown_model_is_free(self) -> None:
        cost = estimate_cost(1000, 1000, "completely-unknown-model-xyz")
        assert cost == 0.0

    def test_zero_tokens_returns_zero(self) -> None:
        cost = estimate_cost(0, 0, "gpt-4o-mini")
        assert cost == 0.0

    def test_gpt4o_cost_formula(self) -> None:
        # gpt-4o: $0.005 / 1k input, $0.015 / 1k output
        expected = (1000 / 1000 * 0.005) + (1000 / 1000 * 0.015)
        assert estimate_cost(1000, 1000, "gpt-4o") == pytest.approx(expected)

    def test_model_name_is_case_insensitive(self) -> None:
        cost_lower = estimate_cost(1000, 0, "gpt-4o-mini")
        cost_upper = estimate_cost(1000, 0, "GPT-4O-MINI")
        assert cost_lower == cost_upper

    def test_all_table_entries_have_non_negative_rates(self) -> None:
        for model, (input_rate, output_rate) in COST_PER_1K_TOKENS.items():
            assert input_rate >= 0, f"Negative input rate for {model}"
            assert output_rate >= 0, f"Negative output rate for {model}"


class TestFormatCost:
    def test_free_model_shows_free_label(self) -> None:
        assert "(free)" in format_cost(0.0)

    def test_nonzero_cost_shows_dollar_sign(self) -> None:
        formatted = format_cost(0.001)
        assert formatted.startswith("$")

    def test_very_small_cost_shows_six_decimal_places(self) -> None:
        formatted = format_cost(0.000001)
        assert "." in formatted
        assert len(formatted.split(".")[1]) >= 4

    def test_normal_cost_shows_four_decimal_places(self) -> None:
        formatted = format_cost(0.1234)
        assert formatted == "$0.1234"
