"""FieldHistory + --mood-log — the fleet's EKG strip.

`EchoSpace` keeps a bounded rolling `FieldHistory`: a deque windowed at
`window` packets per entry, holding at most `max_windows` entries —
bounded by law, like every elephant window. With `--mood-log`, watch
mode appends one JSON line per committed window to `fleet-mood.jsonl`,
so every agent on the bus can read the fleet's mood as a file; the EKG
strip is the timeline.
"""

import json
import sys
from unittest.mock import patch

import pytest

from cns_echo import cli
from cns_echo.echo_space import EchoSpace, FieldEntry, FieldHistory


# ─── Fixtures & helpers ────────────────────────────────────────

@pytest.fixture(autouse=True)
def fresh_echo_space():
    """Each test gets a clean module-level space (fresh history)."""
    cli.ECHO_SPACE = EchoSpace("cns-echo-bus")
    yield
    cli.ECHO_SPACE = EchoSpace("cns-echo-bus")


def bus_packet(i: int, data: str = "all systems nominal") -> dict:
    """A minimal well-formed USCP packet (watch_demo.sh shape). No header
    timestamp, so the space's auto clock spaces messages 60s apart."""
    return {
        "header": {
            "origin_id": f"agent-{i}",
            "priority": "MEDIUM",
            "sequence_id": i,
        },
        "body": {
            "intent": "STATUS_REPORT",
            "payload": {"type": "text", "data": data},
        },
        "signature": {"type": "sha256", "checksum": "verified"},
    }


def run_watch(argv, polls: int = 2):
    """Drive cli.main()'s watch loop for `polls` sleeps, then stop."""
    step = {"n": 0}

    def fake_sleep(_seconds):
        step["n"] += 1
        if step["n"] > polls:
            raise KeyboardInterrupt

    with patch.object(sys, "argv", argv):
        with patch("cns_echo.cli.time.sleep", side_effect=fake_sleep):
            try:
                cli.main()
            except KeyboardInterrupt:
                pass


# ─── Bounded rolling history — the deque is law ────────────────

class TestHistoryBounded:
    def test_ten_thousand_packets_bounded_one_line_per_window(self, tmp_path):
        """10k packets, window=100 → 100 windows close: the deque never
        exceeds max_windows (bounded by law) while the mood log records
        exactly one line per window — the file is the timeline."""
        mood_log = tmp_path / "fleet-mood.jsonl"
        space = EchoSpace("cns-echo-bus", window=100, max_windows=50,
                          mood_log=mood_log)
        space.ingest(*[bus_packet(i) for i in range(10_000)])

        history = space.history
        assert history.total_windows == 100              # 10k / window
        assert len(history) == history.max_windows == 50  # bounded
        assert [e.window for e in history] == list(range(51, 101))

        lines = mood_log.read_text().splitlines()
        assert len(lines) == 100                          # one per window
        windows = [json.loads(line)["window"] for line in lines]
        assert windows == list(range(1, 101))
        assert space.history.lines_written == 100

    def test_partial_window_commits_nothing(self):
        space = EchoSpace("bus", window=10, max_windows=5)
        space.ingest(*[bus_packet(i) for i in range(9)])
        assert space.history.total_windows == 0
        assert len(space.history) == 0
        assert space.history.latest is None

    def test_window_closes_across_batches(self, tmp_path):
        mood_log = tmp_path / "mood.jsonl"
        space = EchoSpace("bus", window=10, mood_log=mood_log)
        space.ingest(*[bus_packet(i) for i in range(7)])
        assert not mood_log.exists()  # no window closed yet
        space.ingest(*[bus_packet(i) for i in range(7, 13)])  # 13 total
        assert space.history.total_windows == 1
        assert len(mood_log.read_text().splitlines()) == 1

    def test_deque_keeps_the_newest_windows(self):
        space = EchoSpace("bus", window=10, max_windows=3)
        space.ingest(*[bus_packet(i) for i in range(50)])
        assert space.history.total_windows == 5
        assert [e.window for e in space.history] == [3, 4, 5]

    def test_malformed_packets_do_not_advance_the_window(self):
        space = EchoSpace("bus", window=5, max_windows=2)
        space.ingest(None, 42, 3.5, bus_packet(1), bus_packet(2))
        assert space.skipped == 3
        assert space.history.total_windows == 0

    def test_packet_method_feeds_history_too(self):
        space = EchoSpace("bus", window=3, max_windows=2)
        for i in range(7):
            assert space.packet(bus_packet(i)) is not None
        assert space.history.total_windows == 2


# ─── FieldEntry — one beat of the strip ─────────────────────────

