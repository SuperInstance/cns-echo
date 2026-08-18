"""EchoSpace — the CNS bus as a room the elephant reads.

Cross-pollination. cns-echo is the *echo* of the CNS bus: it receives
USCP packets and echoes back structured analysis. The elephant
(`/home/eileen/projects/elephant`) reads *spaces* — any communication
medium normalized into a `Room` of `Message`s, a `DialBank` of JEPA
senses, and a `RoomField` (the room's temperature: warmth, concentration
κ, and one dial per sense).

`EchoSpace` is the adapter that mates the two. Every echoed packet
becomes a `Message` (author = sender `origin_id`, text = the packet's
payload), so the fleet's conversation becomes a room the elephant can
read. The `DialBank` reads the bus's temperature (is the fleet's talk
warm? panicked? earnest?), and the field's deadband **rings when the
bus's mood crosses a threshold** — a fleet-wide laugh or a fleet-wide
panic, ringing *up the chain* as a command.

It matches the elephant's `Space` contract (`space.py`) — `ingest`,
`room`, `read`/`read_field`, `tint`, `send_back`, `tint_target` — but is
self-contained so cns-echo keeps its "pure standard library" guarantee.

Zero-dependency import rule
---------------------------
If the elephant is importable (via the `ELEPHANT_ROOT` env var, or a
sibling checkout at ``../elephant`` relative to this project), we use its
`Room`, `Message`, `Dial`, `DialBank`, `RoomField`, `read_field`, and
`DEFAULT_DIALS` (nine dials). Otherwise a **minimal pure-python subset**
is defined below (no numpy) implementing the same seven core dials that
`warmth()`/`concentration()` depend on, plus `model_vs_code` and `vision`
resting at neutral (the bus has no camera and no commit log). Either way
`EchoSpace` exposes the same four seams.

The rule (from the spaces spec): **JEPA correlates; it never replaces.**
The elephant does not replace the bus's protocol — it reads the bus's
temperature, and the deadband turns a mood crossing into a command.
"""
from __future__ import annotations

import json
import math
import os
import re
import sys
import time
from collections import deque
from dataclasses import dataclass, field as dc_field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

__all__ = [
    "EchoSpace",
    "Ring",
    "FieldEntry",
    "FieldHistory",
    "Message",
    "Room",
    "Dial",
    "DialBank",
    "RoomField",
    "read_field",
    "DEFAULT_DIALS",
    "HAS_ELEPHANT",
]


# --------------------------------------------------------------------------- #
# Import the elephant (optional) — else the pure-python fallback below.       #
# --------------------------------------------------------------------------- #
def _elephant_search_paths() -> List[str]:
    """Candidate sys.path entries where the `elephant` package might live."""
    paths: List[str] = []
    env = os.environ.get("ELEPHANT_ROOT")
    if env:
        paths.append(env)
    # A sibling checkout: <cns-echo>/../elephant
    sibling = Path(__file__).resolve().parents[2] / "elephant"
    paths.append(str(sibling))
    return paths


def _try_import_elephant() -> Optional[dict]:
    """Import the real elephant package; return a namespace dict or None."""
    for p in reversed(_elephant_search_paths()):
        if p and p not in sys.path:
            sys.path.insert(0, p)
    try:
        from elephant.dial import Dial, DialBank  # noqa: F401
        from elephant.dials import DEFAULT_DIALS  # noqa: F401
        from elephant.field import RoomField, read_field  # noqa: F401
        from elephant.room import Message, Room  # noqa: F401
    except ImportError:
        return None
    return {
        "Message": Message,
        "Room": Room,
        "Dial": Dial,
        "DialBank": DialBank,
        "RoomField": RoomField,
        "read_field": read_field,
        "DEFAULT_DIALS": DEFAULT_DIALS,
    }


_ELEPHANT = _try_import_elephant()
HAS_ELEPHANT = _ELEPHANT is not None

