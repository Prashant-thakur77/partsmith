from __future__ import annotations

from partsmith_schemas import Verification

from services.agent.templates import get_template
from services.registry import parts as P
from services.registry import steer
from services.registry.publish import dedupe_published, identity, program_identity, publish_part
from services.registry.store import get_registry
from services.registry.tests.fixtures import make_part


def test_identity_ignores_defaults_but_not_values() -> None:
    clip = get_template("cable_clip").code
    a = make_part("cable_clip", "a")
    b = make_part("cable_clip", "b", params={"channel_count": 3})
    assert program_identity(a.code) == program_identity(b.code) == program_identity(clip)
    assert program_identity(make_part("clip").code) != program_identity(clip)
    assert identity(a) != identity(b)
    assert identity(a) == identity(make_part("cable_clip", "zzz"))


def test_identical_publish_returns_the_existing_part() -> None:
    first = publish_part(make_part("cable_clip", "cable-clip-40"), render=False)
    assert first.action == "created"
    again = publish_part(make_part("cable_clip", "desk-kit-cable-clip-1"), render=False)
    assert again.action == "unchanged" and again.part.slug == "cable-clip-40"
    assert again.duplicate_of == "cable-clip-40" and again.requested_slug == "desk-kit-cable-clip-1"
    assert get_registry().slugs() == ["cable-clip-40"]
    same_slug = publish_part(make_part("cable_clip", "cable-clip-40"), render=False)
    assert same_slug.action == "unchanged" and same_slug.part.version == 1


def test_changed_facts_update_and_bump_version() -> None:
    publish_part(make_part("cable_clip", "cable-clip-40", max_error_mm=0.3), render=False)
    better = make_part("cable_clip", "other-name", max_error_mm=0.1)
    out = publish_part(better, render=False)
    assert out.action == "updated" and out.part.slug == "cable-clip-40" and out.part.version == 2
    stored = get_registry().get_part("cable-clip-40")
    assert stored is not None and isinstance(stored.verification, Verification)
    assert stored.verification.max_error_mm == 0.1 and get_registry().slugs() == ["cable-clip-40"]


def test_slug_collision_gets_a_descriptive_suffix_and_lineage() -> None:
    publish_part(make_part("cable_clip", "cable-clip"), render=False)
    out = publish_part(make_part("cable_clip", "cable-clip", params={"length": 50.0, "channel_count": 3}), render=False)
    assert out.action == "renamed" and out.part.slug == "cable-clip-50mm-3ch"
    assert out.part.provenance.forked_from == "cable-clip"
    parent = get_registry().get_part("cable-clip")
    assert parent is not None
    assert P.lineage(parent)[0] == {"slug": "cable-clip-50mm-3ch", "version": 1, "relation": "variant_of",
                                    "title": parent.title}  # fmt: skip
    hole = publish_part(make_part("cable_clip", "cable-clip", params={"hole_d": 4.5}), render=False)
    assert hole.part.slug == "cable-clip-hole4p5mm"
    other = publish_part(make_part("clip", "cable-clip"), render=False)  # a different program under the same slug
    assert other.action == "renamed" and other.part.slug == "cable-clip-36mm-width16mm"
    assert other.part.provenance.forked_from is None


def test_dedupe_published_folds_a_copy_into_the_older_part() -> None:
    reg = get_registry()
    publish_part(make_part("spacer", "m3-spacer"), render=False)
    copy = make_part("spacer", "spacer-from-job-abc123")
    copy.created_at += 10
    reg.upsert_part(copy)
    out = dedupe_published("spacer-from-job-abc123", render=False)
    assert out.part.slug == "m3-spacer" and out.duplicate_of == "m3-spacer"
    assert reg.slugs() == ["m3-spacer"]
    fresh = make_part("knob", "knob-1")
    reg.upsert_part(fresh)
    assert dedupe_published("knob-1", render=False).action == "created"


def test_steer_approvals_of_the_same_kit_publish_one_card() -> None:
    first = steer.start("desk cable kit", 1, sync=True)
    second = steer.start("desk cable kit", 1, sync=True)
    s1, s2 = steer.get(first)["queue"][0]["slug"], steer.get(second)["queue"][0]["slug"]
    assert s1 == s2  # plans no longer dodge registry slugs; publishing decides
    a = steer.review(first, s1, "approve")
    b = steer.review(second, s2, "approve")
    assert a["queue"][0]["publish_action"] == "created"
    assert b["queue"][0]["publish_action"] == "unchanged" and b["queue"][0]["published_slug"] == s1
    assert get_registry().slugs() == [s1]
