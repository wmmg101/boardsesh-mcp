"""Pure functions over ``list[Ascent]``. No I/O, no MCP.

Semantics (from Boardsesh's ``docs/ascents-and-attempts.md``):

* ``status`` is the source of truth: ``flash`` / ``send`` / ``attempt``. Never infer from counts.
* Ticks are not deduplicated, so a climb can appear many times; unique climbs are counted on
  ``(board, climb_uuid, angle)``.
* A "session" is one calendar day in the user's timezone. Boardsesh only groups ticks into
  explicit sessions when they were logged inside a live session, so day-grouping is the honest
  approximation.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import date, datetime, timezone, tzinfo
from typing import Any

from boardsesh_mcp.grades import GradeTable, trustworthy_boardsesh_grade
from boardsesh_mcp.models import Ascent, HoldStat

UTC = timezone.utc
ClimbKey = tuple[str, str, int | None]  # (board, climb_uuid, angle)


# -- helpers ------------------------------------------------------------------------------------


def parse_date_arg(value: str | None, *, tz: tzinfo = UTC) -> str | None:
    """Validate a YYYY-MM-DD argument. Boardsesh's feed wants exactly that format."""
    if value is None or not str(value).strip():
        return None
    text = str(value).strip()
    try:
        date.fromisoformat(text)
    except ValueError:
        raise ValueError(f"Invalid date {value!r}; use YYYY-MM-DD.") from None
    return text


def key_of(ascent: Ascent) -> ClimbKey:
    return (ascent.board, ascent.climb_uuid, ascent.angle)


def ascent_to_dict(ascent: Ascent, grades: GradeTable | None, tz: tzinfo = UTC) -> dict[str, Any]:
    local = ascent.climbed_at.astimezone(tz) if ascent.climbed_at else None
    grade_label = ascent.difficulty_name or (grades.label(ascent.difficulty_id) if grades else None)
    return {
        "climb_name": ascent.climb_name,
        "board": ascent.board,
        "date": local.isoformat() if local else None,
        "angle": ascent.angle,
        "status": ascent.status,
        "attempts": ascent.attempts,
        "grade": grade_label,
        "difficulty_id": ascent.difficulty_id,
        "my_grade_id": ascent.own_difficulty_id,
        "boardsesh_grade": trustworthy_boardsesh_grade(
            ascent.boardsesh_difficulty, ascent.boardsesh_confidence
        ),
        "quality": ascent.quality,
        "benchmark": ascent.is_benchmark,
        "mirrored": ascent.is_mirror,
        "setter": ascent.setter,
        "comment": ascent.comment or None,
        "climb_uuid": ascent.climb_uuid,
    }


def _sorted_desc(ascents: Iterable[Ascent]) -> list[Ascent]:
    return sorted(
        ascents,
        key=lambda a: a.climbed_at.timestamp() if a.climbed_at else 0.0,
        reverse=True,
    )


def _max_difficulty(ascents: Iterable[Ascent]) -> int | None:
    ids = [a.difficulty_id for a in ascents if a.difficulty_id is not None]
    return max(ids) if ids else None


def _describe(grades: GradeTable | None, difficulty_id: int | None) -> dict[str, Any]:
    if grades is None:
        return {"difficulty_id": difficulty_id, "grade": None, "v_grade": None, "font_grade": None}
    return grades.describe(difficulty_id)


# -- summary ------------------------------------------------------------------------------------


