"""Muse Wonder finds a published spec: web search with citations, accepted only by code rules.

Live: Responses API on `muse-wonder-1.0` with the built-in `web_search` tool (`search_context_size="high"`), raw search
results requested with `include=["web_search_call.results"]`. The model answers with JSON values that name a source URL;
code then decides:
- a search must actually have run (a `web_search_call` item in the output) — otherwise nothing is accepted;
- the URL must be one the search returned (a `url_citation` annotation or a search result);
- only requested names, positive finite values, units converted to mm (mm, cm, m, in).
Values enter a PartSpec as `Source.cited` and never override a measured value (the agent loop enforces that).

Mock: a clearly labelled fixture (`MOCK — no web search ran`, `https://example.invalid/...` URLs) built only from
values the caller supplies (`fixture=` or a registered `spec_lookup` mock); without them it returns no values.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from partsmith_schemas.common import Citation

from . import meta, mocks, pricing, replay, retry, sam_parse
from .base import ProviderError
from .clients import field as get
from .config import Mode, settings
from .core import Outcome, dispatch, retry_opts
from .jsonschema_lite import extract_json, validate
from .routing import Route

MOCK_NOTE = "MOCK — no web search ran"
UNIT_MM = {
    "mm": 1.0,
    "millimeter": 1.0,
    "millimetre": 1.0,
    "cm": 10.0,
    "m": 1000.0,
    "in": 25.4,
    "inch": 25.4,
    '"': 25.4,
}

ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "values": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "value": {"type": "number"},
                    "unit": {"type": "string"},
                    "url": {"type": "string"},
                    "title": {"type": "string"},
                    "quote": {"type": "string"},
                },
                "required": ["name", "value", "unit", "url", "quote"],
            },
        },
        "notes": {"type": "string"},
    },
    "required": ["values"],
}

INSTRUCTIONS = """You look up published dimensions of replacement parts (manufacturer pages, manuals, datasheets,
retailer listings). Search the web. Report only values you found on a page you can cite; never estimate.
Answer with one JSON object: {"values": [{"name", "value", "unit" (mm|cm|in), "url", "title", "quote"}], "notes"}.
"quote" is the exact sentence or table cell from the page. Leave out anything you could not find."""


@dataclass
class SpecLookup:
    values: list[dict[str, Any]]  # {"name": str, "value_mm": float, "citation": Citation}
    searched: bool
    notes: list[str] = field(default_factory=list)
    mode: Mode = "mock"
    provider: str = ""
    model: str = ""
    usd: float = 0.0
    queries: int = 0
    sources: list[str] = field(default_factory=list)  # every URL the search returned

    def to_dict(self) -> dict[str, Any]:
        return {
            "values": [{**v, "citation": v["citation"].model_dump()} for v in self.values],
            "searched": self.searched,
            "notes": self.notes,
            "mode": self.mode,
            "provider": self.provider,
            "model": self.model,
            "usd": self.usd,
            "queries": self.queries,
            "sources": self.sources,
        }


def _norm_url(url: str) -> str:
    return url.strip().rstrip("/").split("#", 1)[0].lower()


def _norm_name(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def _to_mm(value: float, unit: str) -> float | None:
    scale = UNIT_MM.get(unit.strip().lower().rstrip("s").rstrip("."))
    return value * scale if scale is not None else None


def search_evidence(response: Any) -> tuple[bool, int, dict[str, str], list[str]]:
    """(searched?, number of search calls, {cited url: cited text span}, all result URLs) from a Responses output."""
    searched, queries = False, 0
    cited: dict[str, str] = {}
    sources: list[str] = []
    for item in get(response, "output", None) or []:
        kind = get(item, "type")
        if kind == "web_search_call":
            queries += 1
            searched = searched or get(item, "status", "completed") != "failed"
            action = get(item, "action") or {}
            for res in (get(item, "results", None) or []) + (get(action, "sources", None) or []):
                url = get(res, "url")
                if url:
                    sources.append(str(url))
        elif kind == "message":
            for part in get(item, "content", None) or []:
                text = str(get(part, "text", "") or "")
                for ann in get(part, "annotations", None) or []:
                    if get(ann, "type") == "url_citation" and get(ann, "url"):
                        start, end = get(ann, "start_index"), get(ann, "end_index")
                        span = text[start:end] if isinstance(start, int) and isinstance(end, int) else ""
                        cited[str(get(ann, "url"))] = span
                        sources.append(str(get(ann, "url")))
    return searched, queries, cited, list(dict.fromkeys(sources))


def accept_values(
    answer: Any, want: Sequence[str], searched: bool, allowed_urls: Sequence[str], cited: Mapping[str, str]
) -> tuple[list[dict[str, Any]], list[str]]:
    """Code decides which proposed values stand. Returns (accepted values, notes on everything rejected)."""
    notes: list[str] = []
    if validate(answer, ANSWER_SCHEMA):
        return [], ["model answer did not match the expected JSON shape"]
    wanted = {_norm_name(w): w for w in want}
    allowed = {_norm_url(u) for u in allowed_urls}
    accepted: list[dict[str, Any]] = []
    for v in answer.get("values", []):
        name = wanted.get(_norm_name(str(v["name"])))
        if name is None:
            notes.append(f"ignored unrequested value {v['name']!r}")
            continue
        if not searched:
            notes.append(f"{name}: rejected — no web search ran, so the value has no source")
            continue
        url = str(v["url"])
        if _norm_url(url) not in allowed:
            notes.append(f"{name}: rejected — {url} was not among the pages the search returned")
            continue
        value_mm = _to_mm(float(v["value"]), str(v["unit"]))
        if value_mm is None or not math.isfinite(value_mm) or value_mm <= 0:
            notes.append(f"{name}: rejected — unusable value {v['value']} {v['unit']}")
            continue
        if any(a["name"] == name for a in accepted):
            notes.append(f"{name}: duplicate value ignored")
            continue
        quote = str(v.get("quote") or "").strip()[:300] or cited.get(url, "")[:300]
        citation = Citation(url=url, title=str(v.get("title") or "")[:200], quote=quote)
        accepted.append({"name": name, "value_mm": round(value_mm, 4), "citation": citation})
    for name in want:
        if not any(a["name"] == name for a in accepted):
            notes.append(f"{name}: not found")
    return accepted, notes


def _live(route: Route, query: str, want: Sequence[str]) -> Outcome[dict[str, Any]]:
    timeout = max(settings().timeout_s, 300.0)
    client = meta.client_for(route, timeout)
    user = f"Part: {query}\nFind these dimensions: {', '.join(want)}"
    kwargs = {
        "model": route.model,
        "input": [
            {"type": "message", "role": "developer", "content": INSTRUCTIONS},
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": user}]},
        ],
        "tools": [{"type": "web_search", "search_context_size": "high"}],
        "tool_choice": "auto",
        "include": ["web_search_call.results"],
        "reasoning": {"effort": "medium", "summary": "auto"},
        "store": False,
    }

    def call() -> tuple[str, Any]:
        events = client.responses.create(**kwargs, stream=True)
        try:
            return sam_parse.stream_text(events)
        finally:
            close = getattr(events, "close", None)
            if callable(close):
                close()

    text, final = retry.with_retries(call, **retry_opts(route))
    if final is None:
        raise ProviderError("Wonder stream ended without a completed response", provider=route.provider)
    searched, queries, cited, sources = search_evidence(final)
    try:
        answer = extract_json(text)
    except ValueError:
        answer = {"values": []}
    values, notes = accept_values(answer, want, searched, sources, cited)
    if isinstance(answer, dict) and answer.get("notes"):
        notes.append(f"model note: {str(answer['notes'])[:300]}")
    usage = meta.usage_of(final)
    usd = pricing.token_cost_usd(route.provider, route.model, usage) + pricing.web_search_cost_usd(
        route.provider, queries
    )
    payload = {"values": values, "searched": searched, "notes": notes, "queries": queries, "sources": sources}
    return Outcome(payload, usage, route.model, round(usd, 8))


def _mock(query: str, want: Sequence[str], fixture: Mapping[str, float] | None) -> dict[str, Any]:
    handler = mocks.handler_for("spec_lookup")
    supplied: Mapping[str, Any] = fixture or {}
    if handler is not None and not supplied:
        from .base import ModelRequest

        supplied = handler(
            ModelRequest(messages=[{"role": "user", "content": query}], mock_context={"want": list(want)})
        )
    values = []
    for name in want:
        if name in supplied:
            slug = _norm_name(name) or "value"
            citation = Citation(
                url=f"https://example.invalid/mock-spec/{slug}",
                title=MOCK_NOTE,
                quote="MOCK fixture value supplied by the caller; not from any source",
            )
            values.append({"name": name, "value_mm": float(supplied[name]), "citation": citation})
    return {"values": values, "searched": False, "notes": [MOCK_NOTE], "queries": 0, "sources": []}


def _encode(v: dict[str, Any]) -> dict[str, Any]:
    return {**v, "values": [{**x, "citation": x["citation"].model_dump()} for x in v["values"]]}


def _decode(r: dict[str, Any]) -> dict[str, Any]:
    return {**r, "values": [{**x, "citation": Citation.model_validate(x["citation"])} for x in r.get("values", [])]}


def lookup_spec(query: str, want: Sequence[str], *, fixture: Mapping[str, float] | None = None) -> SpecLookup:
    """Find published values (mm) for `want` on the part described by `query`, each with a checked citation."""
    if not want:
        raise ValueError("lookup_spec needs at least one wanted dimension")
    want = list(dict.fromkeys(want))
    request = {"query": query, "want": want}
    digest = replay.request_hash("spec_lookup", "spec_lookup", request)
    out = dispatch(
        "spec_lookup",
        digest,
        request=request,
        mock=lambda: _mock(query, want, fixture),
        attempt=lambda route: _live(route, query, want),
        encode=_encode,
        decode=_decode,
    )
    v = out.value
    return SpecLookup(
        values=list(v["values"]), searched=bool(v["searched"]), notes=list(v["notes"]), mode=out.mode,
        provider=out.provider, model=out.model, usd=out.usd, queries=int(v.get("queries", 0)),
        sources=list(v.get("sources", [])),
    )  # fmt: skip
