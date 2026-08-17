"""Tests for EchoSpace — the CNS bus as a room the elephant reads."""

import math

import pytest

from cns_echo.echo_space import (
    EchoSpace,
    Ring,
    HAS_ELEPHANT,
    DEFAULT_DIALS,
)


def make_packet(origin="agent-1", priority="MEDIUM", intent="STATUS_REPORT",
                data="all systems nominal", ptype="status", timestamp=None):
    """Build a minimal USCP-v1 packet."""
    packet = {
        "header": {
            "origin_id": origin,
            "priority": priority,
            "sequence_id": 1,
        },
        "body": {
            "intent": intent,
            "payload": {"type": ptype, "data": data},
        },
        "signature": {"type": "USCP-v1", "checksum": "verified"},
    }
    if timestamp is not None:
        packet["header"]["timestamp"] = timestamp
    return packet


# ─── Room building ──────────────────────────────────────────────

class TestIngestBuildsRoom:
    def test_ingest_returns_self(self):
        space = EchoSpace("cns-bus")
        assert space.ingest(make_packet()) is space

    def test_packet_becomes_message_with_sender(self):
        space = EchoSpace("cns-bus")
        msg = space.packet(make_packet(origin="lucineer-riker"))
        assert msg is not None
        assert msg.author == "lucineer-riker"
        assert "STATUS_REPORT" in msg.text

    def test_room_collects_messages(self):
        space = EchoSpace("cns-bus")
        for i in range(5):
            space.ingest(make_packet(origin=f"agent-{i}"))
        assert len(space.room) == 5
        authors = {m.author for m in space.room.messages}
        assert authors == {f"agent-{i}" for i in range(5)}

    def test_room_property_and_len(self):
        space = EchoSpace("cns-bus")
        space.ingest(make_packet(), make_packet())
        assert len(space) == 2
        assert space.room.name == "cns-bus"

    def test_timestamp_respected(self):
        space = EchoSpace("cns-bus")
        space.ingest(make_packet(timestamp="2026-08-17T00:00:00Z"))
        space.ingest(make_packet(timestamp="2026-08-17T00:01:00Z"))
        t0, t1 = space.room.messages[0].ts, space.room.messages[1].ts
        assert t1 > t0
        assert t1 - t0 == 60.0


# ─── Field reading ─────────────────────────────────────────────

class TestFieldReads:
    def test_read_field_returns_warmth(self):
        space = EchoSpace("cns-bus")
        for i in range(4):
            space.ingest(make_packet(origin=f"a{i}", data="great warm love together"))
        field = space.read_field()
        assert not math.isnan(field.warmth())
        assert not math.isinf(field.warmth())
        assert -1.0 <= field.warmth() <= 1.0

    def test_nine_dials_present(self):
        space = EchoSpace("cns-bus")
        space.ingest(make_packet())
        field = space.read_field()
        names = set(field.readings.keys())
        expected = {"mood", "volume", "earnestness", "cynicism",
                    "joke_landing", "panic", "presence",
                    "model_vs_code", "vision"}
        assert expected <= names
        assert len([d for d in DEFAULT_DIALS]) == 9

    def test_warm_room_reads_warmer_than_cold(self):
        warm = EchoSpace("warm")
        for i in range(6):
            warm.ingest(make_packet(origin=f"a{i}", data="great warm love together fun"))
        cold = EchoSpace("cold")
        for i in range(6):
            cold.ingest(make_packet(origin=f"b{i}",
                                    data="cold dead broke lost fear wrong"))
        assert warm.read_field().warmth() > cold.read_field().warmth()


# ─── Panicked burst ────────────────────────────────────────────

class TestPanickedBurst:
    def test_panicked_burst_reads_cold_and_panicked(self):
        space = EchoSpace("cns-bus")
        for i in range(12):
            space.ingest(make_packet(
                origin=f"agent-{i}",
                priority="CRITICAL",
                intent="EMERGENCY_HALT",
                data="fire flood breach alarm panic evacuate help now",
            ))
        field = space.read_field()
        assert field.readings["panic"] > 0.3
        assert field.warmth() < 0.0

    def test_tint_flags_alarm(self):
        space = EchoSpace("cns-bus")
        for i in range(12):
            space.ingest(make_packet(
                origin=f"agent-{i}", priority="CRITICAL",
                intent="EMERGENCY_HALT",
                data="fire flood breach alarm panic evacuate now",
            ))
        text = space.tint(space.read_field())
        assert "🚨" in text


