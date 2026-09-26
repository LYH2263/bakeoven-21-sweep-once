from app.services.oven_engine import (
    Interval,
    Occupancy,
    OvenTimeline,
    RecipeDurations,
    build_occupancies,
    find_conflicts,
    next_free_window,
    scan_oven,
)


def occ(batch_id: int, start: int, end: int, phase: str = "bake", oven_id: int = 1) -> Occupancy:
    return Occupancy(oven_id, Interval(start, end), phase, batch_id)


def test_half_open_no_touch_conflict():
    a = Occupancy(1, Interval(0, 30), "bake", 1)
    b = Occupancy(1, Interval(30, 60), "bake", 2)
    assert find_conflicts([a], [b]) == []


def test_overlap_detected():
    recipe = RecipeDurations(20, 30)
    cand = build_occupancies(1, 9, 10, recipe)
    existing = [Occupancy(1, Interval(25, 40), "bake", 1)]
    assert find_conflicts(existing, cand)


def test_next_free_window_after_busy():
    existing = [
        Occupancy(1, Interval(0, 40), "ferment", 1),
        Occupancy(1, Interval(40, 70), "bake", 1),
    ]
    w = next_free_window(existing, 1, duration=30, search_from=0)
    assert w == Interval(70, 100)


def test_next_free_in_gap():
    existing = [
        Occupancy(1, Interval(0, 20), "bake", 1),
        Occupancy(1, Interval(80, 100), "bake", 2),
    ]
    w = next_free_window(existing, 1, duration=30, search_from=0)
    assert w == Interval(20, 50)


# ---------------------------------------------------------------------------
# 单次扫描：相接 / 交叉 / 内含 三组数据
# ---------------------------------------------------------------------------


def test_sweep_touching_endpoints_neither_merge_nor_overlap():
    """相接：[100,160) 与 [160,200) 不产生重叠对，也不并成一个忙碌段。"""
    timeline = scan_oven([occ(1, 100, 160), occ(2, 160, 200)], 1)
    assert len(timeline.overlaps) == 0
    assert timeline.busy == (Interval(100, 160), Interval(160, 200))
    # 最早空档从 0 点起，长度 50
    assert next_free_window(
        [occ(1, 100, 160), occ(2, 160, 200)], 1, duration=50, search_from=0, search_to=480
    ) == Interval(0, 50)


def test_sweep_crossing_segments_report_pair_and_merge():
    """交叉：[100,160) 烘烤 与 [140,200) 发酵，一对（烘烤对发酵），忙碌合并为 [100,200)。"""
    timeline = scan_oven(
        [occ(1, 100, 160, "bake"), occ(2, 140, 200, "ferment")], 1
    )
    assert len(timeline.overlaps) == 1
    pair = timeline.overlaps[0]
    assert pair.phases == ("bake", "ferment")
    assert (pair.earlier.batch_id, pair.later.batch_id) == (1, 2)
    assert timeline.busy == (Interval(100, 200),)
    # 最早空档从 0 点起；中间没有空档，50 长只能落在 [0,50)
    assert next_free_window(
        [occ(1, 100, 160, "bake"), occ(2, 140, 200, "ferment")],
        1,
        duration=50,
        search_from=0,
        search_to=480,
    ) == Interval(0, 50)
    # 120 长在忙碌段之前放不下，只能落到合并段之后
    assert next_free_window(
        [occ(1, 100, 160, "bake"), occ(2, 140, 200, "ferment")],
        1,
        duration=120,
        search_from=0,
        search_to=480,
    ) == Interval(200, 320)


def test_sweep_contained_segment_keeps_outer_bounds_and_pair():
    """内含：[130,200) 完全落在 [100,240) 内，忙碌用外层 [100,240)，重叠对仍要报。"""
    timeline = scan_oven(
        [occ(1, 100, 240, "ferment"), occ(2, 130, 200, "bake")], 1
    )
    assert len(timeline.overlaps) == 1
    pair = timeline.overlaps[0]
    assert pair.phases == ("ferment", "bake")
    assert (pair.earlier.batch_id, pair.later.batch_id) == (1, 2)
    # 被包住的内段不得把忙碌段切碎
    assert timeline.busy == (Interval(100, 240),)
    assert next_free_window(
        [occ(1, 100, 240, "ferment"), occ(2, 130, 200, "bake")],
        1,
        duration=50,
        search_from=0,
        search_to=480,
    ) == Interval(0, 50)
    assert next_free_window(
        [occ(1, 100, 240, "ferment"), occ(2, 130, 200, "bake")],
        1,
        duration=140,
        search_from=0,
        search_to=480,
    ) == Interval(240, 380)


# ---------------------------------------------------------------------------
# 重叠对按阶段保留：发酵对发酵、烘烤对烘烤、发酵对烘烤（交叉用例已覆盖烘烤对发酵）
# ---------------------------------------------------------------------------


def test_overlap_pair_ferment_on_ferment():
    timeline = scan_oven(
        [occ(1, 100, 160, "ferment"), occ(2, 120, 180, "ferment")], 1
    )
    assert len(timeline.overlaps) == 1
    assert timeline.overlaps[0].phases == ("ferment", "ferment")


