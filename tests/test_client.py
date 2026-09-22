from __future__ import annotations

import httpx2
import pytest

from boardsesh_mcp.auth import AuthError, TokenManager
from boardsesh_mcp.client import BoardseshAPIError, BoardseshClient
from boardsesh_mcp.config import Settings
from tests.conftest import (
    ACCESS_1,
    ACCESS_2,
    REFRESH_1,
    TEST_EMAIL,
    TEST_PASSWORD,
    TEST_USER_ID,
    TEST_USER_NAME,
    FakeBoardsesh,
)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class RecordingSleep:
    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


# -- identity -----------------------------------------------------------------------------------


async def test_user_id_is_used_directly(fake: FakeBoardsesh, settings: Settings):
    client = BoardseshClient(settings, fake.http())
    user_id, name = await client.resolve_user()
    assert user_id == TEST_USER_ID
    assert name == TEST_USER_NAME
    assert "SearchUsers" not in fake.operations


async def test_display_name_is_resolved(fake: FakeBoardsesh, named_settings: Settings):
    client = BoardseshClient(named_settings, fake.http())
    user_id, name = await client.resolve_user()
    assert user_id == TEST_USER_ID
    assert name == TEST_USER_NAME
    assert fake.operations[0] == "SearchUsers"
    # resolution is cached
    await client.resolve_user()
    assert fake.operations.count("SearchUsers") == 1


async def test_unknown_display_name_is_actionable(fake: FakeBoardsesh):
    client = BoardseshClient(Settings(user="Nobody At All"), fake.http())
    with pytest.raises(BoardseshAPIError, match="No Boardsesh user found"):
        await client.resolve_user()


async def test_ambiguous_display_name_asks_for_precision(fake: FakeBoardsesh):
    fake.users = [
        {"user": {"id": "id-1", "displayName": "Climber One"}, "recentAscentCount": 1},
        {"user": {"id": "id-2", "displayName": "Climber Two"}, "recentAscentCount": 9},
    ]
    client = BoardseshClient(Settings(user="Climber"), fake.http())
    with pytest.raises(BoardseshAPIError) as info:
        await client.resolve_user()
    assert "exact display name" in str(info.value)
    assert "Climber One" in str(info.value)


async def test_exact_match_wins_over_more_active_partial(fake: FakeBoardsesh):
    fake.users = [
        {"user": {"id": "id-busy", "displayName": "Climber Two"}, "recentAscentCount": 99},
        {"user": {"id": "id-exact", "displayName": "Climber"}, "recentAscentCount": 1},
    ]
    client = BoardseshClient(Settings(user="climber"), fake.http())
    user_id, _ = await client.resolve_user()
    assert user_id == "id-exact"


# -- logbook ------------------------------------------------------------------------------------


async def test_get_ascents_parses_the_feed(fake: FakeBoardsesh, settings: Settings):
    client = BoardseshClient(settings, fake.http())
    ascents, total, has_more = await client.get_ascents(limit=3)
    assert len(ascents) == 3
    assert total == 8
    assert has_more is True
    assert ascents[0].climb_name == "Kilter Send"


async def test_get_all_ascents_pages_through(fake: FakeBoardsesh, settings: Settings):
    client = BoardseshClient(settings, fake.http())
    ascents, total = await client.get_all_ascents(page_size=3)
    assert len(ascents) == 8
    assert total == 8
    assert fake.operations.count("AscentsFeed") == 3


async def test_get_all_ascents_respects_max_pages(fake: FakeBoardsesh, settings: Settings):
    client = BoardseshClient(settings, fake.http())
    ascents, _ = await client.get_all_ascents(page_size=2, max_pages=2)
    assert len(ascents) == 4


async def test_tick_counts_sorted_by_volume(fake: FakeBoardsesh, settings: Settings):
    client = BoardseshClient(settings, fake.http())
    counts = await client.get_tick_counts()
    assert [c.board for c in counts] == ["kilter", "tension"]
    assert counts[0].count == 6


async def test_grades_are_cached_per_board(fake: FakeBoardsesh, settings: Settings):
    client = BoardseshClient(settings, fake.http())
    table = await client.get_grades("kilter")
    assert table.source == "api"
    assert table.describe(18)["grade"] == "6b/V4"
    await client.get_grades("kilter")
    assert fake.operations.count("Grades") == 1


