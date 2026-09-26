"""Oven scheduling with half-open ferment+bake intervals and next free window."""

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
class OvenTimeline:
    """One oven's occupancy collapsed by a single sweep.

    busy: merged busy segments — strictly overlapping intervals are unioned,
    touching endpoints (end == start) stay separate segments.
    overlaps: pairwise half-open overlaps with the phase kept on each
    Occupancy (ferment/ferment, bake/bake, ferment/bake); a contained
    interval still pairs with its container even though merging hides it.
    """

    busy: list[Interval]
    overlaps: list[tuple[Occupancy, Occupancy]]


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


def scan_oven_timeline(occupancies: list[Occupancy]) -> OvenTimeline:
    """Single sweep over one oven's occupancies -> merged busy + overlap pairs.

    Intervals are visited once in (start, end) order. Each interval either
    extends the current merged segment (strict overlap) or closes it and
    opens a new one (disjoint or merely touching). While joining a segment
    the interval is paired with every earlier member it strictly overlaps,
    so containment still reports the inner pair.
    """
    ordered = sorted(occupancies, key=lambda o: (o.interval.start, o.interval.end))
    busy: list[Interval] = []
    overlaps: list[tuple[Occupancy, Occupancy]] = []
    segment: Interval | None = None
    members: list[Occupancy] = []
    for occ in ordered:
        iv = occ.interval
        if segment is not None and iv.start < segment.end:
            # sorted by start => prev.start <= iv.start, so a strict
            # prev.end > iv.start is exactly the half-open overlap test
            for prev in members:
                if prev.interval.end > iv.start:
                    overlaps.append((prev, occ))
            segment = Interval(segment.start, max(segment.end, iv.end))
            members.append(occ)
        else:
            if segment is not None:
                busy.append(segment)
            segment = Interval(iv.start, iv.end)
            members = [occ]
    if segment is not None:
        busy.append(segment)
    return OvenTimeline(busy=busy, overlaps=overlaps)


def find_conflicts(existing: list[Occupancy], candidates: list[Occupancy]) -> list[tuple[Occupancy, Occupancy]]:
    cand_pos = {id(o): i for i, o in enumerate(candidates)}
    ex_pos = {id(o): i for i, o in enumerate(existing)}
    hits: list[tuple[Occupancy, Occupancy]] = []
    for oven_id in {o.oven_id for o in candidates}:
        pool = [o for o in existing if o.oven_id == oven_id]
        pool += [o for o in candidates if o.oven_id == oven_id]
        for a, b in scan_oven_timeline(pool).overlaps:
            a_cand = id(a) in cand_pos
            b_cand = id(b) in cand_pos
            if a_cand == b_cand:
                continue  # only existing-vs-candidate pairs are conflicts
            hits.append((a, b) if b_cand else (b, a))
    # keep the historical hit order: candidate order, then existing order
    hits.sort(key=lambda h: (cand_pos[id(h[1])], ex_pos[id(h[0])]))
    return hits


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
    timeline = scan_oven_timeline([o for o in existing if o.oven_id == oven_id])
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
