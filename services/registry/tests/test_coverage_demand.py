"""Search coverage (share of the query's words and numbers a part matches), the search log and missed-search
grouping, and download file names. TEST DATA parts built from family templates."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime, timedelta

from services.registry import demand, filenames
from services.registry.store import (
    coverage,
    get_registry,
    match_hint,
    match_label,
    number_hit,
    query_terms,
    screw_fits,
)
from services.registry.tests.fixtures import add_part, make_part


def test_query_terms_drop_filler_and_keep_numbers() -> None:
    assert query_terms("replacement cable clip for 8 mm cable") == (["cable", "clip", "cable"], [8.0])
    assert query_terms("") == ([], [])
    assert query_terms("mm") == ([], [])


def test_number_tolerance_is_ten_percent_or_half_a_millimetre() -> None:
    assert number_hit(3.0, [3.4])  # within 0.5 mm
    assert not number_hit(3.0, [3.6])
    assert number_hit(50.0, [54.9])  # within 10 %
    assert not number_hit(50.0, [55.6])


def test_coverage_counts_words_and_numbers() -> None:
    part = make_part("cable_clip", "desk-cable-clip")
    cable_d = part.defaults["cable_d"]
    assert coverage(part, *query_terms("cable clip")) == 1.0
    assert coverage(part, *query_terms("cable clips")) == 1.0  # plural ignored
    assert coverage(part, *query_terms(f"cable clip {cable_d:g} mm")) == 1.0
    assert coverage(part, *query_terms("cable clip 400 mm")) == round(2 / 3, 3)
    assert coverage(part, *query_terms("zeppelin")) == 0.0
    assert coverage(part, [], []) == 0.0


def test_match_labels_and_hints() -> None:
    assert match_label(None) == "all" and match_hint("all") is None
    assert match_label(0.75) == "good" and match_hint("good") is None
    assert match_label(0.5) == "partial" and "partial" in (match_hint("partial") or "")
    assert match_label(0.49) == "none"
    hint = match_hint("none") or ""
    assert "/describe" in hint and "/fix" in hint


def test_search_scored_returns_page_coverage_and_best() -> None:
    add_part("cable_clip", "desk-cable-clip")
    add_part("knob", "drawer-knob")
    reg = get_registry()
    items, total, covs, best = reg.search_scored("cable clip", role="part")
    assert items[0].slug == "desk-cable-clip" and total >= 1 and covs[0] == 1.0 and best == 1.0
    items, total, covs, best = reg.search_scored("zeppelin", role="part")
    assert items == [] and total == 0 and covs == [] and best == 0.0
    items, total, covs, best = reg.search_scored("", role="part")
    assert total == 2 and covs == [] and best is None
    assert reg.search("cable clip", role="part")[1] == reg.search_scored("cable clip", role="part")[1]


def test_log_search_writes_jsonl_without_client_data(isolated: object) -> None:
    assert demand.log_search("Cable  clip 8mm", 3, 0.6667)
    assert not demand.log_search("ab", 0, 0.0)  # too short to mean anything
    rows = [json.loads(x) for x in demand.log_path().read_text().splitlines()]
    assert len(rows) == 1
    assert set(rows[0]) == {"q", "total", "best_coverage", "at"}
    assert rows[0]["q"] == "Cable clip 8mm" and rows[0]["total"] == 3 and rows[0]["best_coverage"] == 0.667
    assert datetime.fromisoformat(rows[0]["at"]).tzinfo is not None


def test_log_search_is_thread_safe() -> None:
    threads = [threading.Thread(target=demand.log_search, args=(f"query number {i}", i, 0.1)) for i in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    lines = demand.log_path().read_text().splitlines()
    assert len(lines) == 40 and all(json.loads(x)["q"].startswith("query number") for x in lines)


def test_missed_searches_group_normalised_queries_below_half() -> None:
    t0 = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
    demand.log_search("Zeppelin gondola", 0, 0.0, now=t0)
    demand.log_search("zeppelin  GONDOLA!", 0, 0.0, now=t0 + timedelta(minutes=5))
    demand.log_search("cable clip", 4, 1.0, now=t0 + timedelta(minutes=6))  # found: not missed
    demand.log_search("dishwasher wheel 22 mm", 1, 0.333, now=t0 + timedelta(minutes=7))
    demand.log_search("dishwasher wheel 22 mm", 1, 0.667, now=t0 + timedelta(minutes=9))  # later found partly
    demand.log_search("fridge shelf", 0, 0.0, now=t0 + timedelta(minutes=10))
    missed = demand.missed_searches()
    assert [m["count"] for m in missed] == [2, 1]
    assert missed[0]["q"] == "zeppelin GONDOLA!"  # the latest wording
    assert missed[0]["best_coverage"] == 0.0 and missed[0]["last_at"] == (t0 + timedelta(minutes=5)).isoformat()
    assert missed[1]["q"] == "fridge shelf"
    assert all(set(m) == {"q", "count", "best_coverage", "last_at"} for m in missed)


def test_missed_searches_skip_half_typed_queries() -> None:
    t0 = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
    for i, q in enumerate(["zep", "zeppel", "zeppelin"]):
        demand.log_search(q, 0, 0.0, now=t0 + timedelta(seconds=2 * i))
    demand.log_search("zeppelin", 0, 0.0, now=t0 + timedelta(minutes=10))
    missed = demand.missed_searches()
    assert [(m["q"], m["count"]) for m in missed] == [("zeppelin", 2)]


def test_missed_searches_tolerate_a_damaged_log() -> None:
    demand.log_path().write_text('not json\n{"q": 5}\n{"q": "boat cleat", "total": 0, "best_coverage": 0.0, '
                                 '"at": "2026-10-30T12:00:00+00:00"}\n')  # fmt: skip
    assert [m["q"] for m in demand.missed_searches()] == ["boat cleat"]
    assert demand.missed_searches(limit=0) == []


def test_download_names() -> None:
    d = filenames.download_name
    assert d("cable-clip", ".stl") == "partsmith-cable-clip.stl"
    assert d("cable-clip", "stl", {"hole_d": 3.4, "cable_d": 6.0}, {"hole_d": 3.0, "cable_d": 6.0}) == (
        "partsmith-cable-clip-hole3.4.stl"
    )
    assert d("Weird Slug/../x", ".3mf", {"channel_count": 3}, {"channel_count": 2}) == (
        "partsmith-weird-slug-x-channelcount3.3mf"
    )
    many = {f"knob_{i}_mm": i + 0.25 for i in range(30)}
    long = d("a" * 40, ".step", many, {})
    assert len(long) <= filenames.MAX_LEN and long.endswith(".step") and "-plus" in long
    assert all(c.isascii() and (c.isalnum() or c in ".-") for c in long)
    assert filenames.num_text(8.0) == "8" and filenames.num_text(0.25) == "0.25" and filenames.num_text(-5) == "-5"
    assert filenames.knob_short("wall_t") == "wall" and filenames.knob_short("hole_spacing") == "holespacing"


def _plain_spacer(slug: str = "spacer-8mm", bore_d: float = 3.9) -> object:
    """Like the seeded spacer: title and tags say only "spacer" (no "standoff", no "M3")."""
    part = make_part("spacer", slug, params={"bore_d": bore_d})
    part = part.model_copy(
        update={"title": "Spacer, 8 mm", "tags": ["spacer", "synthetic"], "summary": "Annular spacer."}
    )
    get_registry().upsert_part(part)
    return part


def test_screw_size_is_one_word_matched_against_holes() -> None:
    assert query_terms("M3 standoff") == (["m3", "standoff"], [])
    assert query_terms("m2.5 spacer 10 mm") == (["m2.5", "spacer"], [10.0])
    assert query_terms("M3x10 bolt") == (["m3", "bolt"], [10.0])
    assert query_terms("m7 thing") == (["thing"], [7.0])  # not a size in the clearance table: a plain number
    assert query_terms("8mm") == ([], [8.0])
    assert screw_fits("3", [3.4]) and screw_fits("3", [3.9]) and screw_fits("3", [2.5])
    assert not screw_fits("3", [4.5]) and not screw_fits("3", [2.0])
    assert screw_fits("4", [4.5]) and screw_fits("4", [3.4]) and not screw_fits("4", [3.0])  # 3.4: a pilot hole


def test_standoff_and_screw_size_find_the_spacer() -> None:
    _plain_spacer()
    add_part("knob", "drawer-knob")
    reg = get_registry()
    for q in ("standoff", "M3 standoff", "M3 spacer", "standoffs"):
        items, _, covs, best = reg.search_scored(q, role="part")
        assert items and items[0].slug == "spacer-8mm" and covs[0] == 1.0 and best == 1.0, q
    items, _, covs, _ = reg.search_scored("M5 spacer", role="part")
    assert items[0].slug == "spacer-8mm" and covs[0] == 0.5  # a 3.9 mm bore does not take an M5 screw


def test_synonyms_and_family_names_match() -> None:
    add_part("caster_wheel", "chair-caster")
    add_part("battery_cover", "remote-cover")
    reg = get_registry()
    assert reg.search_scored("castor wheel", role="part")[0][0].slug == "chair-caster"
    items, _, covs, _ = reg.search_scored("lid", role="part")
    assert items[0].slug == "remote-cover" and covs[0] == 1.0
    assert reg.search_scored("zeppelin", role="part")[1] == 0
