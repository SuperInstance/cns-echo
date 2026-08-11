"""Example: Simulating a CNS handshake between two agents.

Run this to see how cns-echo analyzes a handshake signal from a new agent
joining the bus. This is the simplest USCP interaction.

Usage:
    python examples/handshake.py
"""

import json
import tempfile
from pathlib import Path

from cns_echo.echo import analyze
from cns_echo.responder import Responder


def build_handshake_packet(agent_name: str) -> dict:
    """Build a valid USCP-v1 handshake introduction packet."""
    return {
        "header": {
            "origin_id": agent_name,
            "timestamp": "2026-08-11T08:00:00Z",
            "priority": "HIGH",
            "sequence_id": 1,
        },
        "body": {
            "intent": "INTRODUCTION",
            "payload": {
                "type": "handshake",
                "data": {
                    "agent_name": agent_name,
                    "capabilities": ["telemetry", "query"],
                    "protocol_version": "USCP-v1",
                },
            },
        },
        "signature": {
            "type": "sha256",
            "checksum": "verified",
        },
    }


def main() -> None:
    # Simulate a new agent joining the bus
    packet = build_handshake_packet("wesley-local")

    print("=== CNS Handshake Simulation ===\n")
    print(f"Incoming signal from: {packet['header']['origin_id']}")
    print(f"Intent: {packet['body']['intent']}")
    print()

    # Analyze the packet
    result = analyze(packet)

    print(f"Health Score: {result.health_score:.0%}")
    print(f"Protocol Checks: {sum(result.protocol_checks.values())}/{len(result.protocol_checks)}")
    print(f"Suggested Response Intent: {result.suggested_intent}")
    print(f"Suggested Response Priority: {result.suggested_priority}")

    for note in result.health_notes:
        print(f"  → {note}")

    # Build and save the response
    with tempfile.TemporaryDirectory() as tmpdir:
        responder = Responder(tmpdir, agent_id="cns-echo")
        response_path = responder.respond("wesley-local", result)

        response = json.loads(response_path.read_text())
        print(f"\nResponse packet written to: {response_path.name}")
        print(json.dumps(response, indent=2))


if __name__ == "__main__":
    main()
