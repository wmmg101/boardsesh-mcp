"""End-to-end tests of the MCP tools, in-process, against the fake Boardsesh backend."""

from __future__ import annotations

import json
from typing import Any

import pytest
from mcp import Client

from boardsesh_mcp.client import BoardseshClient
from boardsesh_mcp.config import ConfigError, Settings
from boardsesh_mcp.server import BoardseshService, create_server, run_check
from tests.conftest import (
    ACCESS_1,
    REFRESH_1,
    TEST_EMAIL,
    TEST_PASSWORD,
    TEST_USER_ID,
    TEST_USER_NAME,
    FakeBoardsesh,
)

PUBLIC_TOOLS = {
    "boardsesh_get_summary",
    "boardsesh_get_ascents",
    "boardsesh_get_sessions",
    "boardsesh_get_projects",
    "boardsesh_compare_boards",
    "boardsesh_get_grade_pyramid",
    "boardsesh_get_progression",
    "boardsesh_get_grades",
}
CREDENTIAL_TOOLS = {
    "boardsesh_recommend_climbs",
    "boardsesh_find_similar_climbs",
    "boardsesh_get_hold_heatmap",
    "boardsesh_search_climbs",
}
ALL_TOOLS = PUBLIC_TOOLS | CREDENTIAL_TOOLS


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _payload(result) -> Any:
    assert not result.is_error, result.content[0].text
    if result.structured_content is not None:
        return result.structured_content
    return json.loads(result.content[0].text)


def _service(fake: FakeBoardsesh, settings: Settings, **kwargs) -> BoardseshService:
    return BoardseshService(lambda: BoardseshClient(settings, fake.http()), **kwargs)


@pytest.fixture
def server(fake: FakeBoardsesh, settings: Settings):
    return create_server(_service(fake, settings))


@pytest.fixture
def auth_server(fake: FakeBoardsesh, auth_settings: Settings):
    return create_server(_service(fake, auth_settings))


# -- registration -------------------------------------------------------------------------------


async def test_tools_are_listed_and_read_only(server):
    async with Client(server) as client:
        listed = await client.list_tools()
    assert {t.name for t in listed.tools} == ALL_TOOLS
    for tool in listed.tools:
        assert tool.annotations is not None and tool.annotations.read_only_hint is True
        assert tool.description and "Use " in tool.description
        assert "\n        " not in tool.description  # dedented
        props = tool.input_schema.get("properties") or {}
        undescribed = [k for k, v in props.items() if not v.get("description")]
        assert undescribed == [], f"{tool.name} has undescribed args: {undescribed}"


async def test_instructions_explain_the_multi_board_model(server):
    assert "Kilter" in server.instructions
    assert "board" in server.instructions
    assert "boardsesh_grade" in server.instructions


# -- public tools --------------------------------------------------------------------------------


async def test_summary(server):
    async with Client(server) as client:
        res = _payload(await client.call_tool("boardsesh_get_summary", {}))
    assert res["timezone"] == "UTC"
    assert res["total_entries"] == 8
    assert res["sends"] == 6
    assert res["boards"] == ["kilter", "tension"]
    assert res["hardest_send"]["grade"] == "6c/V5"
    assert res["ticks_per_board"] == [
        {"board": "kilter", "count": 6},
        {"board": "tension", "count": 2},
    ]


async def test_get_ascents_filters(server):
    async with Client(server) as client:
        all_rows = _payload(await client.call_tool("boardsesh_get_ascents", {"limit": 50}))
        tension = _payload(await client.call_tool("boardsesh_get_ascents", {"board": "tension"}))
        flashes = _payload(await client.call_tool("boardsesh_get_ascents", {"status": "flashes"}))
        attempts = _payload(await client.call_tool("boardsesh_get_ascents", {"status": "attempts"}))
        window = _payload(
            await client.call_tool(
                "boardsesh_get_ascents",
                {"start_date": "2026-01-08", "end_date": "2026-01-08"},
            )
        )
    assert all_rows["matching"] == 8
    assert {e["board"] for e in tension["entries"]} == {"tension"}
    assert all(e["status"] == "flash" for e in flashes["entries"])
    assert all(e["status"] == "attempt" for e in attempts["entries"])
    assert [e["climb_name"] for e in window["entries"]] == ["Kilter Project"]