# ─── Deadband ──────────────────────────────────────────────────

class TestDeadband:
    def test_first_check_establishes_baseline(self):
        space = EchoSpace("cns-bus", deadband=0.25)
        space.ingest(make_packet(data="all systems nominal"))
        assert space.deadband_check() is None

    def test_noise_does_not_ring(self):
        space = EchoSpace("cns-bus", deadband=0.25)
        for _ in range(4):
            space.ingest(make_packet(data="all systems nominal"))
        space.deadband_check()  # baseline
        space.ingest(make_packet(data="all systems nominal"))
        assert space.deadband_check() is None

    def test_panic_shift_rings_down(self):
        space = EchoSpace("cns-bus", deadband=0.2)
        for i in range(6):
            space.ingest(make_packet(origin=f"a{i}", data="great warm love together"))
        space.deadband_check()  # baseline: warm
        for i in range(12):
            space.ingest(make_packet(
                origin=f"p{i}", priority="CRITICAL", intent="EMERGENCY_HALT",
                data="fire flood breach alarm panic evacuate help now",
            ))
        ring = space.deadband_check()
        assert isinstance(ring, Ring)
        assert ring.direction == "down"
        assert ring.is_alarm
        assert ring.metric == "warmth"
        assert "ring" in ring.message.lower()

    def test_warm_shift_rings_up(self):
        space = EchoSpace("cns-bus", deadband=0.2)
        for _ in range(4):
            space.ingest(make_packet(data="all systems nominal"))
        space.deadband_check()  # baseline: neutral
        for i in range(6):
            space.ingest(make_packet(
                origin=f"a{i}",
                data="we felt great — warm and alive, love this, together lol haha",
            ))
        ring = space.deadband_check()
        assert ring is not None
        assert ring.direction == "up"
        assert ring.is_laugh

    def test_ring_does_not_repeat_without_new_shift(self):
        space = EchoSpace("cns-bus", deadband=0.2)
        for _ in range(4):
            space.ingest(make_packet(data="all systems nominal"))
        space.deadband_check()
        for i in range(10):
            space.ingest(make_packet(
                origin=f"p{i}", priority="CRITICAL", intent="EMERGENCY_HALT",
                data="fire flood breach alarm panic evacuate now",
            ))
        assert space.deadband_check() is not None  # rings
        space.ingest(make_packet(priority="CRITICAL", intent="EMERGENCY_HALT",
                                 data="fire alarm panic"))
        assert space.deadband_check() is None  # still cold — no new crossing


# ─── Malformed / NaN guards ────────────────────────────────────

class TestMalformedPackets:
    def test_malformed_inputs_do_not_crash(self):
        space = EchoSpace("cns-bus")
        space.ingest(
            None,
            42,
            3.14,
            "just a string",
            [],
            {},
            {"header": None, "body": None},
            {"header": "broken", "body": 42},
            {"header": {"origin_id": float("nan")}},
        )
        # Non-dict scalars are skipped; dicts (even empty) degrade to messages.
        assert space.skipped >= 3
        field = space.read_field()
        assert not math.isnan(field.warmth())

    def test_nan_payload_sanitized(self):
        space = EchoSpace("cns-bus")
        msg = space.packet(make_packet(
            data={"reading": float("nan"), "temp": float("inf"), "ok": 1.0},
        ))
        assert msg is not None
        assert "nan" not in msg.text.lower()
        assert "inf" not in msg.text.lower()

    def test_empty_room_field_is_finite(self):
        space = EchoSpace("cns-bus")
        field = space.read_field()
        assert math.isfinite(field.warmth())
        assert math.isfinite(field.concentration())

    def test_deadband_never_rings_on_nan_metric(self):
        space = EchoSpace("cns-bus")
        # A metric the field doesn't produce yields 0.0 (finite), not NaN.
        ring = space.deadband_check(metric="nonexistent")
        assert ring is None
