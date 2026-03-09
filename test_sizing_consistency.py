#!/usr/bin/env python3
"""
Regression tests for strategy parameter sizing consistency.

Verifies that:
- orchestrator MIN_SIZE_PCT default is conservative (not 0.15)
- deterministic_size() values are never clamped upward to 0.15
- DEFAULT_SIZE_PCT in position_manager defaults to a safe value
- record_trade_for_learning respects an explicit size_pct over the module default
"""

import os
import re
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent
ORCH_SOURCE = (REPO_ROOT / "agents" / "orchestrator" / "main.py").read_text()
PM_SOURCE = (REPO_ROOT / "agents" / "07_position_manager" / "main.py").read_text()


# ---------------------------------------------------------------------------
# Helpers to extract constants from source
# ---------------------------------------------------------------------------


def _extract_env_default(source: str, var_name: str) -> float:
    """
    Extract the hard-coded default value from a line like:
        VAR_NAME = float(os.getenv("VAR_NAME", "0.06"))
    """
    pattern = (
        rf'{re.escape(var_name)}\s*=\s*float\(os\.getenv\s*\(\s*"[^"]*"\s*,\s*"([^"]+)"\s*\)\)'
    )
    m = re.search(pattern, source)
    assert m, f"Could not find {var_name} env-default in source"
    return float(m.group(1))


def _extract_hardcoded_value(source: str, var_name: str) -> float:
    """
    Extract a plain integer constant like:
        VAR_NAME = 2
    """
    pattern = rf'^{re.escape(var_name)}\s*=\s*([0-9]+(?:\.[0-9]+)?)\s*$'
    m = re.search(pattern, source, re.MULTILINE)
    assert m, f"Could not find {var_name} as a plain constant in source"
    return float(m.group(1))


# ---------------------------------------------------------------------------
# Orchestrator sizing constants (read from source to avoid import dependencies)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_orchestrator_min_size_pct_default_is_conservative():
    """MIN_SIZE_PCT default must not force sizes up to 0.15."""
    default = _extract_env_default(ORCH_SOURCE, "MIN_SIZE_PCT")
    assert default <= 0.10, (
        f"MIN_SIZE_PCT default is {default}, should be <= 0.10 "
        "to avoid inflating conservative deterministic sizes to 0.15"
    )


@pytest.mark.unit
def test_orchestrator_max_size_pct_default():
    """MAX_SIZE_PCT default should cap trade size at a conservative ceiling."""
    default = _extract_env_default(ORCH_SOURCE, "MAX_SIZE_PCT")
    assert default <= 0.30, (
        f"MAX_SIZE_PCT default is {default}, should be <= 0.30"
    )


@pytest.mark.unit
def test_deterministic_size_function_values():
    """
    deterministic_size() must return 0.06 / 0.08 / 0.10 for the three
    confluence buckets and none of those values must equal 0.15.
    """
    # Extract the function from source and exec it in a minimal namespace
    func_match = re.search(
        r'(def deterministic_size\(.*?)(?=\n\n|\ndef |\nclass )',
        ORCH_SOURCE,
        re.DOTALL,
    )
    assert func_match, "deterministic_size not found in orchestrator source"
    func_src = func_match.group(1)

    ns: dict = {}
    exec(textwrap.dedent(func_src), ns)
    fn = ns["deterministic_size"]

    low = fn(60)    # < 75  -> 0.06
    mid = fn(78)    # 75-84 -> 0.08
    high = fn(90)   # >= 85 -> 0.10

    assert low == 0.06, f"deterministic_size(60) expected 0.06, got {low}"
    assert mid == 0.08, f"deterministic_size(78) expected 0.08, got {mid}"
    assert high == 0.10, f"deterministic_size(90) expected 0.10, got {high}"

    for val in (low, mid, high):
        assert val != 0.15, "deterministic_size must never return 0.15"


