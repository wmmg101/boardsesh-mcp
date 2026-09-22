from __future__ import annotations

import pytest

from boardsesh_mcp import analytics
from boardsesh_mcp.models import Ascent, HoldStat
from tests.conftest import feed_item


def test_summary_across_boards(ascents, grades):
    s = analytics.summary(ascents, grades, total_count=8)
    assert s["entries_analysed"] == 8
    assert s["boards"] == ["kilter", "tension"]
    assert s["sends"] == 6  # 4 sends + 2 flashes
    assert s["flashes"] == 2
    assert s["attempts_without_send"] == 2
    assert s["unique_climbs_sent"] == 6
    assert s["total_tries"] == 3 + 1 + 5 + 4 + 2 + 1 + 1 + 1
    assert s["angles_climbed"] == [20, 40]
    assert s["first_entry"] == "2026-01-01"
    assert s["last_entry"] == "2026-02-10"
    assert s["session_count"] == 4
    assert s["hardest_send"]["grade"] == "6c/V5"  # the self-graded 20
    assert s["hardest_flash"]["grade"] == "5a/V1"


def test_ascent_to_dict_shape(ascents, grades):
    d = analytics.ascent_to_dict(ascents[0], grades)
    assert d["climb_name"] == "Kilter Send"
    assert d["board"] == "kilter"
    assert d["status"] == "send"
    assert d["grade"] == "6b/V4"
    assert d["difficulty_id"] == 18
    assert d["boardsesh_grade"] == 18.2
    assert d["date"] == "2026-01-01T18:00:00+00:00"
    # no internal ids other than the climb uuid, which other tools need
    assert "tick_uuid" not in d and "user_id" not in d


def test_estimate_tier_is_not_reported_as_normalised_grade(ascents, grades):
    estimated = next(a for a in ascents if a.climb_name == "Estimated")
    assert estimated.boardsesh_difficulty == 18.0
    assert analytics.ascent_to_dict(estimated, grades)["boardsesh_grade"] is None


def test_sessions_group_by_day(ascents, grades):
    s = analytics.sessions(ascents, grades, limit=10)
    assert [x["date"] for x in s] == ["2026-02-10", "2026-02-03", "2026-01-08", "2026-01-01"]
    latest = s[0]
    assert latest["entries"] == 3
    assert latest["sends"] == 3
    assert latest["flashes"] == 1
    assert latest["boards"] == ["kilter", "tension"]
    assert len(latest["climbs"]) == 3
    assert len(analytics.sessions(ascents, grades, limit=1)) == 1


def test_sessions_use_timezone(grades):
    from zoneinfo import ZoneInfo

    logs = [
        Ascent.from_feed_item(feed_item("a", "Before", climbed_at="2026-06-11T23:45:00Z")),
        Ascent.from_feed_item(feed_item("b", "After", climbed_at="2026-06-12T00:15:00Z")),
    ]
    assert len(analytics.sessions(logs, grades, limit=5)) == 2
    denver = analytics.sessions(logs, grades, limit=5, tz=ZoneInfo("America/Denver"))
    assert len(denver) == 1 and denver[0]["date"] == "2026-06-11"


def test_projects_are_per_board_climb_and_angle(ascents, grades):
    rows = analytics.projects(ascents, grades)
    assert len(rows) == 1
    p = rows[0]
    assert p["climb_name"] == "Kilter Project"
    assert p["board"] == "kilter"
    assert p["angle"] == 40
    assert p["sessions"] == 2
    assert p["total_tries"] == 9
    assert p["first_tried"] == "2026-01-01"
    assert p["last_tried"] == "2026-01-08"


def test_a_sent_climb_is_not_a_project(grades):
    logs = [
        Ascent.from_feed_item(feed_item("a", "Eventually", status="attempt", attempts=4)),
        Ascent.from_feed_item(feed_item("b", "Eventually", status="send", attempts=2)),
    ]
    assert analytics.projects(logs, grades) == []