class TestFieldEntry:
    def test_entry_shape_and_json(self):
        space = EchoSpace("cns-echo-bus", window=5)
        space.ingest(*[bus_packet(i, data="great warm love together")
                       for i in range(5)])
        entry = space.history.latest
        assert isinstance(entry, FieldEntry)
        assert entry.window == 1
        assert entry.packets == 5
        assert -1.0 <= entry.warmth <= 1.0
        assert entry.kappa >= 0.0
        assert "mood" in entry.readings and "panic" in entry.readings

        as_json = entry.to_json()
        json.dumps(as_json)  # fully serializable, no NaN/Inf
        assert as_json["window"] == 1
        assert set(as_json) == {"window", "ts", "packets", "warmth",
                                "kappa", "dials"}

    def test_history_standalone_feed(self):
        """FieldHistory works without an EchoSpace — feed + snapshot."""
        history = FieldHistory(window=2, max_windows=2)
        committed = history.feed(5, lambda: {"packets": 5, "warmth": 0.1,
                                             "kappa": 0.9,
                                             "readings": {"mood": 0.5}})
        assert [e.window for e in committed] == [1, 2]
        assert len(history) == 2
        assert history.total_windows == 2


# ─── The mood log — every agent reads the fleet's mood ──────────

class TestMoodLog:
    def test_lines_are_valid_json_one_per_window(self, tmp_path):
        mood_log = tmp_path / "fleet-mood.jsonl"
        space = EchoSpace("cns-echo-bus", window=25, mood_log=mood_log)
        for c in range(4):  # one batch per window — the timeline grows
            space.ingest(*[bus_packet(c * 25 + j) for j in range(25)])

        lines = mood_log.read_text().splitlines()
        assert len(lines) == 4
        for k, line in enumerate(lines, start=1):
            entry = json.loads(line)
            assert entry["window"] == k
            assert entry["space"] == "cns-echo-bus"
            assert entry["packets"] == 25 * k
            assert -1.0 <= entry["warmth"] <= 1.0
            assert entry["kappa"] >= 0.0
            assert "mood" in entry["dials"] and "panic" in entry["dials"]

    def test_appends_never_truncates(self, tmp_path):
        mood_log = tmp_path / "fleet-mood.jsonl"
        space = EchoSpace("bus", window=5, mood_log=mood_log)
        space.ingest(*[bus_packet(i) for i in range(5)])
        space.ingest(*[bus_packet(i) for i in range(5, 10)])
        space.ingest(*[bus_packet(i) for i in range(10, 15)])
        lines = mood_log.read_text().splitlines()
        assert [json.loads(line)["window"] for line in lines] == [1, 2, 3]

    def test_no_mood_log_by_default(self, tmp_path):
        space = EchoSpace("bus", window=5)
        space.ingest(*[bus_packet(i) for i in range(10)])
        assert space.history.mood_log is None
        assert space.history.lines_written == 0
        assert list(tmp_path.iterdir()) == []

    def test_unwritable_log_never_kills_the_bus(self):
        space = EchoSpace("bus", window=2, mood_log="/nonexistent-dir/mood.jsonl")
        space.ingest(*[bus_packet(i) for i in range(4)])  # windows close
        assert space.history.log_errors >= 1
        assert space.history.mood_log is None  # logging stood down
        assert len(space) == 4                 # the bus kept ingesting


# ─── --mood-log on the CLI — watch mode writes the strip ────────

class TestWatchMoodLog:
    def test_watch_appends_one_line_per_window(self, tmp_path, capsys):
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        outbox = tmp_path / "outbox"
        outbox.mkdir()
        mood_log = tmp_path / "fleet-mood.jsonl"

        for i in range(15):
            (inbox / f"sig_{i:03d}.json").write_text(json.dumps(bus_packet(i)))

        cli.ECHO_SPACE.history.window = 10  # small windows for the test

        run_watch(["cns-echo", "--inbox", str(inbox), "--outbox", str(outbox),
                   "--watch", "--interval", "0.01",
                   "--mood-log", str(mood_log)])

        lines = mood_log.read_text().splitlines()
        assert len(lines) == 1  # 15 packets, window 10 → one window closed
        entry = json.loads(lines[0])
        assert entry["window"] == 1
        assert entry["packets"] == 10
        assert entry["space"] == "cns-echo-bus"

        assert "Mood log" in capsys.readouterr().out

    def test_bare_flag_defaults_to_fleet_mood_jsonl(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        outbox = tmp_path / "outbox"
        outbox.mkdir()

        for i in range(10):
            (inbox / f"sig_{i:03d}.json").write_text(json.dumps(bus_packet(i)))

        cli.ECHO_SPACE.history.window = 5

        run_watch(["cns-echo", "--inbox", str(inbox), "--outbox", str(outbox),
                   "--watch", "--interval", "0.01", "--mood-log"])

        strip = tmp_path / "fleet-mood.jsonl"
        assert strip.exists()
        assert len(strip.read_text().splitlines()) == 2  # 10 / 5

    def test_no_mood_log_flag_writes_nothing(self, tmp_path):
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        outbox = tmp_path / "outbox"
        outbox.mkdir()

        for i in range(10):
            (inbox / f"sig_{i:03d}.json").write_text(json.dumps(bus_packet(i)))

        cli.ECHO_SPACE.history.window = 5

        run_watch(["cns-echo", "--inbox", str(inbox), "--outbox", str(outbox),
                   "--watch", "--interval", "0.01"])

        assert list(tmp_path.glob("*.jsonl")) == []
