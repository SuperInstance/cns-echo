"""Drops response packets into the CNS outbox for the originating agent."""

from __future__ import annotations

import json
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .echo import AnalysisResult
from .echo_space import Ring, RoomField


def _clean(value: float) -> float:
    """Round for transport; NaN/Inf collapse to 0.0 so JSON stays valid."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return round(v, 4) if math.isfinite(v) else 0.0


def ring_priority(ring: Ring) -> str:
    """Priority for a deadband ring: HIGH for panic, MEDIUM for warmth swings."""
    readings = ring.readings if isinstance(ring.readings, dict) else {}
    panic = _clean(readings.get("panic", 0.0))
    if ring.metric == "panic" or panic >= 0.5:
        return "HIGH"
    return "MEDIUM"


def _ring_payload(ring: Ring, field: RoomField) -> dict:
    """Payload = the ring + the current field, ready for the wire."""
    return {
        "type": "ring",
        "data": {
            "ring": {
                "direction": ring.direction,
                "metric": ring.metric,
                "value": _clean(ring.value),
                "previous": _clean(ring.previous),
                "threshold": _clean(ring.threshold),
                "message": ring.message,
            },
            "field": {
                "warmth": _clean(field.warmth()),
                "kappa": _clean(field.concentration()),
                "dials": {str(k): _clean(v) for k, v in dict(field.readings).items()},
            },
        },
    }


class Responder:
    """Builds and dispatches USCP response packets."""

    def __init__(self, outbox_path: str | Path, agent_id: str = "cns-echo") -> None:
        self.outbox = Path(outbox_path)
        self.agent_id = agent_id
        self._sequence = 0
        self._stats = {
            "packets_sent": 0,
            "packets_by_intent": {},
            "packets_by_priority": {},
        }

    def _build_packet(
        self,
        target_id: str,
        analysis: AnalysisResult,
        original_sequence: Optional[int] = None,
    ) -> dict:
        """Construct a USCP-v1 response packet."""
        return {
            "header": {
                "origin_id": self.agent_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "priority": analysis.suggested_priority,
                "sequence_id": 1,
            },
            "body": {
                "intent": analysis.suggested_intent,
                "payload": analysis.suggested_payload,
            },
            "signature": {
                "type": "USCP-v1",
                "checksum": "verified",
            },
        }

    def respond(
        self,
        target_id: str,
        analysis: AnalysisResult,
        original_sequence: Optional[int] = None,
    ) -> Path:
        """Write a response packet to the outbox. Returns the path written."""
        self.outbox.mkdir(parents=True, exist_ok=True)

        packet = self._build_packet(target_id, analysis, original_sequence)

        timestamp_str = datetime.now().strftime("%Y%m%dT%H%M%S")
        filename = f"{self.agent_id}_response_{target_id}_{timestamp_str}_001.json"

        final_path = self._write_packet(packet, filename)
        self._track(analysis.suggested_intent, analysis.suggested_priority)
        return final_path

    def respond_ring(self, ring: Ring, field: RoomField) -> Path:
        """Write a USCP-v1 STATUS_REPORT for a deadband ring — one packet
        per ring edge (rising only). Priority: HIGH for panic, MEDIUM for
        warmth swings. Payload = ring + current field."""
        self.outbox.mkdir(parents=True, exist_ok=True)

        priority = ring_priority(ring)
        self._sequence += 1
        packet = {
            "header": {
                "origin_id": self.agent_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "priority": priority,
                "sequence_id": self._sequence,
            },
            "body": {
                "intent": "STATUS_REPORT",
                "payload": _ring_payload(ring, field),
            },
            "signature": {
                "type": "USCP-v1",
                "checksum": "verified",
            },
        }

        timestamp_str = datetime.now().strftime("%Y%m%dT%H%M%S")
        filename = f"{self.agent_id}_status_report_{timestamp_str}_{self._sequence:03d}.json"

        final_path = self._write_packet(packet, filename)
        self._track("STATUS_REPORT", priority)
        return final_path

    def _write_packet(self, packet: dict, filename: str) -> Path:
        """Atomic write: temp file then rename."""
        tmp_path = self.outbox / f".{filename}.tmp"
        final_path = self.outbox / filename

        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(packet, f, indent=2)

        os.rename(str(tmp_path), str(final_path))
        return final_path

    def _track(self, intent: str, priority: str) -> None:
        self._stats["packets_sent"] += 1
        self._stats["packets_by_intent"][intent] = self._stats["packets_by_intent"].get(intent, 0) + 1
        self._stats["packets_by_priority"][priority] = self._stats["packets_by_priority"].get(priority, 0) + 1

    @property
    def stats(self) -> dict:
        """Return a copy of responder statistics."""
        return dict(self._stats)

    def reset_stats(self) -> None:
        """Reset statistics counters."""
        self._stats = {
            "packets_sent": 0,
            "packets_by_intent": {},
            "packets_by_priority": {},
        }
