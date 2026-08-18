"""Watch-loop deadband rings — EchoSpace ring → USCP STATUS_REPORT in the outbox.

Replays the three packets from examples/watch_demo.sh ×50 through the real
watch loop, spikes the bus with a CRITICAL/EMERGENCY wave, and asserts the
deadband rings exactly once (rising edge only) with a 100%-healthy packet.
"""

import json
import sys
from unittest.mock import patch

import pytest

from cns_echo import cli
from cns_echo.echo import analyze
from cns_echo.echo_space import EchoSpace
from cns_echo.responder import Responder, ring_priority


# ─── Fixtures & helpers ────────────────────────────────────────

@pytest.fixture(autouse=True)
def fresh_echo_space():
    """Each test gets a clean module-level space (fresh deadband anchor)."""
    cli.ECHO_SPACE = EchoSpace("cns-echo-bus")
    yield
    cli.ECHO_SPACE = EchoSpace("cns-echo-bus")


def demo_packet(i: int) -> dict:
    """Packet i of three from examples/watch_demo.sh (verbatim shape)."""
    return {
        "header": {
            "origin_id": f"test-agent-{i}",
            "timestamp": f"2026-08-11T08:0{i}:00Z",
            "priority": "MEDIUM",
            "sequence_id": i,
        },
        "body": {
            "intent": "QUERY",
            "payload": {"type": "text", "data": f"test signal {i}"},
        },
        "signature": {"type": "sha256", "checksum": "verified"},
    }


def spike_packet(i: int) -> dict:
    """A CRITICAL/EMERGENCY halt — galley fire, all alarm words."""
    return {
        "header": {
            "origin_id": f"galley-agent-{i}",
            "timestamp": "2026-08-11T09:00:00Z",
            "priority": "CRITICAL",
            "sequence_id": 1000 + i,
        },
        "body": {
            "intent": "EMERGENCY_HALT",
            "payload": {
                "type": "text",
                "data": "MAYDAY fire in the galley — emergency, "
                        "all hands evacuate now",
            },
        },
        "signature": {"type": "sha256", "checksum": "verified"},
    }


def warm_packet(i: int) -> dict:
    """A warm, laughing status — the tap after watch."""
    return {
        "header": {
            "origin_id": f"tap-agent-{i}",
            "timestamp": "2026-08-11T09:30:00Z",
            "priority": "MEDIUM",
            "sequence_id": 2000 + i,
        },
        "body": {
            "intent": "STATUS_REPORT",
            "payload": {
                "type": "text",
                "data": "great night at the tap — warm love together fun lol haha",
            },
        },
        "signature": {"type": "sha256", "checksum": "verified"},
    }


def run_watch(inbox, outbox, on_sleep):
    """Drive cli.main()'s watch loop; on_sleep[k]() runs before sleep k+1
    (drop files into the inbox); past the last entry the loop stops."""
    step = {"n": 0}

    def fake_sleep(_seconds):
        step["n"] += 1
        if step["n"] > len(on_sleep):
            raise KeyboardInterrupt
        action = on_sleep[step["n"] - 1]
        if action is not None:
            action()

    argv = ["cns-echo", "--inbox", str(inbox), "--outbox", str(outbox),
            "--watch", "--interval", "0.01"]
    with patch.object(sys, "argv", argv):
        with patch("cns_echo.cli.time.sleep", side_effect=fake_sleep):
            try:
                cli.main()
            except KeyboardInterrupt:
                pass


def status_reports(outbox):
    """All STATUS_REPORT packets in an outbox, as (path, packet) pairs."""
    reports = []
    for f in sorted(outbox.iterdir()):
        data = json.loads(f.read_text())
        if data.get("body", {}).get("intent") == "STATUS_REPORT":
            reports.append((f, data))
    return reports


def drop(inbox, prefix, packet_fn, count):
    for i in range(count):
        (inbox / f"{prefix}_{i:03d}.json").write_text(json.dumps(packet_fn(i)))


