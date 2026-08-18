# Echo Space — the CNS bus as a room the elephant reads

*2026-08-17 · bus cross-pollination.*

cns-echo is the bus's echo: it receives USCP packets and echoes back
structured analysis. The elephant (`/home/eileen/projects/elephant`)
reads *spaces* — any communication medium normalized into a `Room` of
`Message`s, a `DialBank` of JEPA senses, and a `RoomField` (the room's
temperature: warmth, concentration κ, one dial per sense). `EchoSpace`
is the adapter that mates the two: **the CNS echo stream becomes a room
the elephant can read.**

The rule from the spaces spec holds unchanged: **JEPA correlates; it
never replaces.** The elephant does not replace the bus's protocol — it
reads the bus's temperature, and the deadband turns a mood crossing into
a command.

## The bus as a room

Every echoed USCP packet becomes a `Message`:

- **author** = the sender (`header.origin_id`) — who is speaking on the bus;
- **text** = the payload (`body.intent` + payload type + payload data) —
  what the fleet is actually saying;
- **ts** = the packet's timestamp (parsed to epoch seconds; the adapter's
  auto-incrementing clock stands in for missing/unparseable timestamps).

```python
space = EchoSpace("cns-bus")
space.ingest(packet)            # one packet, or many at once
room = space.room               # the Room the elephant reads
room.messages[0].author         # "lucineer-riker"
room.messages[0].text           # "STATUS_REPORT status all systems nominal"
```

Malformed packets (non-dict, NaN/Inf floats, broken sections) are
skipped or sanitized — never fatal, per the fleet's NaN-blindness
culture. `space.skipped` counts the ones dropped outright.

## The fleet's conversation as a field

`read_field()` runs the nine-dial bank over the room and returns the
`RoomField` — the bus's temperature:

- **warmth** — is the fleet's talk warm, aligned, laughing — or cold and
  sharp? (composite of mood, joke-landing, earnestness, presence, volume
  against cynicism and panic);
- **κ (concentration)** — how *tight* the bus is: a cold room has one way
  to be (high κ), a warm room has many (low κ);
- **nine dials** — `mood`, `volume`, `earnestness`, `cynicism`,
  `joke_landing`, `panic`, `presence`, `model_vs_code`, `vision`.

The same field reads a quiet bus, a busy bus, and a panicking bus as
three different elephants — without the elephant ever knowing what USCP
is. It only knows Rooms, Messages, and dials.

## The deadband — ringing up the chain

The field has a deadband. `deadband_check()` reads the bus's mood and
rings only when it has moved past a threshold from the last committed
reading — hysteresis, so a steady bus stays quiet and a *real shift*
becomes a command:

```python
space.deadband_check()          # establishes the reference -> None
# ... a fleet-wide panic bursts onto the bus ...
ring = space.deadband_check()   # Ring(direction="down", ...)
ring.message  # "🚨 cns-bus: FLEET-WIDE PANIC — warmth -0.37 crossed the deadband..."
```

A fleet-wide **laugh** rings *up* the chain; a fleet-wide **panic** rings
*down* — each a command in the bus's own idiom. The elephant is the
light, and the light, here, is the fleet's temperature made audible.

## The EKG strip — the mood as a file

Every `window` (100) ingested packets, the current field is committed to
a bounded rolling `FieldHistory` — a deque holding at most `max_windows`
(50) entries, bounded by law like every elephant window. When `mood_log`
is set (the CLI's `--mood-log` flag), each committed window also appends
one JSON line to `fleet-mood.jsonl`, so every agent on the bus can read
the fleet's mood as a file. The deque is working memory; the strip is
the timeline.

## API

| Member | What it is |
|--------|-----------|
| `EchoSpace(name, deadband=0.25, bank=None, window=100, max_windows=50, mood_log=None)` | the adapter |
| `.ingest(*packets)` | packets → Messages; returns `self` |
| `.packet(packet, ts=None)` | one packet → its Message |
| `.room` | the normalized `Room` |
| `.read_field(bank=None)` / `.read(bank)` | DialBank → `RoomField` |
| `.deadband_check(metric="warmth", threshold=None)` | mood crossing → `Ring` or `None` |
| `.history` | the bounded `FieldHistory` — the EKG strip |
| `.tint(field)` / `.send_back(field)` | the bus's temperature as a status line |
| `.tint_target()` | `"the bus status line"` |
| `.skipped` | count of malformed packets dropped |
| `Ring` | `direction`, `metric`, `value`, `previous`, `threshold`, `readings`, `message`, `ts`, `is_alarm`, `is_laugh` |
| `FieldHistory` | `feed(count, snapshot)`, `entries` (deque, ≤ `max_windows`), `window`, `total_windows`, `latest`, `lines_written` |
| `FieldEntry` | `window`, `ts`, `packets`, `warmth`, `kappa`, `readings`, `to_json()` |

## Zero-dependency import rule

If the elephant is importable (via the `ELEPHANT_ROOT` env var, or a
sibling checkout at `../elephant`), `EchoSpace` uses the real
`Room`/`Message`/`DialBank`/`RoomField` and the nine dials. Otherwise a
**minimal pure-python subset** (no numpy) is defined in
`src/cns_echo/echo_space.py` implementing the seven core dials that
warmth and concentration depend on, with `model_vs_code` and `vision`
resting at neutral (the bus has no commit log and no camera). Either way
the adapter exposes the same four seams — cns-echo keeps its "pure
standard library" guarantee.

---

*The elephant doesn't care if the room is made of oak, pixels, or USCP
packets. It only cares how warm the room is — and here, the room is the
whole fleet, talking.*