async def test_grades_fall_back_when_the_call_fails(fake: FakeBoardsesh, settings: Settings):
    fake.graphql_status = 500
    client = BoardseshClient(settings, fake.http())
    table = await client.get_grades("kilter")
    assert table.source == "fallback"
    assert table.describe(22)["grade"] == "7a/V6"


# -- auth ---------------------------------------------------------------------------------------


async def test_public_mode_sends_no_authorization_header(fake: FakeBoardsesh, settings: Settings):
    client = BoardseshClient(settings, fake.http())
    await client.get_tick_counts()
    assert all("Authorization" not in r.headers for r in fake.requests)


async def test_viewer_query_requires_credentials(fake: FakeBoardsesh, settings: Settings):
    """Asking for viewer-only data without credentials must say exactly what to set."""
    client = BoardseshClient(settings, fake.http())
    with pytest.raises(AuthError) as info:
        await client.get_my_boards()
    assert "BOARDSESH_EMAIL" in str(info.value)
    assert "BOARDSESH_PASSWORD" in str(info.value)
    # nothing was sent to Boardsesh at all
    assert not fake.login_calls


async def test_credentials_unlock_viewer_queries(fake: FakeBoardsesh, auth_settings: Settings):
    client = BoardseshClient(auth_settings, fake.http())
    default, boards = await client.get_my_boards()
    assert default is not None and default.board == "kilter"
    assert default.layout_id == 1 and default.size_id == 10 and default.set_ids == "1,20"
    assert len(boards) == 1
    graphql = [r for r in fake.requests if "graphql" in str(r.url)]
    assert graphql[-1].headers["Authorization"] == f"Bearer {ACCESS_1}"
    assert fake.login_calls[0]["email"] == TEST_EMAIL


async def test_token_is_reused_then_refreshed(fake: FakeBoardsesh, auth_settings: Settings):
    clock = Clock()
    http = fake.http()
    client = BoardseshClient(
        auth_settings, http, token_manager=TokenManager(auth_settings, http, clock=clock)
    )
    await client.get_my_boards()
    await client.get_my_boards()
    assert len(fake.login_calls) == 1  # cached
    clock.now += 600  # past the 600s lifetime minus margin
    await client.get_my_boards()
    assert len(fake.login_calls) == 2
    assert fake.login_calls[1]["refreshToken"] == REFRESH_1


async def test_expired_token_retried_once_on_auth_error(
    fake: FakeBoardsesh, auth_settings: Settings
):
    """Boardsesh answers a stale token with a resolver error, not a 401."""
    calls = {"n": 0}
    original = fake._op_MyBoards

    def flaky(variables, authed):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"errors": [{"message": "Authentication required to perform this operation"}]}
        return original(variables, authed)

    fake._op_MyBoards = flaky  # type: ignore[method-assign]
    client = BoardseshClient(auth_settings, fake.http())
    default, _ = await client.get_my_boards()
    assert default is not None
    assert len(fake.login_calls) == 2  # re-authenticated after the stale-token error


async def test_bad_password_is_reported_without_secrets(
    fake: FakeBoardsesh, auth_settings: Settings
):
    fake.password_ok = False
    client = BoardseshClient(auth_settings, fake.http())
    with pytest.raises(AuthError) as info:
        await client.get_my_boards()
    message = str(info.value)
    assert "BOARDSESH_EMAIL" in message
    assert TEST_PASSWORD not in message


async def test_rejected_login_is_not_retried_immediately(
    fake: FakeBoardsesh, auth_settings: Settings
):
    fake.password_ok = False
    clock = Clock()
    http = fake.http()
    tokens = TokenManager(auth_settings, http, clock=clock, login_failure_cooldown=120)
    client = BoardseshClient(auth_settings, http, token_manager=tokens)
    with pytest.raises(AuthError):
        await client.get_my_boards()
    for _ in range(3):
        with pytest.raises(AuthError, match="Not retrying"):
            await client.get_my_boards()
    assert len(fake.login_calls) == 1
    clock.now += 121
    fake.password_ok = True
    default, _ = await client.get_my_boards()
    assert default is not None


