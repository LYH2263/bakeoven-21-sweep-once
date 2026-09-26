"""Oven scheduling with half-open ferment+bake intervals and next free window.

Conflict pairs and merged busy spans for one oven come from a single
left-to-right sweep over that oven's occupancies.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Interval:
    start: int  # minutes from day origin
    end: int  # exclusive

    def overlaps(self, other: "Interval") -> bool:
        return self.start < other.end and other.start < self.end


@dataclass(frozen=True)
class RecipeDurations:
    ferment_min: int
    bake_min: int

    @property
    def total(self) -> int:
        return self.ferment_min + self.bake_min


@dataclass(frozen=True)
class Occupancy:
    oven_id: int
    interval: Interval
    phase: str  # ferment | bake
    batch_id: int


@dataclass(frozen=True)
class OverlapPair:
    """Two occupancies genuinely overlapping on the same oven.

    Endpoint-touching occupancies are never paired: intervals are
    half-open, so ``earlier.end == later.start`` is allowed.
    """

    earlier: Occupancy
    later: Occupancy

    @property
    def phases(self) -> tuple[str, str]:
        return (self.earlier.phase, self.later.phase)


@dataclass(frozen=True)
class OvenTimeline:
    oven_id: int
    busy: tuple[Interval, ...]          # merged busy spans
    overlaps: tuple[OverlapPair, ...]   # per-phase overlap pairs


def build_occupancies(
    oven_id: int,
    batch_id: int,
    start_min: int,
    recipe: RecipeDurations,
) -> list[Occupancy]:
    ferment = Interval(start_min, start_min + recipe.ferment_min)
    bake = Interval(ferment.end, ferment.end + recipe.bake_min)
    return [
        Occupancy(oven_id, ferment, "ferment", batch_id),
        Occupancy(oven_id, bake, "bake", batch_id),
    ]


def scan_oven(occupancies: list[Occupancy], oven_id: int) -> OvenTimeline:
    """Single sweep producing both overlap pairs and merged busy spans.

    Intervals are visited once in (start, -end) order. Starts are
    processed before ends at the same coordinate, so touching endpoints
    neither merge into a busy span nor register as an overlap. An
    interval fully contained in another still yields its pair even
    though the merged span simply keeps the outer bounds.
    """
    ordered = sorted(
        (o for o in occupancies if o.oven_id == oven_id),
        key=lambda o: (o.interval.start, -o.interval.end),
    )

    active: list[Occupancy] = []  # started but not yet past the current start
    pairs: list[OverlapPair] = []

    busy: list[Interval] = []
    cur_start = 0
    cur_end = 0
    has_cur = False

    for occ in ordered:
        start, end = occ.interval.start, occ.interval.end

        # Half-open: anything ending at or before this start is gone,
        # including an interval that merely touches this endpoint.
        active = [a for a in active if a.interval.end > start]
        # Mirror Interval.overlaps exactly (a.start <= start here):
        # a.end > start and end > a.start. The second clause matters
        # for zero-length occupancies.
        for a in active:
            if end > a.interval.start:
                pairs.append(OverlapPair(a, occ))
        active.append(occ)

        # Merge busy spans in the same pass; strict inequality keeps
        # touching spans as two separate busy segments.
        if not has_cur:
            cur_start, cur_end, has_cur = start, end, True
        elif start < cur_end:
            if end > cur_end:
                cur_end = end
        else:
            busy.append(Interval(cur_start, cur_end))
            cur_start, cur_end = start, end

    if has_cur:
        busy.append(Interval(cur_start, cur_end))

    return OvenTimeline(
        oven_id=oven_id,
        busy=tuple(busy),
        overlaps=tuple(pairs),
    )


def scan_ovens(occupancies: list[Occupancy]) -> dict[int, OvenTimeline]:
    timelines: dict[int, OvenTimeline] = {}
    for oven_id in {o.oven_id for o in occupancies}:
        timelines[oven_id] = scan_oven(occupancies, oven_id)
    return timelines


def find_conflicts(existing: list[Occupancy], candidates: list[Occupancy]) -> list[tuple[Occupancy, Occupancy]]:
    """Cross pairs between scheduled occupancies and new candidates.

    Backed by the single sweep; only pairs straddling the two groups are
    returned, oriented as (existing, candidate) and ordered as in the
    historical nested-loop output.
    """
    ex_index = {id(o): i for i, o in enumerate(existing)}
    cand_index = {id(o): i for i, o in enumerate(candidates)}

    hits: list[tuple[int, int, Occupancy, Occupancy]] = []
    for oven_id in {o.oven_id for o in existing} | {o.oven_id for o in candidates}:
        for pair in scan_oven([*existing, *candidates], oven_id).overlaps:
            a, b = pair.earlier, pair.later
            a_ex, a_cand = id(a) in ex_index, id(a) in cand_index
            b_ex, b_cand = id(b) in ex_index, id(b) in cand_index
            if a_ex and b_cand and not a_cand:
                ex, cand, ci, ei = a, b, cand_index[id(b)], ex_index[id(a)]
            elif b_ex and a_cand and not b_cand:
                ex, cand, ci, ei = b, a, cand_index[id(a)], ex_index[id(b)]
            else:
                continue
            hits.append((ci, ei, ex, cand))

    hits.sort(key=lambda h: (h[0], h[1]))
    return [(ex, cand) for _, _, ex, cand in hits]


def next_free_window(
    existing: list[Occupancy],
    oven_id: int,
    duration: int,
    search_from: int = 0,
    search_to: int = 24 * 60,
) -> Interval | None:
    """Find earliest half-open [start, start+duration) free on oven."""
    if duration <= 0:
        return None
    timeline = scan_oven(existing, oven_id)
    cursor = search_from
    for iv in timeline.busy:
        if iv.end <= cursor:
            continue
        if iv.start >= cursor + duration:
            end = cursor + duration
            if end <= search_to:
                return Interval(cursor, end)
            return None
        cursor = max(cursor, iv.end)
    if cursor + duration <= search_to:
        return Interval(cursor, cursor + duration)
    return None