def summary(
    ascents: list[Ascent],
    grades: GradeTable | None = None,
    *,
    tz: tzinfo = UTC,
    total_count: int | None = None,
) -> dict[str, Any]:
    sent = [a for a in ascents if a.topped]
    flashes = [a for a in sent if a.status == "flash"]
    days = sorted({d for d in (a.local_date(tz) for a in ascents) if d})
    boards = sorted({a.board for a in ascents})
    angles = sorted({a.angle for a in ascents if a.angle is not None})
    return {
        "entries_analysed": len(ascents),
        "total_entries": total_count if total_count is not None else len(ascents),
        "boards": boards,
        "sends": len(sent),
        "flashes": len(flashes),
        "attempts_without_send": len(ascents) - len(sent),
        "unique_climbs_sent": len({key_of(a) for a in sent}),
        "total_tries": sum(a.attempts for a in ascents),
        "angles_climbed": angles,
        "first_entry": days[0] if days else None,
        "last_entry": days[-1] if days else None,
        "session_count": len(days),
        "hardest_send": _describe(grades, _max_difficulty(sent)),
        "hardest_flash": _describe(grades, _max_difficulty(flashes)),
        "sends_by_grade": counts_by_grade(sent, grades),
        "grade_note": grades.grade_note(a.difficulty_id for a in sent) if grades else None,
    }


def counts_by_grade(ascents: Iterable[Ascent], grades: GradeTable | None) -> list[dict[str, Any]]:
    by_id: dict[int | None, int] = defaultdict(int)
    for a in ascents:
        by_id[a.difficulty_id] += 1
    rows = [{**_describe(grades, k), "count": v} for k, v in by_id.items()]
    rows.sort(key=lambda r: (r["difficulty_id"] is None, r["difficulty_id"] or 0))
    return rows


# -- sessions -----------------------------------------------------------------------------------


def sessions(
    ascents: Iterable[Ascent],
    grades: GradeTable | None = None,
    *,
    limit: int = 5,
    tz: tzinfo = UTC,
) -> list[dict[str, Any]]:
    """Group entries by calendar day in ``tz``; newest first."""
    by_day: dict[str, list[Ascent]] = defaultdict(list)
    for a in ascents:
        day = a.local_date(tz)
        if day:
            by_day[day].append(a)
    out: list[dict[str, Any]] = []
    for day in sorted(by_day, reverse=True)[: max(limit, 0)]:
        entries = _sorted_desc(by_day[day])
        sent = [a for a in entries if a.topped]
        out.append(
            {
                "date": day,
                "boards": sorted({a.board for a in entries}),
                "angles": sorted({a.angle for a in entries if a.angle is not None}),
                "entries": len(entries),
                "sends": len(sent),
                "flashes": sum(1 for a in sent if a.status == "flash"),
                "tries": sum(a.attempts for a in entries),
                "hardest_send": _describe(grades, _max_difficulty(sent)),
                "climbs": [ascent_to_dict(a, grades, tz) for a in entries],
            }
        )
    return out


# -- projects -----------------------------------------------------------------------------------


def projects(
    ascents: Iterable[Ascent], grades: GradeTable | None = None, *, tz: tzinfo = UTC
) -> list[dict[str, Any]]:
    """Climbs with attempts but no send, per (board, climb, angle)."""
    all_ascents = list(ascents)
    sent_keys = {key_of(a) for a in all_ascents if a.topped}
    groups: dict[ClimbKey, list[Ascent]] = defaultdict(list)
    for a in all_ascents:
        if not a.topped and key_of(a) not in sent_keys:
            groups[key_of(a)].append(a)
    out: list[dict[str, Any]] = []
    for (board, climb_uuid, angle), entries in groups.items():
        ordered = _sorted_desc(entries)
        latest = ordered[0]
        out.append(
            {
                "climb_name": latest.climb_name,
                "board": board,
                "angle": angle,
                "sessions": len({a.local_date(tz) for a in ordered}),
                "total_tries": sum(a.attempts for a in ordered),
                "first_tried": ordered[-1].local_date(tz),
                "last_tried": latest.local_date(tz),
                **_describe(grades, latest.difficulty_id),
                "grade": latest.difficulty_name or _describe(grades, latest.difficulty_id)["grade"],
                "climb_uuid": climb_uuid,
            }
        )
    out.sort(key=lambda p: (p["last_tried"] or "", p["total_tries"]), reverse=True)
    return out