def test_board_comparison(ascents, grades):
    rows = analytics.board_comparison(ascents, {"kilter": grades, "tension": grades})
    by_board = {r["board"]: r for r in rows}
    assert set(by_board) == {"kilter", "tension"}
    kilter = by_board["kilter"]
    assert kilter["entries"] == 6
    assert kilter["sends"] == 4
    assert kilter["flashes"] == 1
    assert kilter["flash_rate"] == 0.25
    tension = by_board["tension"]
    assert tension["sends"] == 2
    assert tension["flash_rate"] == 0.5
    # normalised grades let the two boards be compared; the estimate tier is excluded
    assert kilter["hardest_boardsesh_grade"] == 18.2
    assert tension["median_boardsesh_grade"] == pytest.approx(15.45)


def test_grade_pyramid(ascents, grades):
    p = analytics.grade_pyramid(ascents, grades)
    assert p["total_sends"] == 6
    ids = [level["difficulty_id"] for level in p["levels"]]
    assert ids == sorted(ids, reverse=True)
    top = p["levels"][0]
    assert top["grade"] == "6c/V5"
    filtered = analytics.grade_pyramid(ascents, grades, board="tension")
    assert filtered["total_sends"] == 2
    assert filtered["board"] == "tension"


def test_progression_by_month_and_week(ascents, grades):
    months = analytics.progression(ascents, grades)
    assert [m["period"] for m in months] == ["2026-01", "2026-02"]
    assert months[0]["sessions"] == 2
    assert months[1]["boards"] == ["kilter", "tension"]
    weeks = analytics.progression(ascents, grades, period="week")
    assert all(w["period"].startswith("2026-W") for w in weeks)
    with pytest.raises(ValueError, match="period"):
        analytics.progression(ascents, grades, period="decade")


def test_parse_date_arg():
    assert analytics.parse_date_arg("2026-01-08") == "2026-01-08"
    assert analytics.parse_date_arg(None) is None
    assert analytics.parse_date_arg("  ") is None
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        analytics.parse_date_arg("last tuesday")


# -- hold heatmap -------------------------------------------------------------------------------


def _holds(personal: bool) -> list[HoldStat]:
    rows = [
        {
            "holdId": 1,
            "totalUses": 60,
            "handUses": 50,
            "footUses": 5,
            "startingUses": 5,
            "finishUses": 0,
            "totalAscents": 600,
            "averageDifficulty": 18.0,
        },
        {
            "holdId": 2,
            "totalUses": 40,
            "handUses": 10,
            "footUses": 30,
            "startingUses": 0,
            "finishUses": 0,
            "totalAscents": 300,
            "averageDifficulty": 17.0,
        },
        {
            "holdId": 3,
            "totalUses": 2,
            "handUses": 2,
            "footUses": 0,
            "startingUses": 0,
            "finishUses": 0,
            "totalAscents": 5,
            "averageDifficulty": 22.0,
        },
    ]
    if personal:
        # heavy on hold 1, avoids hold 2 entirely
        rows[0].update({"userAscents": 20, "userAttempts": 25})
        rows[1].update({"userAscents": 0, "userAttempts": 1})
        rows[2].update({"userAscents": 0, "userAttempts": 0})
    return [h for h in (HoldStat.from_api(r) for r in rows) if h]


def test_hold_usage_community_only():
    out = analytics.hold_usage(_holds(personal=False))
    assert out["personalised"] is False
    assert out["holds_analysed"] == 3
    assert [h["hold_id"] for h in out["most_common_holds"]] == [1, 2, 3]
    assert "most_avoided_by_me" not in out
    assert "session cookie" in out["note"]


def test_hold_usage_flags_avoided_holds():
    out = analytics.hold_usage(_holds(personal=True))
    assert out["personalised"] is True
    assert out["most_used_by_me"][0]["hold_id"] == 1
    assert out["most_avoided_by_me"][0]["hold_id"] == 2
    assert out["most_used_by_me"][0]["relative_use"] > 1
    assert out["most_avoided_by_me"][0]["relative_use"] == 0.0
    # hold 3 is too rare in the community to judge
    assert all("relative_use" in h for h in out["most_avoided_by_me"])
    assert 3 not in [h["hold_id"] for h in out["most_avoided_by_me"]]


def test_hold_usage_handles_no_data():
    out = analytics.hold_usage([])
    assert out["holds_analysed"] == 0 and out["personalised"] is False