if HAS_ELEPHANT:
    Message = _ELEPHANT["Message"]
    Room = _ELEPHANT["Room"]
    Dial = _ELEPHANT["Dial"]
    DialBank = _ELEPHANT["DialBank"]
    RoomField = _ELEPHANT["RoomField"]
    read_field = _ELEPHANT["read_field"]
    DEFAULT_DIALS = _ELEPHANT["DEFAULT_DIALS"]


# --------------------------------------------------------------------------- #
# Pure-python fallback — a minimal subset (no numpy).                         #
# --------------------------------------------------------------------------- #
if not HAS_ELEPHANT:
    _WORD_RE = re.compile(r"\w+")

    @dataclass
    class Message:
        author: str
        text: str
        ts: float = 0.0
        channel: str = "default"
        reactions: Dict[str, int] = dc_field(default_factory=dict)
        replies: List["Message"] = dc_field(default_factory=list)

        @property
        def words(self) -> List[str]:
            return _WORD_RE.findall(self.text.lower())

        @property
        def reaction_heat(self) -> int:
            return sum(self.reactions.values())

    class Room:
        """A sequence of messages with gravity, reverberation, and ripples
        (the pure-python mirror of elephant/room.py)."""

        def __init__(self, name: str, messages: Optional[Iterable[Message]] = None):
            self.name = name
            self.messages: List[Message] = list(messages or [])
            self.messages.sort(key=lambda m: m.ts)

        def gravity(self, msg: Message, half_life: float = 1800.0,
                    engagement_weight: float = 1.0) -> float:
            age = max(0.0, msg.ts - (self.messages[0].ts if self.messages else msg.ts))
            recency = 0.5 ** (age / half_life)
            engagement = 1.0 + engagement_weight * math.log1p(
                msg.reaction_heat + len(msg.replies))
            length = 1.0 + math.log1p(len(msg.words)) / 10.0
            return recency * engagement * length

        def gravity_series(self, half_life: float = 1800.0) -> List[float]:
            return [self.gravity(m, half_life) for m in self.messages]

        def reverberation(self, window: int = 8) -> float:
            heats = self.gravity_series()
            if len(heats) < 2 * window:
                return 0.0
            windows = [heats[i:i + window]
                       for i in range(0, len(heats) - window, window)]
            if len(windows) < 2:
                return 0.0
            sims = [_cosine(a, b) for a, b in zip(windows[:-1], windows[1:])]
            return sum(sims) / len(sims) if sims else 0.0

        def ripple(self, msg: Message, depth: int = 3) -> int:
            if depth <= 0:
                return 0
            size = msg.reaction_heat + len(msg.replies)
            for r in msg.replies:
                size += self.ripple(r, depth - 1)
            return size

        def density(self, window: float = 300.0) -> float:
            if not self.messages:
                return 0.0
            latest = self.messages[-1].ts
            recent = [m for m in self.messages if latest - m.ts <= window]
            if len(recent) < 2:
                return 0.0
            span = max(recent[-1].ts - recent[0].ts, 1e-9)
            return len(recent) / span * 60.0

        def __len__(self) -> int:
            return len(self.messages)

        def __repr__(self) -> str:
            return f"Room({self.name!r}, {len(self.messages)} messages)"

    def _cosine(a: List[float], b: List[float]) -> float:
        num = sum(x * y for x, y in zip(a, b))
        da = math.sqrt(sum(x * x for x in a))
        db = math.sqrt(sum(y * y for y in b))
        if da == 0 or db == 0:
            return 0.0
        return num / (da * db)

    class Dial:
        name: str = "dial"
        description: str = ""

        def read(self, room: Room) -> float:  # pragma: no cover - abstract
            raise NotImplementedError

    class DialBank:
        def __init__(self, dials: Optional[Iterable[Dial]] = None):
            self.dials: List[Dial] = list(dials or [])

        def readings(self, room: Room) -> Dict[str, float]:
            return {d.name: d.read(room) for d in self.dials}

        def names(self) -> List[str]:
            return [d.name for d in self.dials]

        def __len__(self) -> int:
            return len(self.dials)

    # -- the seven core dials (minimal subset) ----------------------- #
    _POS = {"good", "great", "love", "warm", "kind", "glad", "happy", "nice",
            "yes", "thank", "thanks", "together", "fun", "glow", "bright",
            "alive", "laugh", "relax", "peace", "soft", "gentle", "earnest",
            "sincere", "proud", "wonderful", "cheers"}
    _NEG = {"cold", "dead", "broke", "break", "fear", "afraid", "panic",
            "fire", "bad", "wrong", "hate", "lied", "fail", "failed",
            "sinking", "flood", "breach", "alarm", "crickets", "groan",
            "ugh", "no", "never", "dull", "flat", "empty", "stale", "tired",
            "trapped", "crash", "lost", "help", "evacuate", "mayday",
            "distress", "emergency"}
    _ALARM = {"fire", "flood", "breach", "leak", "alarm", "emergency",
              "evacuate", "sinking", "capsize", "mayday", "help", "panic",
              "stampede", "crash", "collision", "distress", "abandon", "run"}
    _URGENCY = {"now", "immediately", "hurry", "fast", "everyone", "all hands",
                "!!!", "now!"}
    _LAUGH = {"lol", "lmao", "rofl", "haha", "hehe", "😂", "🤣", "gold", "dead"}
    _JOKE = {"lol", "haha", "heh", "funny", "joke", "kidding", "😂", "🤣"}
    _SINCERE = {"i", "me", "my", "we", "our", "really", "truly", "honestly",
                "mean", "meant", "felt", "remember", "built", "held", "promise"}
    _CYNICAL = {"sure", "right", "whatever", "of course", "oh great", "ha",
                "totally", "as if", "sarcasm", "eyeroll"}
    _CAPS_RE = re.compile(r"\b[A-Z]{2,}\b")
    _EXCL_RE = re.compile(r"[!?]+")

    class _MoodDial(Dial):
        name = "mood"
        description = "warm/cold valence of the room, [-1 cold .. +1 warm]"

        def read(self, room: Room) -> float:
            if not room.messages:
                return 0.0
            pos = neg = 0
            for m in room.messages:
                words = set(m.words)
                pos += len(words & _POS)
                neg += len(words & _NEG)
            total = pos + neg
            if total == 0:
                return 0.0
            return max(-1.0, min(1.0, (pos - neg) / total * 2.0))

    class _VolumeDial(Dial):
        name = "volume"
        description = "how loud the room is talking, [0 quiet .. 1 shouting]"

        def read(self, room: Room) -> float:
            if not room.messages:
                return 0.0
            density = room.density(window=60.0)
            caps = excl = 0.0
            for m in room.messages:
                w = len(m.words)
                if w > 0:
                    caps += len(_CAPS_RE.findall(m.text)) / w
                    excl += len(_EXCL_RE.findall(m.text)) / w
            n = len(room.messages)
            caps /= n
            excl /= n
            loud = (0.45 * (1.0 - math.exp(-density / 20.0))
                    + 0.35 * caps + 0.20 * excl)
            return max(0.0, min(1.0, loud))

    class _EarnestnessDial(Dial):
        name = "earnestness"
        description = "how much the room means it, [0 ironic .. 1 sincere]"

        def read(self, room: Room) -> float:
            if not room.messages:
                return 0.5
            sincere = hedge = 0
            for m in room.messages:
                words = set(m.words)
                sincere += len(words & _SINCERE)
                hedge += sum(1 for h in ("maybe", "lol", "haha", "kinda", "i guess")
                             if h in m.text.lower())
            total = sincere + hedge
            if total == 0:
                return 0.5
            return sincere / total

    class _CynicismDial(Dial):
        name = "cynicism"
        description = "how much the room is rolling its eyes, [0 earnest .. 1 sneering]"

        def read(self, room: Room) -> float:
            if not room.messages:
                return 0.5
            hits = 0
            total = 0
            for m in room.messages:
                words = set(m.words)
                hits += len(words & _CYNICAL)
                total += len(m.words)
            if total == 0:
                return 0.5
            return max(0.0, min(1.0, hits / total * 40.0))

    class _JokeLandingDial(Dial):
        name = "joke_landing"
        description = "did the jokes land, [-1 booed .. +1 roared]"

        def read(self, room: Room) -> float:
            if not room.messages:
                return 0.0
            scores = []
            for i, m in enumerate(room.messages):
                if not any(k in m.text.lower() for k in _JOKE):
                    continue
                laugh = boo = 0.0
                for w in room.messages[i + 1:i + 5]:
                    wt = w.text.lower()
                    laugh += sum(1 for k in _LAUGH if k in wt)
                    boo += sum(1 for k in ("boo", "crickets", "groan", "yikes")
                               if k in wt)
                if laugh + boo > 0:
                    scores.append((laugh - boo) / (laugh + boo))
            if not scores:
                return 0.0
            return sum(scores) / len(scores)

    class _PanicDial(Dial):
        name = "panic"
        description = "stampede sense, [0 calm .. 1 trampling]"

        def read(self, room: Room) -> float:
            if not room.messages:
                return 0.0
            alarm = urgency = 0
            for m in room.messages:
                t = m.text.lower()
                alarm += sum(1 for a in _ALARM if a in t)
                urgency += sum(1 for u in _URGENCY if u in t)
            word_count = sum(len(m.words) for m in room.messages)
            alarm_norm = min(1.0, alarm / max(word_count / 40.0, 1.0))
            urgency_norm = min(1.0, urgency / 5.0)
            density = room.density(window=30.0)
            density_norm = 1.0 - math.exp(-density / 30.0)
            return max(0.0, min(1.0, 0.5 * alarm_norm + 0.3 * urgency_norm
                                + 0.2 * density_norm))

    class _PresenceDial(Dial):
        name = "presence"
        description = "pheromone trace of the room, [0 empty .. 1 thrumming]"

        def read(self, room: Room) -> float:
            if not room.messages:
                return 0.0
            authors: Dict[str, dict] = {}
            t0 = room.messages[0].ts
            t1 = room.messages[-1].ts
            span = max(t1 - t0, 1e-9)
            for m in room.messages:
                e = authors.setdefault(m.author, {"first": m.ts, "last": m.ts, "n": 0})
                e["first"] = min(e["first"], m.ts)
                e["last"] = max(e["last"], m.ts)
                e["n"] += 1
            distinct = len(authors)
            recency = 1.0 - math.exp(-(t1 - t0) / span)
            longevity = 0.0
            for e in authors.values():
                longevity += min(1.0, (e["last"] - e["first"]) / span * 2.0)
            longevity /= max(distinct, 1)
            activity = min(1.0, len(room.messages) / 40.0)
            return max(0.0, min(1.0, 0.45 * distinct / 5.0 + 0.25 * recency
                                + 0.20 * longevity + 0.10 * activity))

    class _ModelVsCodeDial(Dial):
        name = "model_vs_code"
        description = "who generates the bus signal (neutral in fallback)"

        def read(self, room: Room) -> float:
            return 0.0

    class _VisionDial(Dial):
        name = "vision"
        description = "visual energy (neutral — the bus has no camera)"

        def read(self, room: Room) -> float:
            return 0.5

    DEFAULT_DIALS = [
        _MoodDial(), _VolumeDial(), _EarnestnessDial(), _CynicismDial(),
        _JokeLandingDial(), _PanicDial(), _PresenceDial(),
        _ModelVsCodeDial(), _VisionDial(),
    ]

    DIAL_NAMES = ["mood", "volume", "earnestness", "cynicism",
                  "joke_landing", "panic", "presence"]

    class RoomField:
        """The ensemble of dial readings — the room's temperature vector
        (pure-python mirror of elephant/field.py)."""

        def __init__(self, readings: Dict[str, float]):
            self.readings = dict(readings)

        def vector(self, names: Optional[Iterable[str]] = None) -> List[float]:
            names = list(names) if names is not None else DIAL_NAMES
            return [self.readings.get(n, 0.0) for n in names]

        def warmth(self) -> float:
            r = self.readings
            return (
                0.30 * r.get("mood", 0.0)
                + 0.15 * r.get("joke_landing", 0.0)
                + 0.10 * (r.get("earnestness", 0.5) - 0.5) * 2
                + 0.10 * (r.get("presence", 0.5) - 0.5) * 2
                + 0.10 * (r.get("volume", 0.5) - 0.5) * 2
                - 0.15 * r.get("cynicism", 0.5)
                - 0.10 * r.get("panic", 0.0)
            )

        def concentration(self) -> float:
            v = self.vector()
            centered = [(x - 0.5) for x in v]
            norm = math.sqrt(sum(x * x for x in centered))
            return norm * 2.0

        def distance(self, other: "RoomField") -> float:
            a = self.vector()
            b = other.vector()
            return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))

        def sauna_plunge_gap(self, other: "RoomField") -> float:
            return self.warmth() - other.warmth()

        def __repr__(self) -> str:
            return (f"RoomField(warmth={self.warmth():+.2f}, "
                    f"κ={self.concentration():.2f})")

    def read_field(room: Room, bank: Optional[DialBank] = None) -> RoomField:
        bank = bank or DialBank(DEFAULT_DIALS)
        return RoomField(bank.readings(room))


