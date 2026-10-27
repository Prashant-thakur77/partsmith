"""Registry clean-up: product titles and slugs for seeded parts, and the bench-only role of reference objects.

A seeded part is named after what it is plus its main size, taken from its own knob values ("Cupboard door latch,
52 mm" → `cupboard-door-latch-52mm`), never after the sample folder (`demo-…`). Reference objects (ID-1 card, LEGO
brick, …) exist to measure the measurer: they carry the tag `role:reference`, are hidden from `/parts` by default and stay
reachable with `?role=reference`. No schema change: the role lives in `tags`.
"""

from __future__ import annotations

import re
from functools import cache

from partsmith_schemas import PartRecord

from services.agent.templates import Template, list_templates
from services.geom_worker.program import module_literals
from services.registry.publish import program_identity, publish_part, values_of
from services.registry.store import ROLE_REFERENCE_TAG, Registry, get_registry

PRODUCT_NAMES = {
    "battery_cover": "Battery cover",
    "cable_clip": "Cable clip",
    "caster_wheel": "Caster wheel",
    "clip": "Shelf panel clip",
    "cupboard_latch": "Cupboard door latch",
    "hinge_leaf": "Hinge leaf",
    "hook": "Wall hook",
    "knob": "Control knob",
    "l_bracket": "L-bracket",
    "spacer": "Spacer",
}
_NOISE = re.compile(r"\s*\((?:[^)]*synthetic[^)]*|test sample|[^)]*sample[^)]*)\)", re.I)


def is_reference(part: PartRecord) -> bool:
    return ROLE_REFERENCE_TAG in part.tags


@cache
def _templates_by_identity() -> dict[str, Template]:
    return {program_identity(t.code): t for t in list_templates()}


def template_of(part: PartRecord) -> Template | None:
    """The family template this part's program comes from (same program at any defaults, or the same TITLE literal
    when the builder edited it), or None for free-code parts."""
    t = _templates_by_identity().get(program_identity(part.code))
    if t is not None:
        return t
    try:
        title = module_literals(part.code, ("TITLE",)).get("TITLE")
    except (SyntaxError, ValueError):
        return None
    return next((x for x in list_templates() if x.title == title), None) if title else None


def _slugify(text: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text.lower())).strip("-")[:80] or "part"


def main_size_mm(part: PartRecord) -> float | None:
    """The size a person would quote: the template's length knob, else the longest footprint side."""
    t = template_of(part)
    values = values_of(part)
    if t is not None and t.measure_map.get("length") in values:
        return float(values[t.measure_map["length"]])
    if part.facts is not None:
        return float(max(part.facts.bbox_mm[0], part.facts.bbox_mm[1]))
    return None


def product_name(part: PartRecord, *, reference: bool = False, known_title: str | None = None) -> tuple[str, str]:
    """(title, slug) for a part: "Cupboard door latch, 52 mm" / `cupboard-door-latch-52mm`. A reference object is named
    after what it is (`known_title`, from the sample's own metadata), never after a model's guess of the part."""
    t = template_of(part)
    base = PRODUCT_NAMES.get(t.name, t.title) if t is not None else _NOISE.sub("", part.title).strip() or "Part"
    if reference:
        base = _NOISE.sub("", known_title or part.title).strip() or base
        if known_title:
            base = re.sub(r"\s*\([^)]*\)", "", base).strip() or base  # "AA cell (lying on its side)" → "AA cell"
        base = re.sub(r"^(reference object[:\s—-]*)", "", base, flags=re.I)
        return f"Reference object — {base}", _slugify(f"reference {base}")
    size = main_size_mm(part)
    if size is None:
        return base, _slugify(base)
    shown = f"{size:.1f}".rstrip("0").rstrip(".")
    return f"{base}, {shown} mm", _slugify(f"{base} {round(size)}mm")


def rename(
    part: PartRecord, *, reference: bool = False, known_title: str | None = None, reg: Registry | None = None
) -> PartRecord:
    """Give a published part its product title/slug (and the reference role when asked). Publishing goes through
    `publish_part`, so an identical part already listed under the product slug is reused, never duplicated."""
    reg = reg or get_registry()
    title, slug = product_name(part, reference=reference, known_title=known_title)
    tags = [t for t in part.tags if t != ROLE_REFERENCE_TAG] + ([ROLE_REFERENCE_TAG] if reference else [])
    if part.slug == slug and part.title == title and tags == part.tags:
        return part
    renamed = part.model_copy(update={"slug": slug, "title": title, "tags": tags})
    if part.slug != slug:
        reg.delete_part(part.slug)
    return publish_part(renamed, reg=reg).part


def cleanup(reg: Registry | None = None) -> dict[str, str]:
    """Rename every `demo-…` part to its product name; `demo-ref-…` parts become reference objects. Returns
    {old slug: new slug}. Idempotent."""
    reg = reg or get_registry()
    moved: dict[str, str] = {}
    for slug in reg.slugs():
        if not slug.startswith("demo-"):
            continue
        part = reg.get_part(slug)
        if part is None:
            continue
        reference = slug.startswith("demo-ref-") or is_reference(part)
        moved[slug] = rename(part, reference=reference, reg=reg).slug
    return moved
