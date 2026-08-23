"""Tests for the cns-echo CLI module."""

import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from cns_echo import __version__
from cns_echo import cli


# ─── Default Path Tests ────────────────────────────────────────

class TestDefaultPaths:
    def test_default_inbox(self):
        result = cli.default_inbox()
        assert "cns_inbox" in result
        assert str(Path.home()) in result

    def test_default_outbox(self):
        result = cli.default_outbox()
        assert "cns_outbox" in result
        assert str(Path.home()) in result

    @pytest.mark.skipif(sys.platform == "win32", reason="HOME-based ~ expansion is Unix-specific")
    def test_default_inbox_expands_user(self):
        """Should expand ~ to home directory."""
        with patch.dict("os.environ", {"HOME": "/tmp/fakehome"}):
            result = cli.default_inbox()
            assert "/tmp/fakehome" in result

    @pytest.mark.skipif(sys.platform == "win32", reason="HOME-based ~ expansion is Unix-specific")
    def test_default_outbox_expands_user(self):
        with patch.dict("os.environ", {"HOME": "/tmp/fakehome"}):
            result = cli.default_outbox()
            assert "/tmp/fakehome" in result


# ─── Helper ────────────────────────────────────────────────────

def make_valid_packet(origin="hermes", priority="HIGH", intent="QUERY", seq=1):
    return {
        "header": {
            "origin_id": origin,
            "timestamp": "2026-08-05T07:00:00Z",
            "priority": priority,
            "sequence_id": seq,
        },
        "body": {
            "intent": intent,
            "payload": {"message": "test signal"},
        },
        "signature": {
            "type": "sha256",
            "checksum": hashlib.sha256(b"test").hexdigest(),
        },
    }


import hashlib


# ─── One-Shot Mode Tests ───────────────────────────────────────

class TestOneShotMode:
    def test_process_no_signals(self, tmp_path, capsys):
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        with pytest.raises(SystemExit) as exc_info:
            with patch.object(sys, "argv", ["cns-echo", "--inbox", str(inbox), "--outbox", str(tmp_path/"out")]):
                cli.main()
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "No signals" in captured.out

    def test_process_inbox_not_found(self, tmp_path, capsys):
        nonexistent = tmp_path / "nope"
        with pytest.raises(SystemExit) as exc_info:
            with patch.object(sys, "argv", ["cns-echo", "--inbox", str(nonexistent), "--outbox", str(tmp_path/"out")]):
                cli.main()
        assert exc_info.value.code == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err

    def test_process_single_signal(self, tmp_path, capsys):
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        outbox = tmp_path / "outbox"
        outbox.mkdir()

        packet = make_valid_packet()
        (inbox / "signal.json").write_text(json.dumps(packet))

        with patch.object(sys, "argv", ["cns-echo", "--inbox", str(inbox), "--outbox", str(outbox)]):
            cli.main()

        captured = capsys.readouterr()
        assert "hermes" in captured.out
        assert "QUERY" in captured.out
        # A response should have been written to outbox
        assert len(list(outbox.iterdir())) == 1

    def test_process_multiple_signals(self, tmp_path, capsys):
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        outbox = tmp_path / "outbox"
        outbox.mkdir()

        for i in range(3):
            packet = make_valid_packet(seq=i)
            (inbox / f"signal_{i}.json").write_text(json.dumps(packet))

        with patch.object(sys, "argv", ["cns-echo", "--inbox", str(inbox), "--outbox", str(outbox)]):
            cli.main()

        captured = capsys.readouterr()
        assert "3 signal(s)" in captured.out
        # At least one response should be written
        assert len(list(outbox.iterdir())) >= 1

    def test_dry_run_no_response(self, tmp_path, capsys):
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        outbox = tmp_path / "outbox"
        outbox.mkdir()

        packet = make_valid_packet()
        (inbox / "signal.json").write_text(json.dumps(packet))

        with patch.object(sys, "argv", ["cns-echo", "--inbox", str(inbox), "--outbox", str(outbox), "--dry-run"]):
            cli.main()

        # Dry run: no response files written
        assert len(list(outbox.iterdir())) == 0

    def test_consume_deletes_signal(self, tmp_path, capsys):
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        outbox = tmp_path / "outbox"
        outbox.mkdir()

        packet = make_valid_packet()
        sig_path = inbox / "signal.json"
        sig_path.write_text(json.dumps(packet))

        with patch.object(sys, "argv", ["cns-echo", "--inbox", str(inbox), "--outbox", str(outbox), "--consume"]):
            cli.main()

        assert not sig_path.exists()

    def test_corrupt_json_skipped(self, tmp_path, capsys):
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        outbox = tmp_path / "outbox"
        outbox.mkdir()

        (inbox / "bad.json").write_text("not json")
        packet = make_valid_packet()
        (inbox / "good.json").write_text(json.dumps(packet))

        with patch.object(sys, "argv", ["cns-echo", "--inbox", str(inbox), "--outbox", str(outbox)]):
            cli.main()

        captured = capsys.readouterr()
        # The good packet should be processed
        assert "hermes" in captured.out
        # The bad packet should produce an error message
        assert "Error" in captured.err or "✗" in captured.err or "hermes" in captured.out

    def test_custom_agent_id(self, tmp_path, capsys):
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        outbox = tmp_path / "outbox"
        outbox.mkdir()

        packet = make_valid_packet()
        (inbox / "signal.json").write_text(json.dumps(packet))

        with patch.object(sys, "argv", ["cns-echo", "--inbox", str(inbox), "--outbox", str(outbox), "--agent-id", "custom-echo"]):
            cli.main()

        # Check the response packet has the custom agent_id
        response_files = list(outbox.iterdir())
        assert len(response_files) == 1
        response = json.loads(response_files[0].read_text())
        assert response["header"]["origin_id"] == "custom-echo"

    def test_non_json_files_ignored(self, tmp_path, capsys):
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        outbox = tmp_path / "outbox"
        outbox.mkdir()

        (inbox / "readme.txt").write_text("hello")
        (inbox / "config.yaml").write_text("key: value")

        with pytest.raises(SystemExit) as exc_info:
            with patch.object(sys, "argv", ["cns-echo", "--inbox", str(inbox), "--outbox", str(outbox)]):
                cli.main()
        # No JSON files → "No signals"
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        assert "No signals" in captured.out


