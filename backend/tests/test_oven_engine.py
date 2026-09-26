from app.services.oven_engine import (
    Interval,
    Occupancy,
    RecipeDurations,
    build_occupancies,
    find_conflicts,
    next_free_window,
    scan_oven_timeline,
)


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


def test_scan_touching_not_merged_not_overlap():
    # 相接: end == start 既不并入忙碌段, 也不记重叠
    occ = [
        Occupancy(1, Interval(0, 30), "bake", 1),
        Occupancy(1, Interval(30, 60), "bake", 2),
        Occupancy(1, Interval(60, 90), "ferment", 3),
    ]
    timeline = scan_oven_timeline(occ)
    assert timeline.overlaps == []
    assert timeline.busy == [Interval(0, 30), Interval(30, 60), Interval(60, 90)]
    assert next_free_window(occ, 1, duration=10, search_from=0) == Interval(90, 100)


def test_scan_crossing_merges_and_reports_pair():
    # 交叉: 合并成一段忙碌, 报一对发酵对烘烤
    occ = [
        Occupancy(1, Interval(0, 50), "ferment", 1),
        Occupancy(1, Interval(30, 80), "bake", 2),
    ]
    timeline = scan_oven_timeline(occ)
    assert len(timeline.overlaps) == 1
    a, b = timeline.overlaps[0]
    assert (a.phase, b.phase) == ("ferment", "bake")
    assert timeline.busy == [Interval(0, 80)]
    assert next_free_window(occ, 1, duration=10, search_from=0) == Interval(80, 90)


def test_scan_contained_keeps_pair_and_outer_busy():
    # 内含: 忙碌取外层起止, 被包住的一对仍要报出
    occ = [
        Occupancy(1, Interval(0, 100), "bake", 1),
        Occupancy(1, Interval(20, 40), "ferment", 2),
    ]
    timeline = scan_oven_timeline(occ)
    assert len(timeline.overlaps) == 1
    a, b = timeline.overlaps[0]
    assert (a.batch_id, b.batch_id) == (1, 2)
    assert timeline.busy == [Interval(0, 100)]
    assert next_free_window(occ, 1, duration=30, search_from=0) == Interval(100, 130)


def test_seed_batches_gantt_and_windows_unchanged():
    # 种子: BO-0900 乡村欧包(40+35)@540 炉1, BO-1030 黄油可颂(25+20)@630 炉1,
    #       BO-1000 布朗尼(0+30)@600 炉2
    bo0900 = build_occupancies(1, 1, 9 * 60, RecipeDurations(40, 35))
    bo1030 = build_occupancies(1, 2, 10 * 60 + 30, RecipeDurations(25, 20))
    bo1000 = build_occupancies(2, 3, 10 * 60, RecipeDurations(0, 30))
    existing = bo0900 + bo1030 + bo1000

    # 甘特占用段与改前一致
    assert [o.interval for o in bo0900] == [Interval(540, 580), Interval(580, 615)]
    assert [o.interval for o in bo1030] == [Interval(630, 655), Interval(655, 675)]
    assert [o.interval for o in bo1000] == [Interval(600, 600), Interval(600, 630)]

    # 种子时间线: 批内/批间均端点相接或相离, 无重叠对, 相接段不合并
    t1 = scan_oven_timeline(bo0900 + bo1030)
    assert t1.overlaps == []
    assert t1.busy == [
        Interval(540, 580),
        Interval(580, 615),
        Interval(630, 655),
        Interval(655, 675),
    ]
    assert scan_oven_timeline(bo1000).overlaps == []

    # 可开工窗口(08:00-22:00 搜索域)与改前一致
    assert next_free_window(existing, 1, 75, search_from=480, search_to=1320) == Interval(675, 750)
    assert next_free_window(existing, 1, 45, search_from=480, search_to=1320) == Interval(480, 525)
    assert next_free_window(existing, 2, 75, search_from=480, search_to=1320) == Interval(480, 555)
    assert next_free_window(existing, 2, 30, search_from=480, search_to=1320) == Interval(480, 510)
