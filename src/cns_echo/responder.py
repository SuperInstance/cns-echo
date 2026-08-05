"""Drops response packets into the CNS outbox for the originating agent."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .echo import AnalysisResult


class Responder:
    """Builds and dispatches USCP response packets."""

    def __init__(self, outbox_path: str | Path, agent_id: str = "cns-echo") -> None:
        self.outbox = Path(outbox_path)
        self.agent_id = agent_id

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

        # Atomic write: temp file then rename
        tmp_path = self.outbox / f".{filename}.tmp"
        final_path = self.outbox / filename

        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(packet, f, indent=2)

        os.rename(str(tmp_path), str(final_path))
        return final_path
