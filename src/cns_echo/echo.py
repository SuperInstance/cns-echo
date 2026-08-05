"""Analyzes incoming USCP packets for signal health, protocol compliance, and suggested responses."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from typing import Optional


# Valid values per the USCP spec
VALID_PRIORITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
VALID_INTENTS = {
    "EXECUTE_PLAN",
    "SENSORY_DATA",
    "REQUEST_REASONING",
    "HANDSHAKE_COMPLETE",
    "EMERGENCY_HALT",
    "INTRODUCTION",
    "QUERY",
    "STATUS_REPORT",
    "TELEMETRY",
    "ARTIFACT_SHARE",
}
REQUIRED_HEADER_FIELDS = {"origin_id", "timestamp", "priority", "sequence_id"}
REQUIRED_BODY_FIELDS = {"intent", "payload"}
REQUIRED_SIGNATURE_FIELDS = {"type", "checksum"}


@dataclass
class AnalysisResult:
    """Analysis of a USCP packet."""

    # Signal health: 0.0 (broken) to 1.0 (perfect)
    health_score: float
    health_notes: list[str]

    # Protocol compliance checks
    protocol_checks: dict[str, bool]
    protocol_errors: list[str]
    protocol_warnings: list[str]

    # Suggested response
    suggested_intent: str
    suggested_priority: str
    suggested_payload: dict

    # Checksum verification
    checksum_valid: bool

    # Timing
    received_at: str
    processing_time_ms: float


def _verify_checksum(packet: dict) -> bool:
    """Verify packet checksum. USCP-v1 uses a simple convention —
    if checksum is 'verified' or matches a content hash, accept it."""
    sig = packet.get("signature", {})
    checksum = sig.get("checksum", "")

    if not checksum:
        return False

    if checksum in ("verified", "handshake-verified"):
        return True

    # Content hash verification: recompute sha256 of header+body
    header = packet.get("header", {})
    body = packet.get("body", {})
    content = json.dumps({"header": header, "body": body}, sort_keys=True)
    computed = hashlib.sha256(content.encode()).hexdigest()[:16]
    return computed == checksum


def analyze(packet: dict) -> AnalysisResult:
    """Analyze a USCP packet and return structured results."""
    start = time.perf_counter()
    errors: list[str] = []
    warnings: list[str] = []
    checks: dict[str, bool] = {}
    notes: list[str] = []

    header = packet.get("header", {})
    body = packet.get("body", {})
    sig = packet.get("signature", {})

    # --- Header checks ---
    for field in REQUIRED_HEADER_FIELDS:
        present = field in header and header[field] is not None
        checks[f"header.{field}"] = present
        if not present:
            errors.append(f"Missing required header field: {field}")

    # Priority validation
    priority = header.get("priority", "")
    priority_valid = priority in VALID_PRIORITIES
    checks["header.priority_valid"] = priority_valid
    if priority and not priority_valid:
        warnings.append(f"Unknown priority '{priority}' (expected one of {VALID_PRIORITIES})")

    # Sequence ID should be a positive integer
    seq = header.get("sequence_id")
    checks["header.sequence_id_type"] = isinstance(seq, int)
    if seq is not None and not isinstance(seq, int):
        warnings.append(f"sequence_id should be integer, got {type(seq).__name__}")

    # --- Body checks ---
    for field in REQUIRED_BODY_FIELDS:
        present = field in body
        checks[f"body.{field}"] = present
        if not present:
            errors.append(f"Missing required body field: {field}")

    intent = body.get("intent", "")
    intent_known = intent in VALID_INTENTS
    checks["body.intent_known"] = intent_known
    if intent and not intent_known:
        warnings.append(f"Unknown intent '{intent}' — not in standard set")

    payload = body.get("payload", {})
    checks["body.payload_has_type"] = isinstance(payload.get("type"), str) if payload else False
    checks["body.payload_has_data"] = "data" in payload if payload else False

    # --- Signature checks ---
    for field in REQUIRED_SIGNATURE_FIELDS:
        present = field in sig
        checks[f"signature.{field}"] = present
        if not present:
            errors.append(f"Missing signature field: {field}")

    checksum_valid = _verify_checksum(packet)
    checks["signature.checksum_valid"] = checksum_valid
    if not checksum_valid:
        warnings.append("Checksum verification failed")

    # --- Health score ---
    total_checks = len(checks)
    passed = sum(1 for v in checks.values() if v)
    health_score = passed / total_checks if total_checks > 0 else 0.0

    if health_score >= 0.9:
        notes.append("Signal is healthy and protocol-compliant")
    elif health_score >= 0.7:
        notes.append("Signal mostly compliant — minor issues detected")
    else:
        notes.append("Signal has significant protocol deviations")

    # --- Emergency detection ---
    is_emergency = priority == "CRITICAL" or intent == "EMERGENCY_HALT"
    if is_emergency:
        notes.append("⚠ EMERGENCY signal detected — immediate attention required")
        suggested_intent = "EMERGENCY_ACK"
        suggested_priority = "CRITICAL"
    elif intent == "INTRODUCTION" or intent == "HANDSHAKE_COMPLETE":
        suggested_intent = "HANDSHAKE_COMPLETE"
        suggested_priority = "HIGH"
        notes.append("Handshake signal — responding with synchronization confirmation")
    elif intent == "REQUEST_REASONING":
        suggested_intent = "REASONING_RESPONSE"
        suggested_priority = priority or "MEDIUM"
    elif intent == "QUERY":
        suggested_intent = "QUERY_RESPONSE"
        suggested_priority = priority or "MEDIUM"
    elif intent == "TELEMETRY" or intent == "SENSORY_DATA":
        suggested_intent = "TELEMETRY_ACK"
        suggested_priority = "LOW"
    else:
        suggested_intent = "ECHO"
        suggested_priority = priority or "MEDIUM"

    suggested_payload = {
        "type": "analysis",
        "data": {
            "echo": True,
            "original_intent": intent,
            "original_origin": header.get("origin_id", "?"),
            "health_score": round(health_score, 2),
            "protocol_errors": errors,
            "warnings": warnings,
            "notes": notes,
            "agent": "cns-echo",
        },
    }

    elapsed = (time.perf_counter() - start) * 1000

    return AnalysisResult(
        health_score=health_score,
        health_notes=notes,
        protocol_checks=checks,
        protocol_errors=errors,
        protocol_warnings=warnings,
        suggested_intent=suggested_intent,
        suggested_priority=suggested_priority,
        suggested_payload=suggested_payload,
        checksum_valid=checksum_valid,
        received_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        processing_time_ms=elapsed,
    )
