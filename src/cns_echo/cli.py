"""CLI entry point for cns-echo."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from . import __version__
from .echo import analyze
from .echo_space import EchoSpace
from .responder import Responder, ring_priority

# The bus, read as a room — module-level so the watch daemon's whole
# process shares one deadband (the ring is an edge, not a poll).
ECHO_SPACE = EchoSpace("cns-echo-bus")


def default_inbox() -> str:
    return os.path.expanduser("~/.hermes/cns_inbox/")


def default_outbox() -> str:
    return os.path.expanduser("~/.hermes/cns_outbox/")


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="cns-echo",
        description="CNS echo agent — receives USCP signals and responds with analysis.",
    )
    parser.add_argument(
        "--inbox",
        default=default_inbox(),
        help="Path to cns_inbox to watch (default: ~/.hermes/cns_inbox/)",
    )
    parser.add_argument(
        "--outbox",
        default=default_outbox(),
        help="Path to cns_outbox for responses (default: ~/.hermes/cns_outbox/)",
    )
    parser.add_argument(
        "--agent-id",
        default="cns-echo",
        help="Agent identifier in USCP packets (default: cns-echo)",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Continuously watch inbox for new signals and respond",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Poll interval in seconds when --watch (default: 1.0)",
    )
    parser.add_argument(
        "--consume",
        action="store_true",
        help="Consume (delete) inbox signals after processing (default: leave them)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Analyze and print results without writing response packets",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"cns-echo {__version__}",
    )

    args = parser.parse_args()

    inbox = Path(args.inbox)
    outbox = Path(args.outbox)
    responder = Responder(outbox, agent_id=args.agent_id)
    seen: set[str] = set()

    def process_file(filepath: Path) -> None:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                packet = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"  ✗ Error reading {filepath.name}: {e}", file=sys.stderr)
            return

        origin = packet.get("header", {}).get("origin_id", "?")
        intent = packet.get("body", {}).get("intent", "?")
        priority = packet.get("header", {}).get("priority", "?")

        print(f"  ◆ [{priority}] {origin} → {intent}")

        result = analyze(packet)

        # Feed every analyzed packet into the bus-room — the deadband
        # rings when the fleet's mood crosses a threshold.
        ECHO_SPACE.ingest(packet)

        print(f"    Health: {result.health_score:.0%}  |  "
              f"Checks: {sum(result.protocol_checks.values())}/{len(result.protocol_checks)}  |  "
              f"Time: {result.processing_time_ms:.1f}ms")

        if result.protocol_errors:
            for err in result.protocol_errors:
                print(f"    ✗ {err}")
        if result.protocol_warnings:
            for warn in result.protocol_warnings:
                print(f"    ⚠ {warn}")
        for note in result.health_notes:
            print(f"    → {note}")

        print(f"    Suggested: intent={result.suggested_intent}, priority={result.suggested_priority}")

        if not args.dry_run:
            response_path = responder.respond(origin, result)
            print(f"    ✓ Response dropped: {response_path.name}")

        if args.consume:
            filepath.unlink()
            print(f"    ✓ Consumed: {filepath.name}")

        print()

    if args.watch:
        print(f"cns-echo v{__version__} — watching {inbox}")
        print(f"  Agent ID: {args.agent_id}")
        print(f"  Outbox: {outbox}")
        print(f"  Echo space: {ECHO_SPACE.name} (deadband {ECHO_SPACE.deadband})")
        print(f"  Poll interval: {args.interval}s")
        print(f"  Consume: {args.consume}  |  Dry run: {args.dry_run}")
        print()

        while True:
            if inbox.is_dir():
                batch = 0
                for entry in sorted(inbox.iterdir()):
                    if entry.is_file() and entry.suffix == ".json" and entry.name not in seen:
                        seen.add(entry.name)
                        process_file(entry)
                        batch += 1
                if batch:
                    # After each batch: the deadband. One packet per ring
                    # edge (rising only) — not per poll.
                    ring = ECHO_SPACE.deadband_check()
                    if ring is not None:
                        priority = ring_priority(ring)
                        print(f"  🔔 RING [{priority}] {ring.message}")
                        if not args.dry_run:
                            report = responder.respond_ring(ring, ECHO_SPACE.read_field())
                            print(f"    ✓ Status report dropped: {report.name}")
                        print()
            time.sleep(args.interval)
    else:
        # One-shot: process all unread JSON files
        if not inbox.is_dir():
            print(f"Inbox not found: {inbox}", file=sys.stderr)
            sys.exit(1)

        files = sorted(f for f in inbox.iterdir() if f.is_file() and f.suffix == ".json")
        if not files:
            print("No signals in inbox.")
            sys.exit(0)

        print(f"cns-echo v{__version__} — processing {len(files)} signal(s)\n")
        for filepath in files:
            process_file(filepath)


if __name__ == "__main__":
    main()