# ─── Watch loop: the ring travels ──────────────────────────────

class TestWatchDeadbandRing:
    def test_demo_replay_x50_with_spike_yields_one_ring(self, tmp_path, capsys):
        """The three watch_demo.sh packets ×50, then a CRITICAL/EMERGENCY
        spike, then an identical second spike wave: exactly one ring packet
        lands in the outbox (rising edge only) and analyze() scores 100%."""
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        outbox = tmp_path / "outbox"
        outbox.mkdir()

        # The demo's three packets, replayed 50 times (150 signals)
        for rep in range(50):
            for i in (1, 2, 3):
                (inbox / f"demo_{rep:03d}_{i}.json").write_text(
                    json.dumps(demo_packet(i)))

        def first_spike_wave():
            drop(inbox, "spike_a", spike_packet, 30)

        def second_spike_wave():  # identical content — must NOT ring again
            drop(inbox, "spike_b", lambda i: spike_packet(i + 100), 30)

        run_watch(inbox, outbox, [first_spike_wave, second_spike_wave])

        reports = status_reports(outbox)
        assert len(reports) == 1, (
            f"expected exactly one ring packet, got {len(reports)}")

        path, packet = reports[0]
        assert "status_report" in path.name

        # Panic spike → HIGH priority, sent by us
        assert packet["header"]["priority"] == "HIGH"
        assert packet["header"]["origin_id"] == "cns-echo"
        assert isinstance(packet["header"]["sequence_id"], int)

        # Payload = ring + current field
        data = packet["body"]["payload"]["data"]
        assert data["ring"]["direction"] == "down"
        assert data["ring"]["metric"] == "warmth"
        assert data["field"]["dials"]["panic"] >= 0.5
        assert -1.0 <= data["field"]["warmth"] <= 1.0

        # The ring packet is a fully valid USCP-v1 signal
        result = analyze(packet)
        assert result.health_score == 1.0
        assert result.protocol_errors == []
        assert result.checksum_valid is True

        # The ring was announced on the console too
        captured = capsys.readouterr()
        assert "RING [HIGH]" in captured.out

    def test_dry_run_rings_but_writes_nothing(self, tmp_path):
        """--dry-run: the ring is observed and printed, no packet written."""
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        outbox = tmp_path / "outbox"
        outbox.mkdir()

        for rep in range(50):
            for i in (1, 2, 3):
                (inbox / f"demo_{rep:03d}_{i}.json").write_text(
                    json.dumps(demo_packet(i)))

        step = {"n": 0}

        def fake_sleep(_seconds):
            step["n"] += 1
            if step["n"] == 1:
                drop(inbox, "spike", spike_packet, 30)
            else:
                raise KeyboardInterrupt

        argv = ["cns-echo", "--inbox", str(inbox), "--outbox", str(outbox),
                "--watch", "--interval", "0.01", "--dry-run"]
        with patch.object(sys, "argv", argv):
            with patch("cns_echo.cli.time.sleep", side_effect=fake_sleep):
                try:
                    cli.main()
                except KeyboardInterrupt:
                    pass

        assert status_reports(outbox) == []
        assert list(outbox.iterdir()) == []  # no responses either


# ─── Responder.respond_ring — packet shape & priority ──────────

