"""Pinned GraphQL operation documents.

Every request this client can make is one of the constants below, sent with variables only.
The client never accepts a caller-supplied document, so no tool (and no prompt injected into
one) can reach a mutation such as ``deleteTick``. Adding a capability means adding a document
here deliberately.
"""

from __future__ import annotations

SEARCH_USERS = """
query SearchUsers($query: String!, $limit: Int) {
  searchUsers(input: {query: $query, limit: $limit}) {
    totalCount
    results { user { id displayName } recentAscentCount }
  }
}
"""

PUBLIC_PROFILE = """
query PublicProfile($userId: ID!) {
  publicProfile(userId: $userId) { id displayName followerCount followingCount }
}
"""

TICK_COUNTS_BY_BOARD = """
query TickCountsByBoard($userId: ID!) {
  userTickCountsByBoard(userId: $userId) { boardType count }
}
"""

PROFILE_STATS = """
query ProfileStats($userId: ID!) {
  userProfileStats(userId: $userId) {
    totalDistinctClimbs
    layoutStats {
      layoutKey
      boardType
      layoutId
      distinctClimbCount
      gradeCounts { grade count }
    }
  }
  userClimbPercentile(userId: $userId) {
    totalDistinctClimbs
    percentile
    totalActiveUsers
  }
}
"""

# The only genuinely multi-board logbook read: `boardTypes` accepts a list.
ASCENTS_FEED = """
query AscentsFeed($userId: ID!, $input: AscentFeedInput) {
  userAscentsFeed(userId: $userId, input: $input) {
    totalCount
    hasMore
    items {
      uuid
      climbUuid
      climbName
      setterUsername
      boardType
      boardDisplayName
      layoutId
      angle
      isMirror
      status
      attemptCount
      quality
      difficulty
      difficultyName
      consensusDifficulty
      consensusDifficultyName
      boardseshDifficulty
      boardseshConfidence
      isBenchmark
      comment
      climbedAt
    }
  }
}
"""

GRADES = """
query Grades($boardName: String!) {
  grades(boardName: $boardName) { difficultyId name }
}
"""

SMART_PLAYLIST = """
query SmartPlaylist($input: GetSmartPlaylistInput!) {
  smartPlaylist(input: $input) {
    meta { type userId userName climbCount }
    totalCount
    hasMore
    climbs {
      uuid
      name
      setter_username
      difficulty
      quality_average
      ascensionist_count
      benchmark_difficulty
      boardType
      angle
      statsAngle
      userAscents
      userAttempts
    }
  }
}
"""

SEARCH_CLIMBS = """
query SearchClimbs($input: ClimbSearchInput!) {
  searchClimbs(input: $input) {
    totalCount
    hasMore
    climbs {
      uuid
      name
      setter_username
      difficulty
      quality_average
      ascensionist_count
      benchmark_difficulty
      boardType
      statsAngle
      userAscents
      userAttempts
    }
  }
}
"""

SIMILAR_CLIMBS = """
query SimilarClimbs($input: SimilarClimbsInput!) {
  similarClimbs(input: $input) {
    uuid
    name
    similarity
    sharedHoldCount
    difficultyName
    qualityAverage
    ascensionistCount
  }
}
"""

# --- viewer-only (require credentials) --------------------------------------------------------

MY_BOARDS = """
query MyBoards {
  defaultBoard {
    uuid
    slug
    name
    boardType
    layoutId
    sizeId
    setIds
    angle
    layoutName
    sizeName
    isAngleAdjustable
  }
  myBoards(input: {limit: 20}) {
    totalCount
    boards {
      uuid
      slug
      name
      boardType
      layoutId
      sizeId
      setIds
      angle
      layoutName
      sizeName
    }
  }
}
"""

VIEWER_PROFILE = """
query ViewerProfile {
  profile { id displayName }
}
"""
