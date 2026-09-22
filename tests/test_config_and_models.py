from __future__ import annotations

from datetime import timezone

import pytest

from boardsesh_mcp.config import ConfigError, Settings, redact, resolve_timezone, timezone_name
from boardsesh_mcp.grades import GradeTable, trustworthy_boardsesh_grade, v_number
from boardsesh_mcp.models import Ascent, Grade, HoldStat, parse_datetime
from tests.conftest import TEST_EMAIL, TEST_PASSWORD, TEST_USER_ID, feed_item

# -- config -------------------------------------------------------------------------------------


def test_public_mode_needs_only_a_user():
    s = Settings.from_env({"BOARDSESH_USER": " Test Climber "})
    assert s.user == "Test Climber"
    assert s.has_credentials is False
    assert s.user_is_id is False


def test_user_id_is_detected():
    s = Settings.from_env({"BOARDSESH_USER": TEST_USER_ID})
    assert s.user_is_id is True


def test_credentials_are_optional_but_must_come_in_pairs():
    s = Settings.from_env(
        {"BOARDSESH_USER": "x", "BOARDSESH_EMAIL": TEST_EMAIL, "BOARDSESH_PASSWORD": TEST_PASSWORD}
    )
    assert s.has_credentials is True
    for partial in (
        {"BOARDSESH_USER": "x", "BOARDSESH_EMAIL": TEST_EMAIL},
        {"BOARDSESH_USER": "x", "BOARDSESH_PASSWORD": TEST_PASSWORD},
    ):
        with pytest.raises(ConfigError, match="both"):
            Settings.from_env(partial)


def test_missing_user_is_actionable():
    with pytest.raises(ConfigError) as info:
        Settings.from_env({})
    assert "BOARDSESH_USER" in str(info.value)


def test_repr_hides_password():
    s = Settings(user="x", email=TEST_EMAIL, password="super-secret")
    assert "super-secret" not in repr(s)
    assert "with credentials" in repr(s)


def test_redact_strips_tokens_and_secrets():
    text = (
        'Authorization: Bearer abc.def-ghi {"jwt": "tok1", "refreshToken":"tok2"} password=hunter2'
    )
    out = redact(text, "hunter2")
    for secret in ("abc.def-ghi", "tok1", "tok2", "hunter2"):
        assert secret not in out


def test_timezone_resolution():
    from zoneinfo import ZoneInfo

    assert resolve_timezone({"BOARDSESH_TIMEZONE": " Europe/Rome "}) == ZoneInfo("Europe/Rome")
    assert resolve_timezone({"TZ": "America/Denver"}) == ZoneInfo("America/Denver")
    assert timezone_name(timezone.utc) == "UTC"
    with pytest.raises(ConfigError, match="BOARDSESH_TIMEZONE"):
        resolve_timezone({"BOARDSESH_TIMEZONE": "Nowhere/Land"})


# -- models -------------------------------------------------------------------------------------


def test_ascent_parses_a_feed_item():
    a = Ascent.from_feed_item(feed_item("t1", "Test Climb", attempts=3, consensus=18, quality=4))
    assert a.climb_name == "Test Climb"
    assert a.board == "kilter"
    assert a.angle == 40
    assert a.status == "send"
    assert a.topped is True
    assert a.attempts == 3
    assert a.difficulty_id == 18
    assert a.quality == 4
    assert a.climbed_at is not None and a.climbed_at.tzinfo == timezone.utc


def test_status_drives_topped_not_attempt_count():
    attempt = Ascent.from_feed_item(feed_item("t", "P", status="attempt", attempts=9))
    assert attempt.topped is False
    flash = Ascent.from_feed_item(feed_item("t", "F", status="flash", attempts=1))
    assert flash.topped is True and flash.status == "flash"


def test_personal_grade_wins_over_consensus():
    a = Ascent.from_feed_item(feed_item("t", "G", difficulty=20, consensus=18))
    assert a.difficulty_id == 20
    assert a.own_difficulty_id == 20
    assert a.consensus_difficulty_id == 18


def test_consensus_used_when_no_personal_grade():
    a = Ascent.from_feed_item(feed_item("t", "G", difficulty=None, consensus=15))
    assert a.difficulty_id == 15
    assert a.own_difficulty_id is None


def test_ascent_tolerates_missing_fields():
    a = Ascent.from_feed_item({})
    assert a.climb_name == "Unknown climb"
    assert a.board == "unknown"
    assert a.attempts == 1
    assert a.status == "attempt"
    assert a.climbed_at is None


def test_unknown_status_is_treated_as_attempt():
    assert Ascent.from_feed_item({"status": "wat"}).status == "attempt"


def test_local_date_respects_timezone():
    from zoneinfo import ZoneInfo

    a = Ascent.from_feed_item(feed_item("t", "Late", climbed_at="2026-06-12T00:15:00Z"))
    assert a.local_date() == "2026-06-12"
    assert a.local_date(ZoneInfo("America/Denver")) == "2026-06-11"


def test_parse_datetime_variants():
    assert parse_datetime("2026-01-01T18:00:00Z").hour == 18
    assert parse_datetime("2026-01-01T20:00:00+02:00").hour == 18
    assert parse_datetime("nonsense") is None
    assert parse_datetime(None) is None


def test_hold_stat_parsing():
    h = HoldStat.from_api({"holdId": 4, "totalUses": 10, "handUses": 7, "userAscents": 2})
    assert (h.hold_id, h.total_uses, h.hand_uses, h.user_ascents) == (4, 10, 7, 2)
    assert h.user_attempts is None
    assert HoldStat.from_api({"totalUses": 1}) is None


# -- grades -------------------------------------------------------------------------------------


def test_grade_parses_combined_label():
    g = Grade.from_api({"difficultyId": 18, "name": "6b/V4"})
    assert (g.id, g.label, g.font_scale, g.v_scale) == (18, "6b/V4", "6b", "V4")
    assert Grade.from_api({"name": "6b/V4"}) is None


def test_grade_table_describe(grades: GradeTable):
    assert grades.describe(18) == {
        "difficulty_id": 18,
        "grade": "6b/V4",
        "v_grade": "V4",
        "font_grade": "6b",
    }
    assert grades.describe(None)["grade"] is None
    assert grades.describe(999)["grade"] is None


def test_fallback_table_covers_the_aurora_scale():
    table = GradeTable.fallback()
    assert table.source == "fallback"
    assert len(table.grades) == 39
    assert table.describe(10)["grade"] == "4a/V0"
    assert table.describe(33)["v_grade"] == "V16"


def test_grade_note_only_fires_when_v_scale_is_uninformative(grades: GradeTable):
    # 10/11/12 are 4a/4b/4c, all V0: the V-scale says nothing useful.
    note = grades.grade_note([10, 11, 12])
    assert note and "V0" in note and "4a-4c" in note
    # A wide-ranging logbook does not need the note.
    assert grades.grade_note([10, 13, 15, 18, 20]) is None
    assert grades.grade_note([]) is None


def test_v_number():
    assert v_number("6a/V3") == 3
    assert v_number("V10") == 10
    assert v_number(None) is None
    assert v_number("6a") is None


def test_boardsesh_grade_confidence_gate():
    assert trustworthy_boardsesh_grade(18.2, "confirmed") == 18.2
    assert trustworthy_boardsesh_grade(18.2, "provisional") == 18.2
    for tier in ("setter_only", "cross_angle_estimate", "moonboard_angle_estimate"):
        assert trustworthy_boardsesh_grade(18.2, tier) is None
    assert trustworthy_boardsesh_grade(None, "confirmed") is None