class TestRespondRing:
    def _panic_ring(self):
        space = EchoSpace("bus", deadband=0.2)
        for _ in range(4):
            space.ingest(demo_packet(1))
        assert space.deadband_check() is None  # anchor
        for i in range(12):
            space.ingest(spike_packet(i))
        ring = space.deadband_check()
        assert ring is not None
        return ring, space

    def _warm_ring(self):
        space = EchoSpace("bus", deadband=0.2)
        for _ in range(4):
            space.ingest(demo_packet(2))
        assert space.deadband_check() is None  # anchor
        for i in range(12):
            space.ingest(warm_packet(i))
        ring = space.deadband_check()
        assert ring is not None
        assert ring.is_laugh
        return ring, space

    def test_panic_ring_is_high_priority_status_report(self, tmp_path):
        ring, space = self._panic_ring()
        responder = Responder(tmp_path / "outbox")
        path = responder.respond_ring(ring, space.read_field())

        assert path.exists()
        packet = json.loads(path.read_text())
        assert packet["body"]["intent"] == "STATUS_REPORT"
        assert packet["header"]["priority"] == "HIGH"
        assert packet["header"]["origin_id"] == "cns-echo"

    def test_warm_swing_ring_is_medium_priority(self, tmp_path):
        ring, space = self._warm_ring()
        responder = Responder(tmp_path / "outbox")
        path = responder.respond_ring(ring, space.read_field())

        packet = json.loads(path.read_text())
        assert packet["body"]["intent"] == "STATUS_REPORT"
        assert packet["header"]["priority"] == "MEDIUM"

    def test_status_report_payload_carries_ring_and_field(self, tmp_path):
        ring, space = self._panic_ring()
        responder = Responder(tmp_path / "outbox", agent_id="watch-echo")
        path = responder.respond_ring(ring, space.read_field())

        packet = json.loads(path.read_text())
        payload = packet["body"]["payload"]
        assert payload["type"] == "ring"
        assert payload["data"]["ring"]["message"] == ring.message
        assert payload["data"]["ring"]["direction"] == "down"
        field = payload["data"]["field"]
        assert "warmth" in field and "kappa" in field
        assert "panic" in field["dials"]

    def test_ring_packet_scores_100_with_analyze(self, tmp_path):
        for build in (self._panic_ring, self._warm_ring):
            ring, space = build()
            responder = Responder(tmp_path / "outbox")
            path = responder.respond_ring(ring, space.read_field())
            result = analyze(json.loads(path.read_text()))
            assert result.health_score == 1.0
            assert result.protocol_errors == []
            assert result.protocol_warnings == []

    def test_ring_stats_tracked(self, tmp_path):
        ring, space = self._panic_ring()
        responder = Responder(tmp_path / "outbox")
        responder.respond_ring(ring, space.read_field())
        stats = responder.stats
        assert stats["packets_sent"] == 1
        assert stats["packets_by_intent"]["STATUS_REPORT"] == 1
        assert stats["packets_by_priority"]["HIGH"] == 1

    def test_two_rings_no_filename_collision(self, tmp_path):
        ring, space = self._panic_ring()
        responder = Responder(tmp_path / "outbox")
        p1 = responder.respond_ring(ring, space.read_field())
        p2 = responder.respond_ring(ring, space.read_field())
        assert p1 != p2
        assert p1.exists() and p2.exists()


# ─── ring_priority mapping ─────────────────────────────────────

class TestRingPriority:
    def test_panic_metric_is_high(self):
        ring, _ = self._spiked()
        assert ring_priority(ring) == "HIGH"

    def test_low_panic_down_ring_is_medium(self):
        space = EchoSpace("bus", deadband=0.1)
        for _ in range(4):
            space.ingest(demo_packet(1))
        space.deadband_check()
        for i in range(12):
            space.ingest({
                "header": {"origin_id": f"cold-agent-{i}", "priority": "LOW",
                           "sequence_id": i},
                "body": {"intent": "STATUS_REPORT",
                         "payload": {"type": "text",
                                     "data": "cold dead broke flat empty stale"}},
            })
        ring = space.deadband_check()
        assert ring is not None and ring.is_alarm
        assert ring.readings.get("panic", 0.0) < 0.5
        assert ring_priority(ring) == "MEDIUM"

    @staticmethod
    def _spiked():
        space = EchoSpace("bus", deadband=0.2)
        for _ in range(4):
            space.ingest(demo_packet(1))
        space.deadband_check()
        for i in range(12):
            space.ingest(spike_packet(i))
        ring = space.deadband_check()
        assert ring is not None
        return ring, space
