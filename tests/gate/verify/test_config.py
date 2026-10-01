"""Tests for `gate.verify.config`."""

from __future__ import annotations

import pytest

from gate.verify.config import (
    AxiomHonestyConfig,
    AxiomPolicy,
    SorryDeltaConfig,
    SorryPolicy,
    VerifyConfig,
    VerifyConfigError,
    parse_verify_config,
)


def test_empty_text_returns_defaults() -> None:
    cfg = parse_verify_config("")
    assert cfg == VerifyConfig()
    assert cfg.axiom_honesty == AxiomHonestyConfig()
    assert cfg.axiom_honesty.policy is AxiomPolicy.NET_ZERO
    assert cfg.axiom_honesty.allowed_axioms == ()


def test_whitelist_policy_parsed() -> None:
    cfg = parse_verify_config(
        '[audits.axiom_honesty]\n'
        'policy = "whitelist"\n'
        'allowed_axioms = ["propext", "Quot.sound", "Classical.choice"]\n'
    )
    assert cfg.axiom_honesty.policy is AxiomPolicy.WHITELIST
    assert cfg.axiom_honesty.allowed_axioms == (
        "propext",
        "Quot.sound",
        "Classical.choice",
    )


def test_invalid_policy_raises() -> None:
    with pytest.raises(VerifyConfigError, match="invalid"):
        parse_verify_config('[audits.axiom_honesty]\npolicy = "yolo"\n')


def test_malformed_toml_raises() -> None:
    with pytest.raises(VerifyConfigError, match="malformed"):
        parse_verify_config("this = is = not = toml")


def test_sorry_policy_defaults_to_block() -> None:
    cfg = parse_verify_config("")
    assert cfg.sorry_delta == SorryDeltaConfig()
    assert cfg.sorry_delta.policy is SorryPolicy.BLOCK


# --- style threshold knob --------------------------------------------------


def test_style_threshold_parsed() -> None:
    cfg = parse_verify_config("[audits.style]\nthreshold_lines = 150\n")
    assert cfg.style.threshold_lines == 150


def test_style_threshold_must_be_int() -> None:
    with pytest.raises(VerifyConfigError, match="must be an integer"):
        parse_verify_config('[audits.style]\nthreshold_lines = "150"\n')


def test_style_threshold_must_be_positive() -> None:
    with pytest.raises(VerifyConfigError, match=">= 1"):
        parse_verify_config("[audits.style]\nthreshold_lines = 0\n")


def test_sorry_policy_report_parsed() -> None:
    cfg = parse_verify_config('[audits.sorry_delta]\npolicy = "report"\n')
    assert cfg.sorry_delta.policy is SorryPolicy.REPORT


def test_unknown_fields_ignored_forward_compat() -> None:
    cfg = parse_verify_config(
        '[audits.axiom_honesty]\n'
        'policy = "net_zero"\n'
        'future_knob = "ignored"\n'
        '[audits.future_audit]\n'
        'enabled = true\n'
    )
    assert cfg.axiom_honesty.policy is AxiomPolicy.NET_ZERO
