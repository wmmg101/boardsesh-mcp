"""Grade lookups.

Three scales are in play and it matters which one you show:

1. **Board-native** (Aurora ``difficulty_id``, an integer) is what every tick, filter and search
   argument speaks. Boardsesh serves the labels per board via ``grades(boardName:)``, e.g. id 10
   is ``"4a/V0"``. The Aurora boards (Kilter, Tension, Decoy, Touchstone, So iLL, Grasshopper)
   share one 39-step table; MoonBoard and Woods differ.
2. **Boardsesh local grade** — a shrunk grade within one board, on Boardsesh's shared scale.
3. **Boardsesh universal grade** — standardised across boards (Tension-anchored), which is what
   makes "is my Kilter V5 the same as my Tension V5" answerable.

Boardsesh's own precedence for display: the user's personal grade if they set one, otherwise the
board consensus, and the Boardsesh grade only to fill gaps and only when its confidence tier is
not ``setter_only`` or one of the ``*_estimate`` tiers (those cover angles nobody has climbed).

``FALLBACK_TABLE`` is the Aurora 39-step scale, used only if the live query fails.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from boardsesh_mcp.models import Grade

# (difficulty id, Font, V) for the Aurora scale shared by Kilter/Tension/Decoy/etc.
FALLBACK_TABLE: tuple[tuple[int, str, str], ...] = (
    (1, "1a", "V0"),
    (2, "1b", "V0"),
    (3, "1c", "V0"),
    (4, "2a", "V0"),
    (5, "2b", "V0"),
    (6, "2c", "V0"),
    (7, "3a", "V0"),
    (8, "3b", "V0"),
    (9, "3c", "V0"),
    (10, "4a", "V0"),
    (11, "4b", "V0"),
    (12, "4c", "V0"),
    (13, "5a", "V1"),
    (14, "5b", "V1"),
    (15, "5c", "V2"),
    (16, "6a", "V3"),
    (17, "6a+", "V3"),
    (18, "6b", "V4"),
    (19, "6b+", "V4"),
    (20, "6c", "V5"),
    (21, "6c+", "V5"),
    (22, "7a", "V6"),
    (23, "7a+", "V7"),
    (24, "7b", "V8"),
    (25, "7b+", "V8"),
    (26, "7c", "V9"),
    (27, "7c+", "V10"),
    (28, "8a", "V11"),
    (29, "8a+", "V12"),
    (30, "8b", "V13"),
    (31, "8b+", "V14"),
    (32, "8c", "V15"),
    (33, "8c+", "V16"),
    (34, "9a", "V17"),
    (35, "9a+", "V18"),
    (36, "9b", "V19"),
    (37, "9b+", "V20"),
    (38, "9c", "V21"),
    (39, "9c+", "V22"),
)

# Confidence tiers that describe an angle nobody has actually climbed, plus setter-only opinion.
UNTRUSTED_CONFIDENCE = frozenset(
    {
        "setter_only",
        "cross_angle_estimate",
        "moonboard_angle_estimate",
        "moonboard_wide_angle_estimate",
    }
)


@dataclass(frozen=True)
class GradeTable:
    """Board-native difficulty id to label. ``source`` is 'api' or 'fallback'."""

    grades: dict[int, Grade]
    source: str = "api"
    _order: tuple[int, ...] = field(default=(), repr=False)

    @classmethod
    def from_grades(cls, grades: list[Grade], source: str = "api") -> GradeTable:
        by_id = {g.id: g for g in grades}
        return cls(grades=by_id, source=source, _order=tuple(sorted(by_id)))

    @classmethod
    def fallback(cls) -> GradeTable:
        return cls.from_grades(
            [
                Grade(id=i, label=f"{font}/{v}", font_scale=font, v_scale=v)
                for i, font, v in FALLBACK_TABLE
            ],
            source="fallback",
        )

    def get(self, difficulty_id: int | None) -> Grade | None:
        return None if difficulty_id is None else self.grades.get(difficulty_id)

    def label(self, difficulty_id: int | None) -> str | None:
        grade = self.get(difficulty_id)
        return grade.label if grade else None

    def describe(self, difficulty_id: int | None) -> dict[str, object]:
        """Fields merged into tool output for a difficulty id."""
        grade = self.get(difficulty_id)
        return {
            "difficulty_id": difficulty_id,
            "grade": grade.label if grade else None,
            "v_grade": grade.v_scale if grade else None,
            "font_grade": grade.font_scale if grade else None,
        }

    # Only worth a note when the V-scale is genuinely uninformative: a logbook spanning many
    # V-grades does not need telling that Font is finer.
    COLLAPSED_V_GRADE_LIMIT = 2

    def grade_note(self, difficulty_ids: Iterable[int | None]) -> str | None:
        """Explain when the V-scale hides real differences (ids 10-12 are all V0)."""
        found = [g for g in (self.get(i) for i in difficulty_ids) if g]
        v_grades = {g.v_scale for g in found if g.v_scale}
        fonts = [g.font_scale for g in found if g.font_scale]
        if not fonts or len(v_grades) > self.COLLAPSED_V_GRADE_LIMIT:
            return None
        if len(set(fonts)) <= len(v_grades):
            return None
        order = {g.font_scale: g.id for g in found if g.font_scale}
        ranked = sorted(set(fonts), key=lambda f: order.get(f, 0))
        return (
            f"V-scale collapses these into {'/'.join(sorted(v_grades))}; use font_grade "
            f"({ranked[0]}-{ranked[-1]}) to distinguish levels."
        )


def parse_grade_label(label: str) -> tuple[str | None, str | None]:
    """Split a Boardsesh grade label like '6a/V3' into (font, v)."""
    if "/" in label:
        font, _, v = label.partition("/")
        return font.strip() or None, v.strip() or None
    return None, label.strip() or None


def v_number(label: str | None) -> int | None:
    """Numeric part of a V-grade label, for ordering. '6a/V3' and 'V3' both give 3."""
    if not label:
        return None
    _, v = parse_grade_label(label)
    if not v or not v.upper().startswith("V"):
        return None
    digits = v[1:].strip()
    return int(digits) if digits.isdigit() else None


def trustworthy_boardsesh_grade(value: float | None, confidence: str | None) -> float | None:
    """The cross-board Boardsesh grade, or None when its confidence tier is not ascent-backed."""
    if value is None:
        return None
    if confidence and confidence.lower() in UNTRUSTED_CONFIDENCE:
        return None
    return value
