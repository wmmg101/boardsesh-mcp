"""Typed models for Boardsesh API responses.

Parsing is tolerant: unknown fields are ignored and missing optional fields get sensible
defaults, because the schema evolves faster than this client.

Semantics come from Boardsesh's own ``docs/ascents-and-attempts.md``:

* A **tick** is one row: a user did something on a climb at an angle at a time.
* ``status`` is authoritative and is one of ``flash`` (completed first try), ``send``
  (completed after failures) or ``attempt`` (tried, did not complete, a "bid").
  Never infer status from attempt counts.
* Flashes and sends together are "ascents"; attempts are "bids".
* Ticks are never deduplicated, so counting rows is not counting climbs.
* ``difficulty`` is the user's *personal* grade and is often null; ``effectiveDifficulty``
  coalesces it with the climb's consensus and is the one to display.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, tzinfo
from typing import Any, Literal

Status = Literal["flash", "send", "attempt"]


def parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _as_int(value: Any, default: int | None = None) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return round(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value)
    return default


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


@dataclass(frozen=True)
class Ascent:
    """One entry from the user's logbook (a `Tick`, enriched by the ascents feed).

    ``board`` is the board *type* (kilter, tension, moonboard, ...): Boardsesh keeps one
    logbook across every board, so this is the discriminator that makes it multi-board.
    """

    tick_uuid: str
    climb_uuid: str
    climb_name: str
    board: str
    angle: int | None
    status: Status
    attempts: int
    climbed_at: datetime | None
    difficulty_id: int | None  # effectiveDifficulty: personal grade or consensus
    own_difficulty_id: int | None  # the user's personal grade, when they set one
    consensus_difficulty_id: int | None
    difficulty_name: str | None
    boardsesh_difficulty: float | None  # cross-board normalised grade
    boardsesh_confidence: str | None
    quality: int | None  # 1-5 stars, null for attempts and for Kilter-synced ticks
    is_benchmark: bool
    is_mirror: bool
    setter: str | None
    board_name: str | None  # human-readable physical board, when known
    layout_id: int | None
    comment: str

    @property
    def topped(self) -> bool:
        return self.status in ("flash", "send")

    def local_date(self, tz: tzinfo = timezone.utc) -> str | None:
        """Calendar date (YYYY-MM-DD) in ``tz``; this is what defines a 'session'."""
        return self.climbed_at.astimezone(tz).date().isoformat() if self.climbed_at else None

    @classmethod
    def from_feed_item(cls, raw: dict[str, Any]) -> Ascent:
        status = str(raw.get("status") or "attempt").lower()
        if status not in ("flash", "send", "attempt"):
            status = "attempt"
        attempts = _as_int(raw.get("attemptCount"), None)
        if attempts is None or attempts < 1:
            attempts = 1
        own = _as_int(raw.get("difficulty"))
        consensus = _as_int(raw.get("consensusDifficulty"))
        # The ascents feed has no `effectiveDifficulty` (that lives on `Tick`), so coalesce the
        # way Boardsesh does: the climber's own grade wins, else the climb's consensus.
        effective = _as_int(raw.get("effectiveDifficulty"))
        if effective is None:
            effective = own if own is not None else consensus
        return cls(
            tick_uuid=str(raw.get("uuid") or ""),
            climb_uuid=str(raw.get("climbUuid") or ""),
            climb_name=str(raw.get("climbName") or "Unknown climb"),
            board=str(raw.get("boardType") or "unknown"),
            angle=_as_int(raw.get("angle")),
            status=status,  # type: ignore[arg-type]
            attempts=attempts,
            climbed_at=parse_datetime(raw.get("climbedAt")),
            difficulty_id=effective,
            own_difficulty_id=own,
            consensus_difficulty_id=consensus,
            difficulty_name=_clean_str(raw.get("difficultyName"))
            or _clean_str(raw.get("consensusDifficultyName")),
            boardsesh_difficulty=_as_float(raw.get("boardseshDifficulty")),
            boardsesh_confidence=_clean_str(raw.get("boardseshConfidence")),
            quality=_as_int(raw.get("quality")),
            is_benchmark=bool(raw.get("isBenchmark", False)),
            is_mirror=bool(raw.get("isMirror", False)),
            setter=_clean_str(raw.get("setterUsername")),
            board_name=_clean_str(raw.get("boardDisplayName")),
            layout_id=_as_int(raw.get("layoutId")),
            comment=str(raw.get("comment") or ""),
        )


def _clean_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


@dataclass(frozen=True)
class Grade:
    """One row from ``grades(boardName:)``: the board-native difficulty scale."""

    id: int
    label: str  # as Boardsesh returns it, e.g. "6a/V3"
    font_scale: str | None
    v_scale: str | None

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> Grade | None:
        grade_id = _as_int(raw.get("difficultyId"))
        if grade_id is None:
            return None
        label = str(raw.get("name") or "").strip()
        font = v = None
        if "/" in label:
            font, _, v = label.partition("/")
            font, v = font.strip() or None, v.strip() or None
        elif label:
            v = label
        return cls(id=grade_id, label=label or f"#{grade_id}", font_scale=font, v_scale=v)


@dataclass(frozen=True)
class BoardTickCount:
    board: str
    count: int

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> BoardTickCount | None:
        board = _clean_str(raw.get("boardType"))
        count = _as_int(raw.get("count"), 0) or 0
        return cls(board=board, count=count) if board else None


@dataclass(frozen=True)
class HoldStat:
    """One hold from the heatmap endpoint.

    Community columns are always present. ``user_ascents`` / ``user_attempts`` appear only when
    the request was authenticated, and are the basis of "which holds do I avoid".
    """

    hold_id: int
    total_uses: int  # climbs using this hold
    hand_uses: int
    foot_uses: int
    starting_uses: int
    finish_uses: int
    total_ascents: int  # community ascents across climbs using this hold
    average_difficulty: float | None
    user_ascents: int | None
    user_attempts: int | None

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> HoldStat | None:
        hold_id = _as_int(raw.get("holdId"))
        if hold_id is None:
            return None
        return cls(
            hold_id=hold_id,
            total_uses=_as_int(raw.get("totalUses"), 0) or 0,
            hand_uses=_as_int(raw.get("handUses"), 0) or 0,
            foot_uses=_as_int(raw.get("footUses"), 0) or 0,
            starting_uses=_as_int(raw.get("startingUses"), 0) or 0,
            finish_uses=_as_int(raw.get("finishUses"), 0) or 0,
            total_ascents=_as_int(raw.get("totalAscents"), 0) or 0,
            average_difficulty=_as_float(raw.get("averageDifficulty")),
            user_ascents=_as_int(raw.get("userAscents")),
            user_attempts=_as_int(raw.get("userAttempts")),
        )


@dataclass(frozen=True)
class ClimbSuggestion:
    """A climb from search / recommendations / similar-climbs."""

    climb_uuid: str
    name: str
    board: str | None
    angle: int | None
    difficulty_name: str | None
    ascents: int | None
    quality: float | None
    setter: str | None
    benchmark: bool
    user_ascents: int | None
    user_attempts: int | None
    similarity: float | None = None

    @classmethod
    def from_api(cls, raw: dict[str, Any], board: str | None = None) -> ClimbSuggestion | None:
        uuid = _clean_str(raw.get("uuid")) or _clean_str(raw.get("climbUuid"))
        if not uuid:
            return None
        return cls(
            climb_uuid=uuid,
            name=str(raw.get("name") or "Unknown climb"),
            board=_clean_str(raw.get("boardType")) or board,
            angle=_as_int(raw.get("statsAngle")) or _as_int(raw.get("angle")),
            difficulty_name=_clean_str(raw.get("difficulty"))
            or _clean_str(raw.get("difficultyName")),
            ascents=_as_int(raw.get("ascensionist_count")) or _as_int(raw.get("ascensionistCount")),
            quality=_as_float(raw.get("quality_average")) or _as_float(raw.get("qualityAverage")),
            setter=_clean_str(raw.get("setter_username")) or _clean_str(raw.get("setterUsername")),
            benchmark=bool(
                raw.get("isBenchmark") or _clean_str(raw.get("benchmark_difficulty")) or False
            ),
            user_ascents=_as_int(raw.get("userAscents")),
            user_attempts=_as_int(raw.get("userAttempts")),
            similarity=_as_float(raw.get("similarity")),
        )
