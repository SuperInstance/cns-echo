"""Tests for responder statistics tracking."""

import json
import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from cns_echo.responder import Responder
from cns_echo.echo import AnalysisResult


def make_analysis(
    intent: str = "ECHO",
    priority: str = "MEDIUM",
    health: float = 0.9,
) -> AnalysisResult:
    """Create a minimal AnalysisResult for testing."""
    return AnalysisResult(
        health_score=health,
        health_notes=["ok"],
        protocol_checks={"header.origin_id": True},
        protocol_errors=[],
        protocol_warnings=[],
        suggested_intent=intent,
        suggested_priority=priority,
        suggested_payload={"type": "analysis", "data": {}},
        checksum_valid=True,
        received_at="2026-08-05T20:00:00Z",
        processing_time_ms=0.5,
    )


class TestResponderStats:
    def test_initial_stats(self, tmp_path):
        r = Responder(tmp_path / "outbox")
        stats = r.stats
        assert stats["packets_sent"] == 0
        assert stats["packets_by_intent"] == {}
        assert stats["packets_by_priority"] == {}

    def test_stats_after_one_response(self, tmp_path):
        r = Responder(tmp_path / "outbox")
        r.respond("agent-1", make_analysis(intent="ECHO", priority="MEDIUM"))
        stats = r.stats
        assert stats["packets_sent"] == 1
        assert stats["packets_by_intent"]["ECHO"] == 1
        assert stats["packets_by_priority"]["MEDIUM"] == 1

    def test_stats_multiple_packets(self, tmp_path):
        r = Responder(tmp_path / "outbox")
        r.respond("a1", make_analysis(intent="ECHO", priority="LOW"))
        r.respond("a2", make_analysis(intent="HANDSHAKE_COMPLETE", priority="HIGH"))
        r.respond("a3", make_analysis(intent="ECHO", priority="LOW"))
        stats = r.stats
        assert stats["packets_sent"] == 3
        assert stats["packets_by_intent"]["ECHO"] == 2
        assert stats["packets_by_intent"]["HANDSHAKE_COMPLETE"] == 1
        assert stats["packets_by_priority"]["LOW"] == 2
        assert stats["packets_by_priority"]["HIGH"] == 1

    def test_reset_stats(self, tmp_path):
        r = Responder(tmp_path / "outbox")
        r.respond("a1", make_analysis())
        assert r.stats["packets_sent"] == 1
        r.reset_stats()
        stats = r.stats
        assert stats["packets_sent"] == 0
        assert stats["packets_by_intent"] == {}
        assert stats["packets_by_priority"] == {}

    def test_stats_returns_copy(self, tmp_path):
        """stats should return a copy, not the internal dict."""
        r = Responder(tmp_path / "outbox")
        stats1 = r.stats
        stats1["packets_sent"] = 999
        stats2 = r.stats
        assert stats2["packets_sent"] == 0

    def test_different_intents_tracked_separately(self, tmp_path):
        r = Responder(tmp_path / "outbox")
        for intent in ["ECHO", "HANDSHAKE_COMPLETE", "EMERGENCY_ACK", "QUERY_RESPONSE"]:
            r.respond("a", make_analysis(intent=intent))
        stats = r.stats
        assert len(stats["packets_by_intent"]) == 4
        for intent in ["ECHO", "HANDSHAKE_COMPLETE", "EMERGENCY_ACK", "QUERY_RESPONSE"]:
            assert stats["packets_by_intent"][intent] == 1