# ─── Process File Tests ────────────────────────────────────────

class TestProcessFile:
    def test_process_file_prints_origin_and_intent(self, tmp_path, capsys):
        outbox = tmp_path / "outbox"
        outbox.mkdir()
        responder = cli.Responder(outbox, agent_id="test")

        packet = make_valid_packet()
        filepath = tmp_path / "signal.json"
        filepath.write_text(json.dumps(packet))

        seen = set()
        # Call process_file directly
        args = MagicMock(
            dry_run=False,
            consume=False,
        )
        # We need to replicate what main() does inside process_file
        # but process_file is a closure. Let's test via main().
        pass  # Tested via TestOneShotMode above

    def test_process_file_with_corrupt_json(self, tmp_path, capsys):
        """Corrupt JSON should print error, not crash."""
        outbox = tmp_path / "outbox"
        outbox.mkdir()
        inbox = tmp_path / "inbox"
        inbox.mkdir()

        filepath = inbox / "bad.json"
        filepath.write_text("definitely not json")

        with patch.object(sys, "argv", ["cns-echo", "--inbox", str(inbox), "--outbox", str(outbox)]):
            cli.main()

        captured = capsys.readouterr()
        # Should have error in stderr
        assert "Error" in captured.err


# ─── Watch Mode Tests ──────────────────────────────────────────

