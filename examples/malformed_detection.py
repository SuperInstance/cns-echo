"""Example: Detecting malformed and hostile packets.

Shows how cns-echo handles various kinds of bad input:
- Missing required fields
- Unknown priorities and intents
- Invalid checksums
- Completely broken JSON structure

This is the protocol validator use case — run cns-echo against
suspicious traffic to see what's wrong.

Usage:
    python examples/malformed_detection.py
"""

from cns_echo.echo import analyze


def show(label: str, packet: dict) -> None:
    print(f"=== {label} ===")
    result = analyze(packet)
    print(f"  Health: {result.health_score:.0%}")
    if result.protocol_errors:
        for err in result.protocol_errors:
            print(f"  ✗ {err}")
    if result.protocol_warnings:
        for warn in result.protocol_warnings:
            print(f"  ⚠ {warn}")
    print()


# 1. Missing header fields
show("Missing timestamp and sequence_id", {
    "header": {"origin_id": "rogue", "priority": "HIGH"},
    "body": {"intent": "QUERY", "payload": {"type": "text", "data": "hello"}},
    "signature": {"type": "sha256", "checksum": "verified"},
})

# 2. Unknown priority
show("Unknown priority 'ULTRA'", {
    "header": {"origin_id": "rogue", "timestamp": "2026-08-11T08:00:00Z",
               "priority": "ULTRA", "sequence_id": 1},
    "body": {"intent": "QUERY", "payload": {"type": "text", "data": "hello"}},
    "signature": {"type": "sha256", "checksum": "verified"},
})

# 3. Unknown intent
show("Unknown intent 'COMPROMISE_TARGET'", {
    "header": {"origin_id": "rogue", "timestamp": "2026-08-11T08:00:00Z",
               "priority": "CRITICAL", "sequence_id": 1},
    "body": {"intent": "COMPROMISE_TARGET", "payload": {"type": "exploit", "data": {}}},
    "signature": {"type": "sha256", "checksum": "verified"},
})

# 4. Invalid checksum
show("Checksum mismatch", {
    "header": {"origin_id": "rogue", "timestamp": "2026-08-11T08:00:00Z",
               "priority": "LOW", "sequence_id": 1},
    "body": {"intent": "TELEMETRY", "payload": {"type": "reading", "data": {"temp": 42}}},
    "signature": {"type": "sha256", "checksum": "deadbeef"},
})

# 5. Emergency signal
show("Emergency halt signal (legitimate)", {
    "header": {"origin_id": "captain", "timestamp": "2026-08-11T08:00:00Z",
               "priority": "CRITICAL", "sequence_id": 99},
    "body": {"intent": "EMERGENCY_HALT", "payload": {"type": "command", "data": "all stop"}},
    "signature": {"type": "sha256", "checksum": "verified"},
})

print("\nConclusion: cns-echo flags every deviation while still")
print("processing the packet. The health score tells you how")
print("much to trust the signal. Emergency signals get special routing.")