@pytest.mark.unit
def test_clamp_does_not_raise_deterministic_sizes_to_0_15():
    """
    Simulating the clamp logic from analysis_cycle:
        size_pct = max(MIN_SIZE_PCT, min(MAX_SIZE_PCT, size_pct))
    All deterministic sizes (0.06, 0.08, 0.10) must survive unchanged.
    """
    min_size = _extract_env_default(ORCH_SOURCE, "MIN_SIZE_PCT")
    max_size = _extract_env_default(ORCH_SOURCE, "MAX_SIZE_PCT")

    func_match = re.search(
        r'(def deterministic_size\(.*?)(?=\n\n|\ndef |\nclass )',
        ORCH_SOURCE,
        re.DOTALL,
    )
    ns: dict = {}
    exec(textwrap.dedent(func_match.group(1)), ns)
    fn = ns["deterministic_size"]

    for confluence in (60, 78, 90):
        raw = fn(confluence)
        clamped = max(min_size, min(max_size, raw))
        assert clamped == raw, (
            f"deterministic_size({confluence})={raw} was changed to {clamped} "
            f"by clamp [MIN={min_size}, MAX={max_size}]. "
            "Sizing must not be inflated above its deterministic value."
        )
        assert clamped != 0.15, (
            f"After clamping confluence={confluence}, size became 0.15 (oversizing bug)"
        )


# ---------------------------------------------------------------------------
# Position manager DEFAULT_SIZE_PCT
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_position_manager_default_size_pct_is_conservative():
    """
    DEFAULT_SIZE_PCT code-level default must be <= 0.10 so that absent
    an explicit env override the position manager does not fall back to 0.15.
    """
    default = _extract_env_default(PM_SOURCE, "DEFAULT_SIZE_PCT")
    assert default <= 0.10, (
        f"DEFAULT_SIZE_PCT hard-coded default is {default}; "
        "must be <= 0.10 to prevent oversized trades when env var is absent"
    )
    assert default != 0.15, (
        "DEFAULT_SIZE_PCT must not default to 0.15 (oversizing bug)"
    )


# ---------------------------------------------------------------------------
# record_trade_for_learning size_pct propagation
# ---------------------------------------------------------------------------


def _build_record_fn(default_size_pct: float):
    """
    Extract record_trade_for_learning from PM source, inject minimal stubs,
    and return (fn, captured_calls) where captured_calls accumulates kwargs
    passed to record_closed_trade.
    """
    func_match = re.search(
        r'(def record_trade_for_learning\(.*?)(?=\n# =======|\nclass |\ndef [a-z])',
        PM_SOURCE,
        re.DOTALL,
    )
    assert func_match, "record_trade_for_learning not found in position_manager source"
    func_src = func_match.group(1)

    captured: list = []

    def fake_record_closed_trade(**kwargs):
        captured.append(kwargs)

    ns = {
        "Optional": __import__("typing").Optional,
        "DEFAULT_SIZE_PCT": default_size_pct,
        "normalize_position_side": lambda x: "long",
        "symbol_base": lambda x: x,
        "record_closed_trade": fake_record_closed_trade,
        "datetime": __import__("datetime").datetime,
        "print": print,
    }
    exec(textwrap.dedent(func_src), ns)
    return ns["record_trade_for_learning"], captured


@pytest.mark.unit
def test_record_trade_for_learning_uses_explicit_size_pct():
    """
    When an explicit size_pct is provided to record_trade_for_learning,
    it must be forwarded to record_closed_trade instead of DEFAULT_SIZE_PCT.
    """
    fn, captured = _build_record_fn(default_size_pct=0.06)

    fn(
        symbol="BTCUSDT",
        side_raw="long",
        entry_price=50000.0,
        exit_price=51000.0,
        leverage=2.0,
        duration_minutes=10,
        size_pct=0.08,
    )

    assert len(captured) == 1, "record_closed_trade should have been called once"
    call = captured[0]
    assert "size_pct" in call, "size_pct was not forwarded to record_closed_trade"
    assert call["size_pct"] == 0.08, (
        f"Expected size_pct=0.08 forwarded, got {call['size_pct']}"
    )


@pytest.mark.unit
def test_record_trade_for_learning_falls_back_to_default_when_not_provided():
    """
    When size_pct is NOT provided to record_trade_for_learning,
    it falls back to DEFAULT_SIZE_PCT (which must be conservative, not 0.15).
    """
    fn, captured = _build_record_fn(default_size_pct=0.06)

    fn(
        symbol="BTCUSDT",
        side_raw="long",
        entry_price=50000.0,
        exit_price=51000.0,
        leverage=2.0,
        duration_minutes=10,
        # size_pct intentionally omitted
    )

    assert len(captured) == 1, "record_closed_trade should have been called once"
    call = captured[0]
    assert call["size_pct"] == 0.06, (
        f"Expected fallback to DEFAULT_SIZE_PCT=0.06, got {call['size_pct']}"
    )
    assert call["size_pct"] != 0.15, (
        "Fallback size_pct must not be 0.15 (that was the oversizing bug)"
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))

