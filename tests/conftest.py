"""Shared fixtures: synthetic data and a fake Boardsesh backend over httpx2.MockTransport."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx2
import pytest

from boardsesh_mcp.config import Settings
from boardsesh_mcp.endpoints import GRAPHQL_URL, NATIVE_LOGIN_URL, NATIVE_REFRESH_URL
from boardsesh_mcp.grades import GradeTable
from boardsesh_mcp.models import Ascent, Grade

TEST_USER_NAME = "Test Climber"
TEST_USER_ID = "11111111-2222-3333-4444-555555555555"
TEST_EMAIL = "test-climber@example.invalid"
TEST_PASSWORD = "test-password"
ACCESS_1 = "test-access-token-1"
ACCESS_2 = "test-access-token-2"
REFRESH_1 = "test-refresh-token-1"
REFRESH_2 = "test-refresh-token-2"

# Grade labels for the Aurora scale subset the fixtures use.
GRADE_ROWS = [
    {"difficultyId": 10, "name": "4a/V0"},
    {"difficultyId": 11, "name": "4b/V0"},
    {"difficultyId": 12, "name": "4c/V0"},
    {"difficultyId": 13, "name": "5a/V1"},
    {"difficultyId": 15, "name": "5c/V2"},
    {"difficultyId": 18, "name": "6b/V4"},
    {"difficultyId": 20, "name": "6c/V5"},
]


def feed_item(
    uuid: str,
    climb: str,
    *,
    board: str = "kilter",
    angle: int = 40,
    status: str = "send",
    attempts: int = 1,
    climbed_at: str = "2026-01-01T18:00:00Z",
    difficulty: int | None = None,
    consensus: int | None = 18,
    quality: int | None = None,
    benchmark: bool = False,
    boardsesh: float | None = None,
    confidence: str | None = "confirmed",
) -> dict[str, Any]:
    return {
        "uuid": uuid,
        "climbUuid": f"climb-{climb}",
        "climbName": climb,
        "setterUsername": "setter",
        "boardType": board,
        "boardDisplayName": f"{board} home wall",
        "layoutId": 1,
        "angle": angle,
        "isMirror": False,
        "status": status,
        "attemptCount": attempts,
        "quality": quality,
        "difficulty": difficulty,
        "difficultyName": None,
        "consensusDifficulty": consensus,
        "consensusDifficultyName": None,
        "boardseshDifficulty": boardsesh,
        "boardseshConfidence": confidence,
        "isBenchmark": benchmark,
        "comment": "",
        "climbedAt": climbed_at,
    }


def default_feed() -> list[dict[str, Any]]:
    """A small multi-board logbook: kilter + tension, sends, a flash, and a live project."""
    return [
        feed_item(
            "t1",
            "Kilter Send",
            status="send",
            attempts=3,
            consensus=18,
            climbed_at="2026-01-01T18:00:00Z",
            boardsesh=18.2,
            quality=4,
        ),
        feed_item(
            "t2",
            "Kilter Flash",
            status="flash",
            attempts=1,
            consensus=13,
            climbed_at="2026-01-01T18:20:00Z",
            boardsesh=13.1,
        ),
        feed_item(
            "t3",
            "Kilter Project",
            status="attempt",
            attempts=5,
            consensus=20,
            climbed_at="2026-01-01T18:40:00Z",
        ),
        feed_item(
            "t4",
            "Kilter Project",
            status="attempt",
            attempts=4,
            consensus=20,
            climbed_at="2026-01-08T18:00:00Z",
        ),
        feed_item(
            "t5",
            "Tension Send",
            board="tension",
            status="send",
            attempts=2,
            consensus=15,
            angle=20,
            climbed_at="2026-02-03T19:00:00Z",
            boardsesh=16.9,
        ),
        feed_item(
            "t6",
            "Tension Flash",
            board="tension",
            status="flash",
            attempts=1,
            consensus=13,
            angle=20,
            climbed_at="2026-02-10T19:30:00Z",
            boardsesh=14.0,
            benchmark=True,
        ),
        # personal grade overrides the consensus
        feed_item(
            "t7",
            "Graded Myself",
            status="send",
            attempts=1,
            difficulty=20,
            consensus=18,
            climbed_at="2026-02-10T20:00:00Z",
        ),
        # an estimate tier must not be trusted as a normalised grade
        feed_item(
            "t8",
            "Estimated",
            status="send",
            attempts=1,
            consensus=18,
            climbed_at="2026-02-10T20:30:00Z",
            boardsesh=18.0,
            confidence="cross_angle_estimate",
        ),
    ]


@dataclass
class FakeBoardsesh:
    """Scriptable fake for the GraphQL endpoint, the login endpoints and the heatmap route."""

    feed: list[dict[str, Any]] = field(default_factory=default_feed)
    grades: list[dict[str, Any]] = field(default_factory=lambda: list(GRADE_ROWS))
    users: list[dict[str, Any]] = field(
        default_factory=lambda: [
            {"user": {"id": TEST_USER_ID, "displayName": TEST_USER_NAME}, "recentAscentCount": 7}
        ]
    )
    hold_stats: list[dict[str, Any]] = field(
        default_factory=lambda: [
            {
                "holdId": 1,
                "totalUses": 40,
                "handUses": 30,
                "footUses": 8,
                "startingUses": 2,
                "finishUses": 0,
                "totalAscents": 400,
                "averageDifficulty": 18.2,
            },
            {
                "holdId": 2,
                "totalUses": 20,
                "handUses": 5,
                "footUses": 15,
                "startingUses": 0,
                "finishUses": 0,
                "totalAscents": 150,
                "averageDifficulty": 17.0,
            },
            {
                "holdId": 3,
                "totalUses": 3,
                "handUses": 3,
                "footUses": 0,
                "startingUses": 0,
                "finishUses": 0,
                "totalAscents": 9,
                "averageDifficulty": 21.0,
            },
        ]
    )
    password_ok: bool = True
    refresh_ok: bool = True
    login_status: int = 200
    graphql_status: int = 200
    rate_limit_queue: list[str | None] = field(default_factory=list)
    requests: list[httpx2.Request] = field(default_factory=list)
    operations: list[str] = field(default_factory=list)
    login_calls: list[dict[str, Any]] = field(default_factory=list)
    _issued: int = 0

    def http(self) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(transport=httpx2.MockTransport(self.handle))

    # -- routing ----------------------------------------------------------------------------

    def handle(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        url = str(request.url)
        if self.rate_limit_queue:
            retry_after = self.rate_limit_queue.pop(0)
            headers = {} if retry_after is None else {"Retry-After": retry_after}
            return httpx2.Response(429, headers=headers, json={"error": "slow down"})
        if url == GRAPHQL_URL:
            return self._graphql(request)
        if url in (NATIVE_LOGIN_URL, NATIVE_REFRESH_URL):
            return self._login(request, url)
        if "/heatmap" in url:
            return httpx2.Response(200, json={"holdStats": self.hold_stats})
        return httpx2.Response(404, json={"error": "unknown endpoint"})

    def _login(self, request: httpx2.Request, url: str) -> httpx2.Response:
        body = json.loads(request.content or b"{}")
        self.login_calls.append(body)
        if self.login_status != 200:
            return httpx2.Response(self.login_status, json={"error": "nope"})
        if url == NATIVE_LOGIN_URL:
            ok = (
                self.password_ok
                and body.get("email") == TEST_EMAIL
                and body.get("password") == TEST_PASSWORD
            )
            if not ok:
                return httpx2.Response(401, json={"error": "Invalid credentials"})
        elif not self.refresh_ok or body.get("refreshToken") not in (REFRESH_1, REFRESH_2):
            return httpx2.Response(401, json={"error": "Token is not active"})
        self._issued += 1
        return httpx2.Response(
            200,
            json={
                "jwt": ACCESS_1 if self._issued == 1 else ACCESS_2,
                "refreshToken": REFRESH_1 if self._issued == 1 else REFRESH_2,
                "expiresIn": 600,
            },
        )

    def _graphql(self, request: httpx2.Request) -> httpx2.Response:
        if self.graphql_status != 200:
            return httpx2.Response(self.graphql_status, json={"error": "boom"})
        body = json.loads(request.content or b"{}")
        document = body.get("query") or ""
        variables = body.get("variables") or {}
        name = _operation_name(document)
        self.operations.append(name)
        authed = "Authorization" in request.headers
        handler = getattr(self, f"_op_{name}", None)
        if handler is None:
            return httpx2.Response(200, json={"errors": [{"message": f"unknown op {name}"}]})
        return httpx2.Response(200, json=handler(variables, authed))

    # -- operations -------------------------------------------------------------------------

    def _op_SearchUsers(self, variables: dict[str, Any], authed: bool) -> dict[str, Any]:
        query = str(variables.get("query") or "").lower()
        hits = [u for u in self.users if query in str(u["user"]["displayName"]).lower()]
        return {"data": {"searchUsers": {"totalCount": len(hits), "results": hits}}}

    def _op_PublicProfile(self, variables: dict[str, Any], authed: bool) -> dict[str, Any]:
        return {
            "data": {
                "publicProfile": {
                    "id": variables.get("userId"),
                    "displayName": TEST_USER_NAME,
                    "followerCount": 1,
                    "followingCount": 2,
                }
            }
        }

    def _op_TickCountsByBoard(self, variables: dict[str, Any], authed: bool) -> dict[str, Any]:
        counts: dict[str, int] = {}
        for item in self.feed:
            counts[item["boardType"]] = counts.get(item["boardType"], 0) + 1
        return {
            "data": {
                "userTickCountsByBoard": [
                    {"boardType": b, "count": c} for b, c in sorted(counts.items())
                ]
            }
        }

    def _op_ProfileStats(self, variables: dict[str, Any], authed: bool) -> dict[str, Any]:
        return {
            "data": {
                "userProfileStats": {
                    "totalDistinctClimbs": 6,
                    "layoutStats": [
                        {
                            "layoutKey": "kilter-1",
                            "boardType": "kilter",
                            "layoutId": 1,
                            "distinctClimbCount": 4,
                            "gradeCounts": [{"grade": "6b/V4", "count": 2}],
                        }
                    ],
                },
                "userClimbPercentile": {
                    "totalDistinctClimbs": 6,
                    "percentile": 42.5,
                    "totalActiveUsers": 2980,
                },
            }
        }

    def _op_AscentsFeed(self, variables: dict[str, Any], authed: bool) -> dict[str, Any]:
        payload = variables.get("input") or {}
        items = list(self.feed)
        boards = payload.get("boardTypes")
        if boards:
            items = [i for i in items if i["boardType"] in boards]
        limit = int(payload.get("limit") or 20)
        offset = int(payload.get("offset") or 0)
        window = items[offset : offset + limit]
        return {
            "data": {
                "userAscentsFeed": {
                    "totalCount": len(items),
                    "hasMore": offset + limit < len(items),
                    "items": window,
                }
            }
        }

    def _op_Grades(self, variables: dict[str, Any], authed: bool) -> dict[str, Any]:
        return {"data": {"grades": self.grades}}

    def _op_SmartPlaylist(self, variables: dict[str, Any], authed: bool) -> dict[str, Any]:
        payload = variables.get("input") or {}
        return {
            "data": {
                "smartPlaylist": {
                    "meta": {
                        "type": payload.get("type"),
                        "userId": payload.get("userId"),
                        "userName": TEST_USER_NAME,
                        "climbCount": 1,
                    },
                    "totalCount": 1,
                    "hasMore": False,
                    "climbs": [
                        {
                            "uuid": "climb-suggested",
                            "name": "Suggested Climb",
                            "setter_username": "setter",
                            "difficulty": "6c/V5",
                            "quality_average": "4.5",
                            "ascensionist_count": 120,
                            "benchmark_difficulty": None,
                            "boardType": "kilter",
                            "angle": 40,
                            "statsAngle": 40,
                            "userAscents": 0,
                            "userAttempts": 0,
                        }
                    ],
                }
            }
        }

    def _op_SearchClimbs(self, variables: dict[str, Any], authed: bool) -> dict[str, Any]:
        return {
            "data": {
                "searchClimbs": {
                    "totalCount": 1,
                    "hasMore": False,
                    "climbs": [
                        {
                            "uuid": "climb-found",
                            "name": "Found Climb",
                            "setter_username": "setter",
                            "difficulty": "6b/V4",
                            "quality_average": "4.0",
                            "ascensionist_count": 55,
                            "benchmark_difficulty": "6b",
                            "boardType": "kilter",
                            "statsAngle": 40,
                            "userAscents": 0,
                            "userAttempts": 1,
                        }
                    ],
                }
            }
        }

    def _op_SimilarClimbs(self, variables: dict[str, Any], authed: bool) -> dict[str, Any]:
        return {
            "data": {
                "similarClimbs": [
                    {
                        "uuid": "climb-similar",
                        "name": "Similar Climb",
                        "similarity": 0.72,
                        "sharedHoldCount": 8,
                        "difficultyName": "6b/V4",
                        "qualityAverage": 4.2,
                        "ascensionistCount": 31,
                    }
                ]
            }
        }

    def _op_MyBoards(self, variables: dict[str, Any], authed: bool) -> dict[str, Any]:
        if not authed:
            return {
                "errors": [{"message": "Authentication required to perform this operation"}],
                "data": None,
            }
        board = {
            "uuid": "board-1",
            "slug": "home-wall",
            "name": "Home wall",
            "boardType": "kilter",
            "layoutId": 1,
            "sizeId": 10,
            "setIds": "1,20",
            "angle": 40,
            "layoutName": "Kilter Board Original",
            "sizeName": "12x12",
            "isAngleAdjustable": True,
        }
        return {
            "data": {
                "defaultBoard": board,
                "myBoards": {"totalCount": 1, "boards": [board]},
            }
        }

    def _op_ViewerProfile(self, variables: dict[str, Any], authed: bool) -> dict[str, Any]:
        if not authed:
            return {
                "errors": [{"message": "Authentication required to perform this operation"}],
                "data": None,
            }
        return {"data": {"profile": {"id": TEST_USER_ID, "displayName": TEST_USER_NAME}}}


def _operation_name(document: str) -> str:
    for line in document.splitlines():
        line = line.strip()
        if line.startswith("query "):
            return line[len("query ") :].split("(")[0].split("{")[0].strip()
    return "unknown"


# -- fixtures -----------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _deterministic_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests must not depend on the host timezone or on real credentials in the environment."""
    monkeypatch.setenv("BOARDSESH_TIMEZONE", "UTC")
    for var in ("BOARDSESH_USER", "BOARDSESH_EMAIL", "BOARDSESH_PASSWORD"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def fake() -> FakeBoardsesh:
    return FakeBoardsesh()


@pytest.fixture
def settings() -> Settings:
    return Settings(user=TEST_USER_ID)


@pytest.fixture
def named_settings() -> Settings:
    return Settings(user=TEST_USER_NAME)


@pytest.fixture
def auth_settings() -> Settings:
    return Settings(user=TEST_USER_ID, email=TEST_EMAIL, password=TEST_PASSWORD)


@pytest.fixture
def grades() -> GradeTable:
    return GradeTable.from_grades([g for g in map(Grade.from_api, GRADE_ROWS) if g])


@pytest.fixture
def ascents() -> list[Ascent]:
    return [Ascent.from_feed_item(i) for i in default_feed()]