# -- boards -------------------------------------------------------------------------------------


def board_comparison(
    ascents: Iterable[Ascent],
    grade_tables: dict[str, GradeTable] | None = None,
    *,
    tz: tzinfo = UTC,
) -> list[dict[str, Any]]:
    """One row per board so the agent can compare Kilter vs Tension vs MoonBoard."""
    by_board: dict[str, list[Ascent]] = defaultdict(list)
    for a in ascents:
        by_board[a.board].append(a)
    out: list[dict[str, Any]] = []
    for board in sorted(by_board):
        entries = by_board[board]
        table = (grade_tables or {}).get(board)
        sent = [a for a in entries if a.topped]
        flashes = [a for a in sent if a.status == "flash"]
        normalised = [
            g
            for g in (
                trustworthy_boardsesh_grade(a.boardsesh_difficulty, a.boardsesh_confidence)
                for a in sent
            )
            if g is not None
        ]
        out.append(
            {
                "board": board,
                "entries": len(entries),
                "sends": len(sent),
                "unique_climbs_sent": len({key_of(a) for a in sent}),
                "flashes": len(flashes),
                "flash_rate": round(len(flashes) / len(sent), 3) if sent else 0.0,
                "tries": sum(a.attempts for a in entries),
                "sessions": len({d for d in (a.local_date(tz) for a in entries) if d}),
                "angles": sorted({a.angle for a in entries if a.angle is not None}),
                "hardest_send": _describe(table, _max_difficulty(sent)),
                "hardest_boardsesh_grade": round(max(normalised), 2) if normalised else None,
                "median_boardsesh_grade": round(_median(normalised), 2) if normalised else None,
                "sends_by_grade": counts_by_grade(sent, table),
            }
        )
    return out


