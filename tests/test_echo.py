"""Tests for the CNS Echo signal analyzer."""

import pytest
from cns_echo.echo import (
    analyze,
    AnalysisResult,
    _verify_checksum,
    VALID_PRIORITIES,
    VALID_INTENTS,
    REQUIRED_HEADER_FIELDS,
    REQUIRED_BODY_FIELDS,
)


def make_valid_packet(
    origin="lucineer-riker",
    priority="HIGH",
    intent="QUERY",
    sequence_id=1,
    checksum="verified",
):
    return {
        "header": {
            "origin_id": origin,
            "timestamp": "2026-08-05T07:00:00Z",
            "priority": priority,
            "sequence_id": sequence_id,
        },
        "body": {
            "intent": intent,
            "payload": {
                "type": "signal",
                "data": {"message": "test"},
            },
        },
        "signature": {
            "type": "USCP-v1",
            "checksum": checksum,
        },
    }


class TestVerifyChecksum:
    def test_verified_string(self):
        assert _verify_checksum({"signature": {"checksum": "verified"}}) is True

    def test_handshake_verified(self):
        assert _verify_checksum({"signature": {"checksum": "handshake-verified"}}) is True

    def test_empty_checksum(self):
        assert _verify_checksum({"signature": {"checksum": ""}}) is False

    def test_no_checksum(self):
        assert _verify_checksum({"signature": {}}) is False

    def test_content_hash(self):
        import json, hashlib
        packet = {"header": {"a": 1}, "body": {"b": 2}}
        content = json.dumps(packet, sort_keys=True)
        h = hashlib.sha256(content.encode()).hexdigest()[:16]
        full = {"signature": {"checksum": h}, **packet}
        assert _verify_checksum(full) is True

    def test_wrong_content_hash(self):
        full = {"signature": {"checksum": "abcdef1234567890"},
                "header": {"a": 1}, "body": {"b": 2}}
        assert _verify_checksum(full) is False


class TestAnalyze:
    def test_returns_analysis_result(self):
        result = analyze(make_valid_packet())
        assert isinstance(result, AnalysisResult)

    def test_valid_packet_high_health(self):
        result = analyze(make_valid_packet())
        assert result.health_score >= 0.9

    def test_missing_header_field(self):
        packet = make_valid_packet()
        del packet["header"]["origin_id"]
        result = analyze(packet)
        assert result.health_score < 1.0
        assert any("origin_id" in e for e in result.protocol_errors)

    def test_missing_body_field(self):
        packet = make_valid_packet()
        del packet["body"]["intent"]
        result = analyze(packet)
        assert any("intent" in e for e in result.protocol_errors)

    def test_invalid_priority(self):
        packet = make_valid_packet(priority="URGENT")
        result = analyze(packet)
        assert any("priority" in w for w in result.protocol_warnings)

    def test_unknown_intent(self):
        packet = make_valid_packet(intent="NEW_THING")
        result = analyze(packet)
        assert any("Unknown intent" in w for w in result.protocol_warnings)

    def test_emergency_detection(self):
        packet = make_valid_packet(priority="CRITICAL", intent="EMERGENCY_HALT")
        result = analyze(packet)
        assert result.suggested_intent == "EMERGENCY_ACK"
        assert result.suggested_priority == "CRITICAL"
        assert any("EMERGENCY" in n for n in result.health_notes)

    def test_handshake_response(self):
        packet = make_valid_packet(intent="HANDSHAKE_COMPLETE")
        result = analyze(packet)
        assert result.suggested_intent == "HANDSHAKE_COMPLETE"

    def test_reasoning_response(self):
        packet = make_valid_packet(intent="REQUEST_REASONING")
        result = analyze(packet)
        assert result.suggested_intent == "REASONING_RESPONSE"

    def test_query_response(self):
        packet = make_valid_packet(intent="QUERY")
        result = analyze(packet)
        assert result.suggested_intent == "QUERY_RESPONSE"

    def test_telemetry_response(self):
        packet = make_valid_packet(intent="TELEMETRY")
        result = analyze(packet)
        assert result.suggested_intent == "TELEMETRY_ACK"
        assert result.suggested_priority == "LOW"

    def test_processing_time_positive(self):
        result = analyze(make_valid_packet())
        assert result.processing_time_ms >= 0.0

    def test_received_at_is_timestamp(self):
        result = analyze(make_valid_packet())
        assert "T" in result.received_at
        assert result.received_at.endswith("Z")

    def test_checksum_valid_flag(self):
        result = analyze(make_valid_packet(checksum="verified"))
        assert result.checksum_valid is True

    def test_checksum_invalid_flag(self):
        result = analyze(make_valid_packet(checksum=""))
        assert result.checksum_valid is False

    def test_suggested_payload_contains_echo(self):
        result = analyze(make_valid_packet())
        assert result.suggested_payload["data"]["echo"] is True

    def test_suggested_payload_contains_health(self):
        result = analyze(make_valid_packet())
        assert "health_score" in result.suggested_payload["data"]


class TestConstants:
    def test_priorities_include_critical(self):
        assert "CRITICAL" in VALID_PRIORITIES

    def test_intents_include_query(self):
        assert "QUERY" in VALID_INTENTS

    def test_header_fields_required(self):
        assert "origin_id" in REQUIRED_HEADER_FIELDS
        assert "timestamp" in REQUIRED_HEADER_FIELDS

    def test_body_fields_required(self):
        assert "intent" in REQUIRED_BODY_FIELDS
        assert "payload" in REQUIRED_BODY_FIELDS
