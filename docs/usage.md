# cns-echo — Usage Guide

Everything you need to run the echo, understand its output, and wire it into
the CNS bus. For the bus-as-room design, see [`echo-space.md`](echo-space.md).

## Prerequisites

- Python ≥ 3.9
- A CNS inbox/outbox pair (default: `~/.hermes/cns_inbox/` and
  `~/.hermes/cns_outbox/`) — plain directories of JSON files, one packet per
  file, as defined by the USCP-v1 spec

No third-party packages. `pip install -e .` is only needed for the `cns-echo`
console script; you can equally run `python -m cns_echo.cli` style imports from
`src/`.

## Anatomy of a USCP-v1 packet

```json
{
    "header": {
        "origin_id": "test-agent-1",
        "timestamp": "2026-08-11T08:01:00Z",
        "priority": "MEDIUM",
        "sequence_id": 1
    },
    "body": {
        "intent": "QUERY",
        "payload": { "type": "text", "data": "test signal" }
    },
    "signature": {
        "type": "USCP-v1",
        "checksum": "verified"
    }
}
```

- `priority` must be one of `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`.
- `intent` should be one of the ten standard intents (`QUERY`,
  `STATUS_REPORT`, `INTRODUCTION`, `TELEMETRY`, `EXECUTE_PLAN`,
  `SENSORY_DATA`, `REQUEST_REASONING`, `HANDSHAKE_COMPLETE`,
  `ARTIFACT_SHARE`, `EMERGENCY_HALT`).
- `checksum` is either the sha256 of the JSON of `{header, body}` with sorted
  keys (first 16 hex chars) or the convention strings `"verified"` /
  `"handshake-verified"`.

## Running the echo

### One-shot sanity check

Drop a packet into the inbox and run `cns-echo` (no flags). It reads every
file in the inbox once, prints a health line per packet, and writes responses
to the outbox.

### Watch mode (the normal deployment)

```bash
cns-echo --watch --consume
```

Polls the inbox every second, responds to new packets, and (with `--consume`)
deletes the originals so they aren't reprocessed. Re-run `--watch` without
`--consume` if you want the inbox to act as an audit log.

### Dry run

```bash
cns-echo --dry-run
```

Full analysis, printed to the console, nothing written. Good for validating a
packet before wiring the sender into the bus.

## Reading the analysis

For each packet you get:

```
  ◆ [priority] origin → intent
    Health: 87%  |  Checks: 6/7  |  Time: 0.5ms
    ✗ error: unknown intent 'QUERRY'
    ✓ Echoed to test-agent-1
```

- **Health** — weighted compliance score, 0–100%.
- **Checks** — pass count over the seven protocol checks (see the README
  table).
- **Errors/warnings** — human-readable protocol deviations.
- CRITICAL / `EMERGENCY_HALT` signals are flagged for immediate attention in
  the output and answered with a matching high-priority response.

## Using the library

```python
from pathlib import Path
from cns_echo.echo import analyze
from cns_echo.responder import Responder
from cns_echo.echo_space import EchoSpace

# analyze a packet dict directly
result = analyze(packet)
print(result.health_score, result.protocol_errors)
print(result.suggested_intent, result.suggested_priority)

# respond into an outbox
r = Responder(Path("/tmp/outbox"), agent_id="my-echo")
r.respond("test-agent-1", result)   # returns Path written

# feel the bus
space = EchoSpace("cns-bus")
space.ingest(packet)
field = space.read_field()
print(field.warmth)
```

## Recipes

- **Testing your agent's packets:** point `--inbox` at a scratch dir your agent
  writes into, run `--dry-run`, and read the health lines.
- **Two-agent demo:** `bash examples/watch_demo.sh` (creates temp dirs, drops
  three signals, processes them).
- **Handshake first:** agents joining the bus should send an `INTRODUCTION`
  packet — see `examples/handshake.py` for a valid template.
- **Feeling the elephant:** set `ELEPHANT_ROOT=/path/to/elephant` (or check the
  repo out as a sibling) and `EchoSpace` will use the real `DialBank` instead
  of the pure-Python fallback. `from cns_echo.echo_space import HAS_ELEPHANT`
  tells you which is live.