# --------------------------------------------------------------------------- #
# Packet coercion — a USCP packet -> Message                                   #
# --------------------------------------------------------------------------- #
def _sanitize(value: Any) -> Any:
    """Recursively replace non-finite floats so NaN/Inf never leak into text."""
    if isinstance(value, dict):
        return {k: _sanitize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_sanitize(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return 0.0
    return value


def _render_packet_text(header: Any, body: Any) -> str:
    """Render a packet's body into the text the dials feel: intent, payload
    type, and payload data. Malformed sections degrade to ''."""
    header = header if isinstance(header, dict) else {}
    body = body if isinstance(body, dict) else {}
    intent = body.get("intent") or header.get("intent") or ""
    payload = body.get("payload")
    ptype = data = None
    if isinstance(payload, dict):
        ptype = payload.get("type")
        data = payload.get("data")
    parts: List[str] = []
    if intent:
        parts.append(str(intent))
    if ptype:
        parts.append(str(ptype))
    if data is not None:
        d = _sanitize(data)
        if isinstance(d, (dict, list)):
            parts.append(json.dumps(d, sort_keys=True))
        else:
            parts.append(str(d))
    return " ".join(parts) if parts else "[empty]"


def _to_epoch(ts: Any) -> Optional[float]:
    """Coerce a timestamp to epoch seconds; None if unparseable/NaN/Inf."""
    if ts is None or isinstance(ts, bool):
        return None
    if isinstance(ts, (int, float)):
        v = float(ts)
        return v if math.isfinite(v) else None
    if isinstance(ts, str):
        s = ts.strip()
        if not s:
            return None
        try:
            if s.endswith("Z"):
                s = s[:-1] + "+00:00"
            return datetime.fromisoformat(s).timestamp()
        except (ValueError, OverflowError):
            return None
    return None


def _packet_to_message(packet: Any, ts: float) -> Optional[Message]:
    """Turn one echoed packet into a Message (or None if unusable)."""
    if isinstance(packet, Message):
        return packet
    if isinstance(packet, str):
        return Message(author="[bus]", text=packet, ts=ts)
    if isinstance(packet, (tuple, list)) and len(packet) >= 2:
        author, text = packet[0], packet[1]
        t = packet[2] if len(packet) > 2 else ts
        return Message(author=str(author), text=str(text), ts=float(t))
    if not isinstance(packet, dict):
        return None  # malformed (None/int/list-of-3?) — skip, never crash
    header = packet.get("header")
    body = packet.get("body")
    header = header if isinstance(header, dict) else {}
    author = header.get("origin_id") or "[echo]"
    # Timestamp: prefer the packet's own header, else the auto clock.
    resolved = _to_epoch(header.get("timestamp"))
    mts = resolved if resolved is not None else ts
    return Message(author=str(author), text=_render_packet_text(header, body), ts=mts)


# --------------------------------------------------------------------------- #
# Ring — the deadband crossing, the bus ringing up the chain                   #
# --------------------------------------------------------------------------- #
@dataclass
class Ring:
    """A deadband crossing: the bus's mood crossed a threshold, so the bus
    rings up the chain — a fleet-wide laugh or a fleet-wide panic becomes
    a command."""

    direction: str            # "up" (warmth surge / laugh) or "down" (cold / panic)
    metric: str               # the field metric that crossed ("warmth", "mood", "panic")
    value: float              # current metric reading
    previous: float           # the last reading the deadband committed
    threshold: float          # the deadband width that was crossed
    readings: Dict[str, float]  # the full field at the moment of the ring
    message: str              # the command, phrased up the chain
    ts: float

    @property
    def is_alarm(self) -> bool:
        return self.direction == "down"

    @property
    def is_laugh(self) -> bool:
        return self.direction == "up"


def _ring_message(name: str, direction: str, metric: str, value: float,
                  threshold: float, readings: Dict[str, float]) -> str:
    """Phrase the ring as a command up the chain."""
    if direction == "down":
        panic = readings.get("panic", 0.0)
        if metric == "panic" or panic >= 0.5:
            return (f"🚨 {name}: FLEET-WIDE PANIC — {metric} {value:+.2f} "
                    f"crossed the deadband ({threshold:.2f}); ring the alarm up the chain")
        return (f"🧊 {name}: the bus went cold — {metric} {value:+.2f} "
                f"crossed the deadband ({threshold:.2f}); ring the chill up the chain")
    return (f"🤝 {name}: FLEET-WIDE LAUGH — {metric} {value:+.2f} "
            f"crossed the deadband ({threshold:.2f}); ring the warmth up the chain")


# --------------------------------------------------------------------------- #
# FieldHistory — the EKG strip: bounded rolling memory of the bus's field     #
# --------------------------------------------------------------------------- #
def _clean4(value: Any) -> float:
    """Round for transport; NaN/Inf collapse to 0.0 so JSON stays valid."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return round(v, 4) if math.isfinite(v) else 0.0


@dataclass
class FieldEntry:
    """One window of the fleet's field — one beat of the EKG strip."""

    window: int                 # 1-based window index since the space began
    ts: float                   # when the window closed
    packets: int                # packets the room held when it closed
    warmth: float
    kappa: float
    readings: Dict[str, float]  # the full dial bank at close

    def to_json(self) -> Dict[str, Any]:
        """The entry as one mood-log line, ready for any agent to read."""
        return {
            "window": self.window,
            "ts": _clean4(self.ts),
            "packets": self.packets,
            "warmth": _clean4(self.warmth),
            "kappa": _clean4(self.kappa),
            "dials": {str(k): _clean4(v) for k, v in self.readings.items()},
        }


class FieldHistory:
    """The bus's EKG strip — a bounded rolling history of the field.

    Every `window` ingested packets, one `FieldEntry` is committed: the
    field at the moment the window closed. The deque holds at most
    `max_windows` entries — bounded by law, like every elephant window.
    The in-memory deque is working memory; the mood log (if set) is the
    durable timeline: one JSON line per committed window, appended to
    `mood_log` so every agent on the bus can read the fleet's mood as a
    file.
    """

    def __init__(self, window: int = 100, max_windows: int = 50,
                 mood_log: Optional[Any] = None, name: str = ""):
        self.window = max(1, int(window))
        self.max_windows = max(1, int(max_windows))
        self.entries: "deque[FieldEntry]" = deque(maxlen=self.max_windows)
        self.total_windows = 0
        self.lines_written = 0
        self.log_errors = 0
        self.name = str(name)
        self.mood_log: Optional[Path] = (
            Path(mood_log) if mood_log is not None else None)
        self._since = 0            # packets counted toward the open window

    def feed(self, count: int,
             snapshot: Callable[[], Dict[str, Any]]) -> List[FieldEntry]:
        """Account for `count` new packets; commit one entry each time a
        window closes. `snapshot()` supplies the field at close time
        ({"packets", "warmth", "kappa", "readings"}) and is read at most
        once per feed — a batch shares one reading. Returns the entries
        this call committed."""
        if count <= 0:
            return []
        self._since += count
        if self._since < self.window:
            return []
        snap = _sanitize(snapshot())
        committed: List[FieldEntry] = []
        while self._since >= self.window:
            self._since -= self.window
            self.total_windows += 1
            entry = FieldEntry(
                window=self.total_windows,
                ts=time.time(),
                packets=int(snap.get("packets", 0)),
                warmth=float(snap.get("warmth", 0.0)),
                kappa=float(snap.get("kappa", 0.0)),
                readings=dict(snap.get("readings", {})),
            )
            self.entries.append(entry)
            committed.append(entry)
            self._append_mood_line(entry)
        return committed

    def _append_mood_line(self, entry: FieldEntry) -> None:
        """One JSON line per window — the strip. A bad log path never
        kills the bus; after a failed append, logging stands down."""
        if self.mood_log is None:
            return
        line = json.dumps({**entry.to_json(), "space": self.name},
                          sort_keys=True)
        try:
            with open(self.mood_log, "a", encoding="utf-8") as f:
                f.write(line + "\n")
            self.lines_written += 1
        except OSError:
            self.log_errors += 1
            self.mood_log = None

    @property
    def latest(self) -> Optional[FieldEntry]:
        """The most recently committed window, if any."""
        return self.entries[-1] if self.entries else None

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self):
        return iter(self.entries)

    def __repr__(self) -> str:
        return (f"<FieldHistory window={self.window} "
                f"entries={len(self.entries)}/{self.max_windows} "
                f"total={self.total_windows}>")


# --------------------------------------------------------------------------- #
# EchoSpace                                                                   #
# --------------------------------------------------------------------------- #
class EchoSpace:
    """The CNS bus, read as a room.

    Matches the elephant `Space` contract while staying self-contained:

        ingest(*packets)    — echoed packets -> Messages (author=sender,
                              text=payload, ts=header.timestamp)
        .room               — the normalized Room the elephant reads
        read_field(bank)    — DialBank over .room -> RoomField (warmth, κ,
                              nine dials)
        deadband_check()    — the field's deadband: rings when the bus's mood
                              crosses a threshold (a Ring up the chain)
        .history            — the bounded FieldHistory (the EKG strip):
                              one FieldEntry per window of `window` packets,
                              one JSONL line per window when mood_log is set
        tint()/send_back()  — the bus's temperature phrased as a status line
        tint_target()       — "the bus status line"
    """

    kind = "echo"
    step = 60.0

    def __init__(self, name: str, deadband: float = 0.25,
                 bank: Optional[DialBank] = None, window: int = 100,
                 max_windows: int = 50,
                 mood_log: Optional[Any] = None):
        self.name = name
        self.deadband = float(deadband)
        self.bank = bank if bank is not None else DialBank(list(DEFAULT_DIALS))
        self._room = Room(name)
        self._clock = 0.0
        self._skipped = 0                     # malformed packets dropped
        self._last_ring_value: Dict[str, Optional[float]] = {}
        self.status = f"{name} — bus quiet"
        self._last_tint: Optional[str] = None
        self.history = FieldHistory(window=window, max_windows=max_windows,
                                    mood_log=mood_log, name=name)

    # -- ingest ------------------------------------------------------- #
    def ingest(self, *packets: Any) -> "EchoSpace":
        """Accept one or more echoed packets (or Messages / (author, text)
        tuples); return self. Malformed packets are skipped, never fatal."""
        added = 0
        for p in packets:
            msg = _packet_to_message(p, self._next_ts())
            if msg is None:
                self._skipped += 1
                continue
            self._room.messages.append(msg)
            added += 1
        if added:
            self._room.messages.sort(key=lambda m: m.ts)
            self.history.feed(added, self._field_snapshot)
        return self

    def packet(self, packet: dict, ts: Optional[float] = None) -> Optional[Message]:
        """Ingest one USCP packet, returning the Message it became."""
        msg = _packet_to_message(packet, self._next_ts(ts))
        if msg is None:
            self._skipped += 1
            return None
        self._room.messages.append(msg)
        self._room.messages.sort(key=lambda m: m.ts)
        self.history.feed(1, self._field_snapshot)
        return msg

    # -- normalized room ---------------------------------------------- #
    @property
    def room(self) -> Room:
        """The Room the elephant reads — the fleet's conversation."""
        return self._room

    # -- read --------------------------------------------------------- #
    def read_field(self, bank: Optional[DialBank] = None) -> RoomField:
        """Run the dial bank over the bus -> its field (warmth, κ, 9 dials)."""
        return read_field(self._room, bank or self.bank)

    def read(self, bank: Optional[DialBank] = None) -> RoomField:
        """Alias for the elephant Space contract's `.read(bank)`."""
        return self.read_field(bank)

    # -- deadband ----------------------------------------------------- #
    def deadband_check(self, metric: str = "warmth",
                       threshold: Optional[float] = None) -> Optional[Ring]:
        """Ring when the bus's mood crosses the deadband.

        Reads the current field, takes `metric` ("warmth" by default; also
        "mood" or "panic"), and returns a `Ring` when it has moved by at
        least `threshold` (default `self.deadband`) from the last committed
        reading. The first call establishes the reference and returns None.
        Every ring re-anchors the deadband to the new reading (hysteresis),
        so a second identical reading will NOT ring again.
        """
        threshold = self.deadband if threshold is None else float(threshold)
        field = self.read_field()
        r = field.readings
        if metric == "warmth":
            value = field.warmth()
        else:
            value = float(r.get(metric, 0.0))
        if not math.isfinite(value):
            value = 0.0
        previous = self._last_ring_value.get(metric)
        if previous is None:
            self._last_ring_value[metric] = value
            return None
        delta = value - previous
        if abs(delta) < threshold:
            return None
        direction = "up" if delta > 0 else "down"
        self._last_ring_value[metric] = value
        return Ring(
            direction=direction,
            metric=metric,
            value=value,
            previous=previous,
            threshold=threshold,
            readings=dict(r),
            message=_ring_message(self.name, direction, metric, value, threshold, r),
            ts=time.time(),
        )

    # -- tint / send_back --------------------------------------------- #
    def tint_target(self) -> str:
        return "the bus status line"

    def tint(self, field: RoomField) -> str:
        return _echo_tint(self.name, field, len(self._room))

    def send_back(self, field: Optional[RoomField] = None,
                  tinted_text: Optional[str] = None) -> str:
        field = field or self.read_field()
        text = tinted_text or self.tint(field)
        self._last_tint = text
        self.status = text
        return text

    # -- internals ---------------------------------------------------- #
    def _field_snapshot(self) -> Dict[str, Any]:
        """The field at window close — what the EKG strip records."""
        f = self.read_field()
        return {
            "packets": len(self._room),
            "warmth": f.warmth(),
            "kappa": f.concentration(),
            "readings": dict(f.readings),
        }

    def _next_ts(self, ts: Optional[float] = None) -> float:
        if ts is None:
            ts = self._clock
        ts = float(ts)
        self._clock = max(self._clock, ts + self.step)
        return ts

    @property
    def skipped(self) -> int:
        """Count of malformed packets dropped by ingest."""
        return self._skipped

    def __len__(self) -> int:
        return len(self._room)

    def __repr__(self) -> str:
        return f"<{type(self).__name__} {self.name!r} ({self.kind})>"


def _echo_tint(name: str, field: RoomField, n_pkts: int) -> str:
    """The bus's temperature phrased as a status line."""
    r = field.readings
    warm = field.warmth()
    kappa = field.concentration()
    panic = r.get("panic", 0.0)
    if panic >= 0.5:
        tag, phrase = "🚨", "fleet-wide alarm — the bus is ringing up the chain"
    elif warm >= 0.25:
        tag, phrase = "🤝", "fleet laughing — the bus hums warm and aligned"
    elif warm >= 0.0:
        tag, phrase = "⚙️", "bus steady — agents trading, no contention"
    elif warm >= -0.25:
        tag, phrase = "🧊", "bus cooling — agents going quiet"
    else:
        tag, phrase = "💤", "bus dead — no traffic, agents offline"
    return f"{tag} {name} — {phrase} (warmth {warm:+.2f}, κ {kappa:.2f}, {n_pkts} pkts)"