async def test_rate_limited_login_does_not_trigger_cooldown(
    fake: FakeBoardsesh, auth_settings: Settings
):
    fake.login_status = 429
    client = BoardseshClient(auth_settings, fake.http())
    with pytest.raises(AuthError) as info:
        await client.get_my_boards()
    assert "rate-limiting" in str(info.value)
    assert info.value.rejected is False


async def test_failing_frame_never_holds_the_password(fake: FakeBoardsesh, auth_settings: Settings):
    """pytest and debuggers print the raising frame's locals."""
    import traceback

    fake.password_ok = False
    http = fake.http()
    tokens = TokenManager(auth_settings, http, clock=Clock())
    try:
        await tokens.get_access_token()
    except AuthError as exc:
        frames = list(traceback.walk_tb(exc.__traceback__))
        blob = repr(frames[-1][0].f_locals)
        assert TEST_PASSWORD not in blob
        assert "password" not in blob
    else:
        raise AssertionError("expected AuthError")


# -- transport ----------------------------------------------------------------------------------


async def test_429_is_retried_with_retry_after(fake: FakeBoardsesh, settings: Settings):
    fake.rate_limit_queue = ["2"]
    sleep = RecordingSleep()
    client = BoardseshClient(settings, fake.http(), sleep=sleep)
    counts = await client.get_tick_counts()
    assert counts
    assert sleep.calls == [2.0]


async def test_429_without_retry_after_fails_fast(fake: FakeBoardsesh, settings: Settings):
    fake.rate_limit_queue = [None]
    sleep = RecordingSleep()
    client = BoardseshClient(settings, fake.http(), sleep=sleep)
    with pytest.raises(BoardseshAPIError, match="rate-limiting"):
        await client.get_tick_counts()
    assert sleep.calls == []


async def test_429_retries_are_bounded(fake: FakeBoardsesh, settings: Settings):
    fake.rate_limit_queue = ["1", "1", "1", "1"]
    sleep = RecordingSleep()
    client = BoardseshClient(settings, fake.http(), sleep=sleep, max_rate_limit_retries=2)
    with pytest.raises(BoardseshAPIError, match="rate-limiting"):
        await client.get_tick_counts()
    assert sleep.calls == [1.0, 1.0]


async def test_network_error_is_redacted(auth_settings: Settings):
    def boom(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError(f"cannot connect, password={TEST_PASSWORD}")

    http = httpx2.AsyncClient(transport=httpx2.MockTransport(boom))
    client = BoardseshClient(auth_settings, http)
    with pytest.raises((BoardseshAPIError, AuthError)) as info:
        await client.get_tick_counts()
    assert TEST_PASSWORD not in str(info.value)


async def test_user_agent_is_not_agentic(fake: FakeBoardsesh, settings: Settings):
    """Boardsesh's WAF blocks crawler user agents zone-wide."""
    client = BoardseshClient(settings)
    ua = client._http.headers["User-Agent"].lower()
    await client.aclose()
    for blocked in ("gptbot", "claudebot", "claude", "perplexity", "ccbot", "bot/"):
        assert blocked not in ua


async def test_repr_has_no_secrets(fake: FakeBoardsesh, auth_settings: Settings):
    client = BoardseshClient(auth_settings, fake.http())
    await client.get_my_boards()
    assert TEST_PASSWORD not in repr(client)
    assert ACCESS_1 not in repr(client)
    assert ACCESS_2 not in repr(client)


# -- heatmap ------------------------------------------------------------------------------------


async def test_heatmap_parses_hold_stats(fake: FakeBoardsesh, auth_settings: Settings):
    from boardsesh_mcp.client import BoardConfig

    client = BoardseshClient(auth_settings, fake.http())
    config = BoardConfig(board="kilter", layout_id=1, size_id=10, set_ids="1,20", angle=40)
    holds = await client.get_hold_heatmap(config, params={"minGrade": 18})
    assert [h.hold_id for h in holds] == [1, 2, 3]
    assert holds[0].hand_uses == 30
    request = next(r for r in fake.requests if "heatmap" in str(r.url))
    assert "/api/v1/kilter/1/10/1,20/40/heatmap" in str(request.url)
    assert "minGrade=18" in str(request.url)