async def test_get_ascents_entry_shape(server):
    async with Client(server) as client:
        res = _payload(await client.call_tool("boardsesh_get_ascents", {"limit": 1}))
    assert set(res["entries"][0]) == {
        "climb_name",
        "board",
        "date",
        "angle",
        "status",
        "attempts",
        "grade",
        "difficulty_id",
        "my_grade_id",
        "boardsesh_grade",
        "quality",
        "benchmark",
        "mirrored",
        "setter",
        "comment",
        "climb_uuid",
    }


async def test_bad_date_is_a_tool_error(server):
    async with Client(server) as client:
        res = await client.call_tool("boardsesh_get_ascents", {"start_date": "last tuesday"})
    assert res.is_error and "YYYY-MM-DD" in res.content[0].text


async def test_sessions_projects_pyramid_progression(server):
    async with Client(server) as client:
        sessions = _payload(await client.call_tool("boardsesh_get_sessions", {"limit": 2}))
        projects = _payload(await client.call_tool("boardsesh_get_projects", {}))
        pyramid = _payload(await client.call_tool("boardsesh_get_grade_pyramid", {}))
        progression = _payload(
            await client.call_tool("boardsesh_get_progression", {"period": "month"})
        )
    assert [s["date"] for s in sessions["sessions"]] == ["2026-02-10", "2026-02-03"]
    assert projects["matching"] == 1
    assert projects["projects"][0]["total_tries"] == 9
    assert pyramid["levels"][0]["grade"] == "6c/V5"
    assert [p["period"] for p in progression["periods"]] == ["2026-01", "2026-02"]


async def test_compare_boards_is_the_multi_board_answer(server):
    async with Client(server) as client:
        res = _payload(await client.call_tool("boardsesh_compare_boards", {}))
    boards = {b["board"]: b for b in res["boards"]}
    assert set(boards) == {"kilter", "tension"}
    assert boards["kilter"]["sends"] == 4
    assert boards["tension"]["flash_rate"] == 0.5
    assert boards["tension"]["median_boardsesh_grade"] is not None
    assert "not comparable" in res["note"]


async def test_get_grades(server):
    async with Client(server) as client:
        res = _payload(await client.call_tool("boardsesh_get_grades", {"board": "tension"}))
    assert res["board"] == "tension"
    assert res["source"] == "api"
    assert {"difficulty_id": 18, "grade": "6b/V4", "v_grade": "V4"} in res["grades"]


async def test_invalid_period_is_a_tool_error(server):
    async with Client(server) as client:
        res = await client.call_tool("boardsesh_get_progression", {"period": "decade"})
    assert res.is_error


async def test_limit_must_be_positive(server):
    async with Client(server) as client:
        res = await client.call_tool("boardsesh_get_ascents", {"limit": 0})
    assert res.is_error


# -- credential-gated tools ----------------------------------------------------------------------


@pytest.mark.parametrize("tool", sorted(CREDENTIAL_TOOLS))
async def test_credential_tools_explain_what_to_set(server, tool: str):
    args = {"climb_uuid": "climb-x"} if tool == "boardsesh_find_similar_climbs" else {}
    async with Client(server) as client:
        res = await client.call_tool(tool, args)
    assert res.is_error
    text = res.content[0].text
    assert "BOARDSESH_EMAIL" in text and "BOARDSESH_PASSWORD" in text


async def test_recommendations_with_credentials(auth_server):
    async with Client(auth_server) as client:
        res = _payload(await client.call_tool("boardsesh_recommend_climbs", {"limit": 5}))
    assert res["kind"] == "at_level"
    assert res["board_config"]["board"] == "kilter"
    assert res["board_config"]["angle"] == 40
    assert res["climbs"][0]["name"] == "Suggested Climb"
    assert res["climbs"][0]["my_sends"] == 0


async def test_search_climbs_with_credentials(auth_server):
    async with Client(auth_server) as client:
        res = _payload(
            await client.call_tool(
                "boardsesh_search_climbs",
                {"min_grade_id": 18, "max_grade_id": 20, "exclude_sent": True, "limit": 5},
            )
        )
    assert res["matching"] == 1
    assert res["climbs"][0]["name"] == "Found Climb"
    assert res["climbs"][0]["benchmark"] is True