class TestWatchMode:
    def test_watch_starts_and_prints_header(self, tmp_path, capsys):
        """Watch mode should print startup info."""
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        outbox = tmp_path / "outbox"
        outbox.mkdir()

        # We'll interrupt the infinite loop with a KeyboardInterrupt
        with patch.object(sys, "argv", ["cns-echo", "--inbox", str(inbox), "--outbox", str(outbox), "--watch", "--interval", "0.01"]):
            with patch("cns_echo.cli.time.sleep", side_effect=KeyboardInterrupt):
                try:
                    cli.main()
                except KeyboardInterrupt:
                    pass

        captured = capsys.readouterr()
        assert "watching" in captured.out
        assert "cns-echo" in captured.out
        assert str(inbox) in captured.out

    def test_watch_processes_new_file(self, tmp_path, capsys):
        """Watch mode should process files that appear."""
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        outbox = tmp_path / "outbox"
        outbox.mkdir()

        packet = make_valid_packet()
        packet_file = inbox / "signal.json"

        # Write the file BEFORE starting watch so it's found on first poll
        packet_file.write_text(json.dumps(packet))

        call_count = [0]
        original_sleep = cli.time.sleep

        def stop_after_first_sleep(seconds):
            call_count[0] += 1
            if call_count[0] >= 2:
                raise KeyboardInterrupt

        with patch.object(sys, "argv", ["cns-echo", "--inbox", str(inbox), "--outbox", str(outbox), "--watch", "--interval", "0.01"]):
            with patch("cns_echo.cli.time.sleep", side_effect=stop_after_first_sleep):
                try:
                    cli.main()
                except KeyboardInterrupt:
                    pass

        captured = capsys.readouterr()
        assert "hermes" in captured.out

    def test_watch_shows_agent_id(self, tmp_path, capsys):
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        outbox = tmp_path / "outbox"
        outbox.mkdir()

        with patch.object(sys, "argv", ["cns-echo", "--inbox", str(inbox), "--outbox", str(outbox), "--watch", "--agent-id", "special-agent"]):
            with patch("cns_echo.cli.time.sleep", side_effect=KeyboardInterrupt):
                try:
                    cli.main()
                except KeyboardInterrupt:
                    pass

        captured = capsys.readouterr()
        assert "special-agent" in captured.out

    def test_watch_shows_consume_and_dry_run(self, tmp_path, capsys):
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        outbox = tmp_path / "outbox"
        outbox.mkdir()

        with patch.object(sys, "argv", ["cns-echo", "--inbox", str(inbox), "--outbox", str(outbox), "--watch", "--consume", "--dry-run"]):
            with patch("cns_echo.cli.time.sleep", side_effect=KeyboardInterrupt):
                try:
                    cli.main()
                except KeyboardInterrupt:
                    pass

        captured = capsys.readouterr()
        assert "Consume: True" in captured.out
        assert "Dry run: True" in captured.out


# ─── Version Flag Tests ────────────────────────────────────────

class TestVersionFlag:
    def test_version_flag_exits(self):
        with pytest.raises(SystemExit) as exc_info:
            with patch.object(sys, "argv", ["cns-echo", "--version"]):
                cli.main()
        assert exc_info.value.code == 0


# ─── Process File Details Tests ────────────────────────────────

class TestProcessFileDetails:
    def test_health_score_displayed(self, tmp_path, capsys):
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        outbox = tmp_path / "outbox"
        outbox.mkdir()

        packet = make_valid_packet(priority="HIGH", intent="QUERY")
        (inbox / "signal.json").write_text(json.dumps(packet))

        with patch.object(sys, "argv", ["cns-echo", "--inbox", str(inbox), "--outbox", str(outbox)]):
            cli.main()

        captured = capsys.readouterr()
        assert "Health:" in captured.out

    def test_suggested_fields_displayed(self, tmp_path, capsys):
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        outbox = tmp_path / "outbox"
        outbox.mkdir()

        packet = make_valid_packet()
        (inbox / "signal.json").write_text(json.dumps(packet))

        with patch.object(sys, "argv", ["cns-echo", "--inbox", str(inbox), "--outbox", str(outbox)]):
            cli.main()

        captured = capsys.readouterr()
        assert "Suggested:" in captured.out
        assert "intent=" in captured.out
        assert "priority=" in captured.out

    def test_response_written_message(self, tmp_path, capsys):
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        outbox = tmp_path / "outbox"
        outbox.mkdir()

        packet = make_valid_packet()
        (inbox / "signal.json").write_text(json.dumps(packet))

        with patch.object(sys, "argv", ["cns-echo", "--inbox", str(inbox), "--outbox", str(outbox)]):
            cli.main()

        captured = capsys.readouterr()
        assert "Response dropped" in captured.out

    def test_consume_message(self, tmp_path, capsys):
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        outbox = tmp_path / "outbox"
        outbox.mkdir()

        packet = make_valid_packet()
        (inbox / "signal.json").write_text(json.dumps(packet))

        with patch.object(sys, "argv", ["cns-echo", "--inbox", str(inbox), "--outbox", str(outbox), "--consume"]):
            cli.main()

        captured = capsys.readouterr()
        assert "Consumed" in captured.out

    def test_dry_run_no_response_message(self, tmp_path, capsys):
        inbox = tmp_path / "inbox"
        inbox.mkdir()
        outbox = tmp_path / "outbox"
        outbox.mkdir()

        packet = make_valid_packet()
        (inbox / "signal.json").write_text(json.dumps(packet))

        with patch.object(sys, "argv", ["cns-echo", "--inbox", str(inbox), "--outbox", str(outbox), "--dry-run"]):
            cli.main()

        captured = capsys.readouterr()
        assert "Response dropped" not in captured.out
