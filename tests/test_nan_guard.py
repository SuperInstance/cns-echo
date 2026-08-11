"""Tests for NaN/Inf guards and malformed input handling in cns-echo.

These tests address the fleet-wide NaN blindness documented in
2026-08-11-0000-negative-space-fleet-wide-nan-blindness.md.
"""

import math
import pytest
from cns_echo.echo import analyze, _sanitize_float


# ─── _sanitize_float Tests ─────────────────────────────────────

class TestSanitizeFloat:
    def test_normal_value_passes_through(self):
        assert _sanitize_float(0.5) == 0.5

    def test_nan_replaced_with_default(self):
        assert _sanitize_float(float("nan")) == 0.0

    def test_inf_replaced_with_default(self):
        assert _sanitize_float(float("inf")) == 0.0

    def test_neg_inf_replaced_with_default(self):
        assert _sanitize_float(float("-inf")) == 0.0

    def test_none_replaced_with_default(self):
        assert _sanitize_float(None) == 0.0

    def test_bool_replaced_with_default(self):
        # bool is a subclass of int but shouldn't be treated as a valid float
        assert _sanitize_float(True) == 0.0

    def test_string_that_is_a_number(self):
        assert _sanitize_float("3.14") == 3.14

    def test_string_that_is_not_a_number(self):
        assert _sanitize_float("banana") == 0.0

    def test_custom_default(self):
        assert _sanitize_float(float("nan"), default=-1.0) == -1.0

    def test_zero_is_preserved(self):
        assert _sanitize_float(0.0) == 0.0

    def test_negative_zero_is_preserved(self):
        assert _sanitize_float(-0.0) == -0.0


# ─── Malformed Packet Tests ────────────────────────────────────

class TestMalformedInput:
    def test_non_dict_packet_returns_zero_health(self):
        result = analyze("not a packet")
        assert result.health_score == 0.0
        assert len(result.protocol_errors) > 0
        assert "not a dict" in result.protocol_errors[0] or "dict" in result.protocol_errors[0]

    def test_list_packet_handled(self):
        result = analyze([1, 2, 3])
        assert result.health_score == 0.0
        assert result.protocol_errors

    def test_none_packet_handled(self):
        result = analyze(None)
        assert result.health_score == 0.0

    def test_integer_packet_handled(self):
        result = analyze(42)
        assert result.health_score == 0.0

    def test_non_dict_header_section(self):
        """Header is a string instead of dict — should warn, not crash."""
        packet = {
            "header": "broken",
            "body": {"intent": "QUERY", "payload": {"type": "text", "data": "hi"}},
            "signature": {"type": "sha256", "checksum": "verified"},
        }
        result = analyze(packet)
        assert "header is not a dict" in result.protocol_errors
        assert result.health_score < 0.7
        assert len(result.protocol_errors) >= 5  # header section + 4 missing fields

    def test_non_dict_body_section(self):
        packet = {
            "header": {"origin_id": "x", "timestamp": "t", "priority": "LOW", "sequence_id": 1},
            "body": 42,
            "signature": {"type": "sha256", "checksum": "verified"},
        }
        result = analyze(packet)
        assert "body is not a dict" in result.protocol_errors

    def test_non_dict_signature_section(self):
        packet = {
            "header": {"origin_id": "x", "timestamp": "t", "priority": "LOW", "sequence_id": 1},
            "body": {"intent": "QUERY", "payload": {"type": "text", "data": "hi"}},
            "signature": "oops",
        }
        result = analyze(packet)
        assert "signature is not a dict" in result.protocol_errors

    def test_completely_empty_dict(self):
        result = analyze({})
        assert result.health_score == 0.0
        assert len(result.protocol_errors) >= 3  # missing header, body, signature


# ─── NaN Propagation Tests ─────────────────────────────────────

class TestNaNPropagation:
    def test_health_score_is_never_nan(self):
        """No matter what we throw at analyze(), health_score must not be NaN."""
        for bad_input in [None, 42, "str", [], {}, {"header": None}]:
            result = analyze(bad_input)
            assert not math.isnan(result.health_score), \
                f"health_score is NaN for input: {bad_input!r}"

    def test_health_score_is_never_inf(self):
        for bad_input in [None, 42, "str", [], {}, {"header": float("inf")}]:
            result = analyze(bad_input)
            assert not math.isinf(result.health_score), \
                f"health_score is Inf for input: {bad_input!r}"

    def test_processing_time_is_never_nan(self):
        for bad_input in [None, 42, "str", [], {}]:
            result = analyze(bad_input)
            assert not math.isnan(result.processing_time_ms), \
                f"processing_time_ms is NaN for input: {bad_input!r}"