async def test_similar_climbs_with_credentials(auth_server):
    async with Client(auth_server) as client:
        res = _payload(
            await client.call_tool(
                "boardsesh_find_similar_climbs", {"climb_uuid": "climb-abc", "limit": 3}
            )
        )
    assert res["climbs"][0]["similarity"] == 0.72


async def test_heatmap_with_credentials(auth_server, fake: FakeBoardsesh):
    async with Client(auth_server) as client:
        res = _payload(
            await client.call_tool("boardsesh_get_hold_heatmap", {"min_grade_id": 18, "limit": 5})
        )
    assert res["holds_analysed"] == 3
    assert res["personalised"] is False  # no cookie session, so community-only
    assert res["most_common_holds"][0]["hold_id"] == 1
    assert res["filters"] == {"minGrade": 18}
    assert res["board_config"]["layout_id"] == 1


async def test_heatmap_project_filter_passes_through(auth_server, fake: FakeBoardsesh):
    async with Client(auth_server) as client:
        res = _payload(
            await client.call_tool("boardsesh_get_hold_heatmap", {"only_my_projects": True})
        )
    assert res["filters"] == {"showOnlyAttempted": "true", "hideCompleted": "true"}


async def test_heatmap_personalises_when_the_api_returns_user_columns(
    fake: FakeBoardsesh, auth_settings: Settings
):
    for row, ascents, attempts in ((0, 20, 25), (1, 0, 1), (2, 0, 0)):
        fake.hold_stats[row].update({"userAscents": ascents, "userAttempts": attempts})
    fake.hold_stats[0]["totalUses"] = 60
    fake.hold_stats[1]["totalUses"] = 40
    server = create_server(_service(fake, auth_settings))
    async with Client(server) as client:
        res = _payload(await client.call_tool("boardsesh_get_hold_heatmap", {}))
    assert res["personalised"] is True
    assert res["most_avoided_by_me"][0]["hold_id"] == 2
    assert "relative_use" in res["note"]


# -- caching, config, secrets --------------------------------------------------------------------


async def test_logbook_is_fetched_once_across_tool_calls(fake: FakeBoardsesh, settings: Settings):
    clock = FakeClock()
    server = create_server(_service(fake, settings, cache_ttl=60.0, clock=clock))
    async with Client(server) as client:
        await client.call_tool("boardsesh_get_summary", {})
        await client.call_tool("boardsesh_get_sessions", {})
        await client.call_tool("boardsesh_get_projects", {})
        first = fake.operations.count("AscentsFeed")
        clock.now += 61
        await client.call_tool("boardsesh_compare_boards", {})
    assert first == 1
    assert fake.operations.count("AscentsFeed") == 2


async def test_concurrent_tool_calls_share_one_fetch(fake: FakeBoardsesh, settings: Settings):
    import asyncio

    server = create_server(_service(fake, settings))
    async with Client(server) as client:
        await asyncio.gather(
            client.call_tool("boardsesh_get_summary", {}),
            client.call_tool("boardsesh_get_sessions", {}),
            client.call_tool("boardsesh_compare_boards", {}),
        )
    assert fake.operations.count("AscentsFeed") == 1


async def test_missing_config_is_actionable():
    def factory():
        raise ConfigError("Boardsesh is not configured. Set BOARDSESH_USER to your ...")

    server = create_server(BoardseshService(factory))
    async with Client(server) as client:
        res = await client.call_tool("boardsesh_get_summary", {})
    assert res.is_error and "BOARDSESH_USER" in res.content[0].text


async def test_no_secrets_in_any_tool_output(auth_server):
    async with Client(auth_server) as client:
        listed = await client.list_tools()
        blobs = []
        for tool in listed.tools:
            args = {"climb_uuid": "climb-x"} if tool.name == "boardsesh_find_similar_climbs" else {}
            result = await client.call_tool(tool.name, args)
            blobs.append(json.dumps(result.model_dump(mode="json")))
    blob = "\n".join(blobs)
    for secret in (TEST_PASSWORD, TEST_EMAIL, ACCESS_1, REFRESH_1, "Bearer "):
        assert secret not in blob


