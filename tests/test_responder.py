"""Tests for the CNS Echo Responder — builds and dispatches USCP response packets."""

import json
import pytest
from pathlib import Path

from cns_echo.echo import AnalysisResult, analyze
from cns_echo.responder import Responder


def make_valid_packet(
    origin="test-agent",
    priority="HIGH",
    intent="QUERY",
    checksum="verified",
):
    return {
        "header": {
            "origin_id": origin,
            "timestamp": "2026-08-05T07:00:00Z",
            "priority": priority,
            "sequence_id": 1,
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


class TestResponderConstruction:
    def test_default_agent_id(self, tmp_path):
        r = Responder(tmp_path / "outbox")
        assert r.agent_id == "cns-echo"

    def test_custom_agent_id(self, tmp_path):
        r = Responder(tmp_path / "outbox", agent_id="hermes")
        assert r.agent_id == "hermes"

    def test_outbox_path(self, tmp_path):
        outbox = tmp_path / "responses"
        r = Responder(outbox)
        assert r.outbox == outbox


class TestRespond:
    def test_creates_outbox_directory(self, tmp_path):
        """Responder should create the outbox if it doesn't exist."""
        outbox = tmp_path / "new_outbox"
        r = Responder(outbox)
        assert not outbox.exists()
        packet = make_valid_packet()
        analysis = analyze(packet)
        r.respond("test-agent", analysis)
        assert outbox.exists()
        assert outbox.is_dir()

    def test_returns_path(self, tmp_path):
        r = Responder(tmp_path / "outbox")
        analysis = analyze(make_valid_packet())
        path = r.respond("test-agent", analysis)
        assert isinstance(path, Path)
        assert path.exists()

    def test_filename_contains_agent_id(self, tmp_path):
        r = Responder(tmp_path / "outbox", agent_id="hermes")
        analysis = analyze(make_valid_packet())
        path = r.respond("test-agent", analysis)
        assert "hermes" in path.name

    def test_filename_contains_target(self, tmp_path):
        r = Responder(tmp_path / "outbox")
        analysis = analyze(make_valid_packet())
        path = r.respond("lucineer", analysis)
        assert "lucineer" in path.name

    def test_response_is_valid_json(self, tmp_path):
        r = Responder(tmp_path / "outbox")
        analysis = analyze(make_valid_packet())
        path = r.respond("test-agent", analysis)
        with open(path) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_response_has_uscp_structure(self, tmp_path):
        r = Responder(tmp_path / "outbox")
        analysis = analyze(make_valid_packet())
        path = r.respond("test-agent", analysis)
        with open(path) as f:
            data = json.load(f)
        assert "header" in data
        assert "body" in data
        assert "signature" in data

    def test_response_header_origin_is_agent(self, tmp_path):
        r = Responder(tmp_path / "outbox", agent_id="cns-echo")
        analysis = analyze(make_valid_packet())
        path = r.respond("test-agent", analysis)
        with open(path) as f:
            data = json.load(f)
        assert data["header"]["origin_id"] == "cns-echo"

    def test_response_priority_matches_analysis(self, tmp_path):
        r = Responder(tmp_path / "outbox")
        # Use a query → suggested priority should match original
        packet = make_valid_packet(priority="MEDIUM", intent="QUERY")
        analysis = analyze(packet)
        path = r.respond("test-agent", analysis)
        with open(path) as f:
            data = json.load(f)
        assert data["header"]["priority"] == analysis.suggested_priority

    def test_response_intent_matches_analysis(self, tmp_path):
        r = Responder(tmp_path / "outbox")
        packet = make_valid_packet(intent="QUERY")
        analysis = analyze(packet)
        path = r.respond("test-agent", analysis)
        with open(path) as f:
            data = json.load(f)
        assert data["body"]["intent"] == "QUERY_RESPONSE"

    def test_response_payload_has_echo(self, tmp_path):
        r = Responder(tmp_path / "outbox")
        analysis = analyze(make_valid_packet())
        path = r.respond("test-agent", analysis)
        with open(path) as f:
            data = json.load(f)
        assert data["body"]["payload"]["data"]["echo"] is True

    def test_response_checksum_verified(self, tmp_path):
        r = Responder(tmp_path / "outbox")
        analysis = analyze(make_valid_packet())
        path = r.respond("test-agent", analysis)
        with open(path) as f:
            data = json.load(f)
        assert data["signature"]["checksum"] == "verified"
        assert data["signature"]["type"] == "USCP-v1"

    def test_emergency_response(self, tmp_path):
        r = Responder(tmp_path / "outbox")
        packet = make_valid_packet(priority="CRITICAL", intent="EMERGENCY_HALT")
        analysis = analyze(packet)
        path = r.respond("bridge", analysis)
        with open(path) as f:
            data = json.load(f)
        assert data["header"]["priority"] == "CRITICAL"
        assert data["body"]["intent"] == "EMERGENCY_ACK"

    def test_multiple_responses_no_collision(self, tmp_path):
        """Writing multiple responses should not overwrite."""
        r = Responder(tmp_path / "outbox")
        analysis = analyze(make_valid_packet())
        path1 = r.respond("agent-a", analysis)
        path2 = r.respond("agent-b", analysis)
        assert path1 != path2
        assert path1.exists()
        assert path2.exists()

    def test_response_has_timestamp(self, tmp_path):
        r = Responder(tmp_path / "outbox")
        analysis = analyze(make_valid_packet())
        path = r.respond("test-agent", analysis)
        with open(path) as f:
            data = json.load(f)
        ts = data["header"]["timestamp"]
        assert "T" in ts
        # ISO format
        assert ts.count("-") >= 2


class TestBuildPacket:
    def test_build_packet_structure(self, tmp_path):
        r = Responder(tmp_path / "outbox")
        analysis = analyze(make_valid_packet())
        packet = r._build_packet("target", analysis)
        assert "header" in packet
        assert "body" in packet
        assert "signature" in packet

    def test_build_packet_origin(self, tmp_path):
        r = Responder(tmp_path / "outbox", agent_id="echo-1")
        analysis = analyze(make_valid_packet())
        packet = r._build_packet("target", analysis)
        assert packet["header"]["origin_id"] == "echo-1"

    def test_build_packet_sequence_id(self, tmp_path):
        r = Responder(tmp_path / "outbox")
        analysis = analyze(make_valid_packet())
        packet = r._build_packet("target", analysis)
        assert isinstance(packet["header"]["sequence_id"], int)