def test_overlap_pair_bake_on_bake():
    timeline = scan_oven(
        [occ(1, 100, 160, "bake"), occ(2, 120, 180, "bake")], 1
    )
    assert len(timeline.overlaps) == 1
    assert timeline.overlaps[0].phases == ("bake", "bake")


def test_sweep_reports_each_pair_among_three():
    timeline = scan_oven(
        [occ(1, 0, 100, "bake"), occ(2, 20, 120, "ferment"), occ(3, 40, 90, "bake")],
        1,
    )
    assert len(timeline.overlaps) == 3
    assert timeline.busy == (Interval(0, 120),)


def test_find_conflicts_only_crosses_existing_and_candidate():
    """同组内的重叠不报；候选与每条既有的重叠都要报。"""
    existing = [occ(1, 0, 100), occ(2, 20, 120)]  # 彼此重叠但都已在排
    candidates = [occ(9, 50, 80)]
    hits = find_conflicts(existing, candidates)
    assert hits == [(occ(1, 0, 100), candidates[0]), (occ(2, 20, 120), candidates[0])]


def test_sweep_ignores_other_ovens():
    timeline = scan_oven(
        [occ(1, 0, 100, oven_id=1), occ(2, 50, 150, oven_id=2)], 1
    )
    assert isinstance(timeline, OvenTimeline)
    assert timeline.overlaps == ()
    assert timeline.busy == (Interval(0, 100),)


# ---------------------------------------------------------------------------
# 种子 BO-0900 / BO-1030 / BO-1000：甘特块坐标与可开工窗口与改前一致
# （与 app/services/seed.py 的种子数据一一对应）
# ---------------------------------------------------------------------------

RECIPES = {
    "乡村欧包": RecipeDurations(40, 35),   # 总 75
    "黄油可颂": RecipeDurations(25, 20),   # 总 45
    "布朗尼": RecipeDurations(0, 30),      # 总 30，发酵为零长度段
}

# (批次号, 产品, 炉号, 起点)
SEED_BATCHES = [
    ("BO-0900", "乡村欧包", 1, 9 * 60),
    ("BO-1030", "黄油可颂", 1, 10 * 60 + 30),
    ("BO-1000", "布朗尼", 2, 10 * 60),
]


def _seed_occupancies() -> list[Occupancy]:
    out: list[Occupancy] = []
    for idx, (_, name, oven_id, start) in enumerate(SEED_BATCHES, start=1):
        out.extend(build_occupancies(oven_id, idx, start, RECIPES[name]))
    return out


def test_seed_gantt_blocks_unchanged():
    """与 /gantt 端点相同的构造顺序：按起点排序，每批先发酵后烘烤。"""
    batches = sorted(SEED_BATCHES, key=lambda b: b[3])
    blocks = []
    for code, name, oven_id, start in batches:
        for o in build_occupancies(oven_id, 0, start, RECIPES[name]):
            blocks.append((code, oven_id, o.phase, o.interval.start, o.interval.end))
    assert blocks == [
        ("BO-0900", 1, "ferment", 540, 580),
        ("BO-0900", 1, "bake", 580, 615),
        ("BO-1000", 2, "ferment", 600, 600),  # 零长度发酵段仍在甘特上
        ("BO-1000", 2, "bake", 600, 630),
        ("BO-1030", 1, "ferment", 630, 655),
        ("BO-1030", 1, "bake", 655, 675),
    ]


def test_seed_no_overlap_pairs():
    timelines = {1: scan_oven(_seed_occupancies(), 1), 2: scan_oven(_seed_occupancies(), 2)}
    assert timelines[1].overlaps == ()
    assert timelines[2].overlaps == ()
    # 炉 1：每批发酵段与烘烤段端点相接，相接不得并入，故为 4 个忙碌段；
    # BO-0900 烘烤 615 收尾与 BO-1030 发酵 630 起也是分离两段
    assert timelines[1].busy == (
        Interval(540, 580),
        Interval(580, 615),
        Interval(630, 655),
        Interval(655, 675),
    )
    # 炉 2：零长度发酵段 [600,600) 与烘烤同起点，不产生独立忙碌段，
    # 合并后即 [600,630)；窗口结果不受影响
    assert timelines[2].busy == (Interval(600, 630),)


def test_seed_windows_unchanged():
    """与 /windows 端点相同的参数：8:00 起、22:00 止，每炉取最早空档。"""
    existing = _seed_occupancies()
    cases = [
        # (产品, 总时长, {炉号: (最早开工, 完工)})；炉 2/3 在 8:00 后尚无占用，
        # 能在忙碌前放下的就从 480 起——与改前完全一致
        ("乡村欧包", 75, {1: (675, 750), 2: (480, 555), 3: (480, 555)}),
        ("黄油可颂", 45, {1: (480, 525), 2: (480, 525), 3: (480, 525)}),
        ("布朗尼", 30, {1: (480, 510), 2: (480, 510), 3: (480, 510)}),
    ]
    for name, duration, expected in cases:
        assert RECIPES[name].total == duration
        for oven_id, (start, end) in expected.items():
            w = next_free_window(
                existing, oven_id, duration, search_from=8 * 60, search_to=22 * 60
            )
            assert w == Interval(start, end), f"{name} 炉{oven_id} 窗口变化: {w}"
