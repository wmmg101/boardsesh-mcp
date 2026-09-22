"""Opt-in smoke test against a real Boardsesh account.

Runs only when BOARDSESH_INTEGRATION=1 and BOARDSESH_USER are set. Asserts shapes only; never
prints or stores logbook entries.
"""

from __future__ import annotations

import os

import pytest

from boardsesh_mcp.auth import AuthError
from boardsesh_mcp.client import BoardseshAPIError, BoardseshClient
from boardsesh_mcp.config import Settings

pytestmark = pytest.mark.skipif(
    os.environ.get("BOARDSESH_INTEGRATION") != "1" or not os.environ.get("BOARDSESH_USER"),
    reason="set BOARDSESH_INTEGRATION=1 plus BOARDSESH_USER to run",
)


async def test_public_reads_have_expected_shape():
    client = BoardseshClient(Settings.from_env())
    try:
        user_id, _ = await client.resolve_user()
        counts = await client.get_tick_counts()
        ascents, total = await client.get_all_ascents(page_size=50, max_pages=4)
    except (AuthError, BoardseshAPIError) as exc:
        pytest.fail(str(exc), pytrace=False)
    finally:
        await client.aclose()

    assert user_id
    assert isinstance(total, int) and total >= 0
    assert len(ascents) <= total or total == 0
    logged_boards = {c.board for c in counts}
    for ascent in ascents[:50]:
        assert ascent.climb_uuid
        assert ascent.status in ("flash", "send", "attempt")
        assert ascent.attempts >= 1
        assert ascent.board in logged_boards or not logged_boards

    for board in sorted(logged_boards)[:2]:
        table = await client.get_grades(board)
        assert table.grades, f"no grade table for {board}"


async def test_viewer_reads_when_credentials_are_configured():
    settings = Settings.from_env()
    if not settings.has_credentials:
        pytest.skip("no BOARDSESH_EMAIL / BOARDSESH_PASSWORD configured")
    client = BoardseshClient(settings)
    try:
        viewer_id = await client.get_viewer_id()
        default, boards = await client.get_my_boards()
    except (AuthError, BoardseshAPIError) as exc:
        pytest.fail(str(exc), pytrace=False)
    finally:
        await client.aclose()
    assert viewer_id
    for board in ([default] if default else []) + boards:
        assert board.board and board.layout_id and board.size_id and board.set_ids