def _median(values: list[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


# -- progression --------------------------------------------------------------------------------


def _period_key(dt: datetime, period: str) -> str:
    if period == "week":
        iso = dt.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    return f"{dt.year:04d}-{dt.month:02d}"


def progression(
    ascents: Iterable[Ascent],
    grades: GradeTable | None = None,
    *,
    period: str = "month",
    tz: tzinfo = UTC,
) -> list[dict[str, Any]]:
    if period not in ("month", "week"):
        raise ValueError("period must be 'month' or 'week'")
    buckets: dict[str, list[Ascent]] = defaultdict(list)
    for a in ascents:
        if a.climbed_at is not None:
            buckets[_period_key(a.climbed_at.astimezone(tz), period)].append(a)
    out: list[dict[str, Any]] = []
    for key in sorted(buckets):
        entries = buckets[key]
        sent = [a for a in entries if a.topped]
        out.append(
            {
                "period": key,
                "sessions": len({d for d in (a.local_date(tz) for a in entries) if d}),
                "boards": sorted({a.board for a in entries}),
                "entries": len(entries),
                "sends": len(sent),
                "unique_climbs_sent": len({key_of(a) for a in sent}),
                "flashes": sum(1 for a in sent if a.status == "flash"),
                "tries": sum(a.attempts for a in entries),
                "hardest_send": _describe(grades, _max_difficulty(sent)),
            }
        )
    return out


# -- grade pyramid ------------------------------------------------------------------------------


def grade_pyramid(
    ascents: Iterable[Ascent], grades: GradeTable | None = None, *, board: str | None = None
) -> dict[str, Any]:
    sent = [a for a in ascents if a.topped and (board is None or a.board == board)]
    by_id: dict[int | None, dict[str, Any]] = {}
    seen: set[tuple[int | None, ClimbKey]] = set()
    for a in sent:
        row = by_id.setdefault(
            a.difficulty_id, {"sends": 0, "unique_climbs": 0, "flashes": 0, "tries": 0}
        )
        row["sends"] += 1
        row["tries"] += a.attempts
        if a.status == "flash":
            row["flashes"] += 1
        marker = (a.difficulty_id, key_of(a))
        if marker not in seen:
            seen.add(marker)
            row["unique_climbs"] += 1
    levels = [
        {
            **_describe(grades, k),
            **v,
            "flash_rate": round(v["flashes"] / v["sends"], 3) if v["sends"] else 0.0,
        }
        for k, v in by_id.items()
    ]
    levels.sort(key=lambda r: (r["difficulty_id"] is None, -(r["difficulty_id"] or 0)))
    return {
        "board": board,
        "total_sends": len(sent),
        "levels": levels,
        "grade_note": grades.grade_note(a.difficulty_id for a in sent) if grades else None,
    }


# -- hold heatmap -------------------------------------------------------------------------------


def hold_usage(
    holds: list[HoldStat], *, limit: int = 15, min_community_uses: int = 5
) -> dict[str, Any]:
    """Turn per-hold counts into a weakness/strength picture.

    Community counts always exist. When the heatmap carries the user's own numbers, each hold
    gets a ``relative_use`` (the user's share of climbs on that hold divided by the community's
    share), so ``< 1`` means the user under-uses that hold relative to how common it is. Holds
    the community barely uses are excluded, because a 0-of-2 sample says nothing.
    """
    if not holds:
        return {"holds_analysed": 0, "personalised": False, "note": "No hold data returned."}

    personalised = any(h.user_ascents is not None for h in holds)
    community_total = sum(h.total_uses for h in holds) or 1
    rows: list[dict[str, Any]] = []
    user_total = sum((h.user_ascents or 0) for h in holds) or 1

    for h in holds:
        row: dict[str, Any] = {
            "hold_id": h.hold_id,
            "climbs_using_hold": h.total_uses,
            "as_hand": h.hand_uses,
            "as_foot": h.foot_uses,
            "as_start": h.starting_uses,
            "as_finish": h.finish_uses,
            "community_ascents": h.total_ascents,
            "average_difficulty": (
                round(h.average_difficulty, 2) if h.average_difficulty is not None else None
            ),
        }
        if personalised:
            row["my_ascents"] = h.user_ascents or 0
            row["my_tries"] = h.user_attempts or 0
            if h.total_uses >= min_community_uses:
                community_share = h.total_uses / community_total
                my_share = (h.user_ascents or 0) / user_total
                row["relative_use"] = round(my_share / community_share, 3)
        rows.append(row)

    out: dict[str, Any] = {
        "holds_analysed": len(rows),
        "personalised": personalised,
        "most_common_holds": sorted(rows, key=lambda r: -r["climbs_using_hold"])[: max(limit, 0)],
    }
    if personalised:
        rated = [r for r in rows if "relative_use" in r]
        out["most_used_by_me"] = sorted(rated, key=lambda r: -r["relative_use"])[: max(limit, 0)]
        out["most_avoided_by_me"] = sorted(rated, key=lambda r: r["relative_use"])[: max(limit, 0)]
        out["note"] = (
            "relative_use compares your share of climbs on a hold with the community's share: "
            "below 1 means you use it less than the wall's climbs would suggest. Hold ids are "
            "wall positions; ask about patterns, not individual ids."
        )
    else:
        out["note"] = (
            "Community-wide hold usage only. Personal hold usage needs a Boardsesh session "
            "cookie, which this server does not use; see the README."
        )
    return out


def hold_usage_from_logbook(
    ascents: Iterable[Ascent], holds: list[HoldStat], *, limit: int = 15
) -> dict[str, Any]:
    """Placeholder for reconstructing personal hold usage client-side.

    The heatmap's personal columns need a cookie session. Reconstructing them means fetching the
    hold list of every climb in the logbook, which is a lot of requests; deferred until the
    upstream endpoint accepts a bearer token.
    """
    return hold_usage(holds, limit=limit)