# -- --check ------------------------------------------------------------------------------------


async def test_check_reports_counts_without_secrets(
    fake: FakeBoardsesh, auth_settings: Settings, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("BOARDSESH_USER", TEST_USER_ID)
    monkeypatch.setenv("BOARDSESH_EMAIL", TEST_EMAIL)
    monkeypatch.setenv("BOARDSESH_PASSWORD", TEST_PASSWORD)
    code, report = await run_check(_service(fake, auth_settings))
    assert code == 0, report
    assert "result:    ok" in report
    assert "public + credentials" in report
    assert TEST_USER_NAME in report
    assert "kilter=6, tension=2" in report
    assert "8 loaded of 8 entries, 6 sends, 4 sessions" in report
    assert "my boards: 1 saved" in report
    for secret in (TEST_PASSWORD, ACCESS_1, REFRESH_1, TEST_USER_ID):
        assert secret not in report


async def test_check_in_public_mode(fake: FakeBoardsesh, settings: Settings, monkeypatch):
    monkeypatch.setenv("BOARDSESH_USER", TEST_USER_ID)
    code, report = await run_check(_service(fake, settings))
    assert code == 0
    assert "public only" in report
    assert "my boards" not in report


async def test_check_reports_missing_config(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("BOARDSESH_USER", raising=False)
    code, report = await run_check()
    assert code == 1 and "config:    FAILED" in report


async def test_check_reports_an_unknown_user(fake: FakeBoardsesh, monkeypatch):
    monkeypatch.setenv("BOARDSESH_USER", "Nobody At All")
    settings = Settings(user="Nobody At All")
    code, report = await run_check(_service(fake, settings))
    assert code == 1
    assert "boardsesh: FAILED" in report and "No Boardsesh user found" in report


def test_main_check_exits_nonzero_without_config(monkeypatch: pytest.MonkeyPatch, capsys):
    from boardsesh_mcp.server import main

    monkeypatch.delenv("BOARDSESH_USER", raising=False)
    with pytest.raises(SystemExit) as info:
        main(["--check"])
    assert info.value.code == 1
    assert "config:    FAILED" in capsys.readouterr().out


def test_main_version_and_help(capsys):
    from boardsesh_mcp import __version__
    from boardsesh_mcp.server import main

    main(["--version"])
    assert __version__ in capsys.readouterr().out
    main(["--help"])
    help_text = capsys.readouterr().out
    assert "BOARDSESH_USER" in help_text and "--check" in help_text


# -- empty logbook (the new-user path) -----------------------------------------------------------


async def test_empty_logbook_explains_itself(fake: FakeBoardsesh, settings: Settings):
    """A Boardsesh account with no linked board syncs nothing; zeros must not look like history."""
    fake.feed = []
    server = create_server(_service(fake, settings))
    async with Client(server) as client:
        for tool in sorted(PUBLIC_TOOLS - {"boardsesh_get_grades"}):
            res = _payload(await client.call_tool(tool, {}))
            assert res["total_entries"] == 0, tool
            note = res["empty_logbook_note"]
            assert "link their board account" in note, tool
            assert "Do not present the zeros" in note, tool


async def test_empty_logbook_totals_are_zero_not_errors(fake: FakeBoardsesh, settings: Settings):
    fake.feed = []
    server = create_server(_service(fake, settings))
    async with Client(server) as client:
        summary = _payload(await client.call_tool("boardsesh_get_summary", {}))
        boards = _payload(await client.call_tool("boardsesh_compare_boards", {}))
        pyramid = _payload(await client.call_tool("boardsesh_get_grade_pyramid", {}))
    assert summary["sends"] == 0 and summary["boards"] == []
    assert summary["hardest_send"]["grade"] is None
    assert summary["session_count"] == 0
    assert boards["boards"] == []
    assert pyramid["total_sends"] == 0 and pyramid["levels"] == []


async def test_populated_logbook_has_no_empty_note(server):
    async with Client(server) as client:
        res = _payload(await client.call_tool("boardsesh_get_summary", {}))
    assert "empty_logbook_note" not in res
