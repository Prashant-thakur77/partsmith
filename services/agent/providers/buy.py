"""Buy-or-print lookup: a search-grounded model proposes where to buy the original part; code keeps only cited facts.

Live: Responses API on `muse-wonder-1.0` (fallback `muse-spark-1.3`) with the built-in `web_search` tool, the user's
city as `user_location` when given, raw results requested with `include=["web_search_call.results"]`; `tool_choice`
"auto". The model answers with JSON in its text (the same proven shape as the spec lookup). Code then decides:
- nothing is kept unless a search actually ran (a `web_search_call` item in the output);
- every offer, place and OEM name needs an http(s) URL that the search returned and a non-empty quote from that page;
- an offer's price must be positive and appear in its quote, and its currency must resolve to an ISO 4217 code;
- places (print shops, repair cafés) are kept only when the user gave a city.
A price is never shown without its link: whatever fails a rule is listed in `dropped` with the reason.

Mock: a clearly labelled empty result (`MOCK — no web search ran`); it never invents a seller or a price. Tests and
UI fixtures pass `fixture=` (or `register_mock("buy_lookup", ...)`) with an answer in the live JSON shape, which goes
through the same code rules (its URLs must be listed in `fixture["sources"]`).
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from . import meta, mocks, pricing, replay, retry, sam_parse
from .base import ModelRequest, ProviderError
from .config import Mode, settings
from .core import Outcome, dispatch, retry_opts
from .jsonschema_lite import extract_json, validate
from .routing import Route
from .spec import search_evidence

MOCK_NOTE = "MOCK — no web search ran"
MAX_OFFERS = 8
MAX_PLACES = 6
CURRENCY_SYMBOLS = {"₹": "INR", "rs": "INR", "rs.": "INR", "inr": "INR", "$": "USD", "us$": "USD", "€": "EUR",
                    "£": "GBP", "¥": "JPY", "a$": "AUD", "c$": "CAD"}  # fmt: skip
PLACE_KINDS = ("print_shop", "repair_cafe", "maker_space", "other")

ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "oem": {
            "type": ["object", "null"],
            "properties": {
                "name": {"type": "string"},
                "number": {"type": "string"},
                "url": {"type": "string"},
                "quote": {"type": "string"},
            },
        },
        "offers": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "seller": {"type": "string"},
                    "price": {"type": "number"},
                    "currency": {"type": "string"},
                    "url": {"type": "string"},
                    "quote": {"type": "string"},
                    "title": {"type": "string"},
                    "availability": {"type": "string"},
                },
                "required": ["seller", "price", "currency", "url", "quote"],
            },
        },
        "places": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "kind": {"type": "string"},
                    "url": {"type": "string"},
                    "quote": {"type": "string"},
                    "city": {"type": "string"},
                },
                "required": ["name", "url", "quote"],
            },
        },
        "notes": {"type": "string"},
    },
    "required": ["offers"],
}

INSTRUCTIONS = """You help someone decide whether to buy an original replacement part or 3D-print it. Search the web.
1. Identify the original (OEM) part: its name and part number if a page states them.
2. Find where it is sold now: seller, price, currency, and the exact text from the page that shows the price.
3. If a city is given, find 3D-print shops, repair cafés or maker spaces in or near that city.
Report only what you found on a page you can cite; never estimate a price. Answer with one JSON object:
{"oem": {"name", "number", "url", "quote"} | null,
 "offers": [{"seller", "price", "currency" (ISO code), "url", "quote", "title", "availability"}],
 "places": [{"name", "kind" (print_shop|repair_cafe|maker_space|other), "url", "quote", "city"}],
 "notes"}
"quote" is the exact sentence or table cell from the page; for an offer it must contain the price."""


@dataclass
class BuyResult:
    query: str
    city: str | None
    oem: dict[str, str] | None
    offers: list[dict[str, Any]]
    places: list[dict[str, Any]]
    dropped: list[str]
    searched: bool
    queries: int = 0
    mode: Mode = "mock"
    provider: str = ""
    model: str = ""
    usd: float = 0.0
    notes: list[str] = field(default_factory=list)

    @property
    def label(self) -> str:
        if self.mode == "mock":
            return MOCK_NOTE
        if self.mode == "replay":
            return "replayed recording of a web search"
        return "web search with citations"


def _http(url: str) -> bool:
    return bool(re.match(r"^https?://[^\s/]+\.[^\s]+", url.strip(), re.IGNORECASE))


def _norm_url(url: str) -> str:
    return url.strip().rstrip("/").split("#", 1)[0].lower()


def currency_code(raw: str) -> str | None:
    """ISO 4217 code for a currency as a model or page writes it (code or common symbol), else None."""
    s = raw.strip()
    if re.fullmatch(r"[A-Za-z]{3}", s):
        return s.upper()
    return CURRENCY_SYMBOLS.get(s.lower())


def price_in_quote(price: float, quote: str) -> bool:
    """True when the quote shows this price (digits with any thousands separators; decimals optional)."""
    digits = [re.sub(r"[,\s  ']", "", m) for m in re.findall(r"\d[\d,\s  '.]*\d|\d", quote)]
    for d in digits:
        try:
            if math.isclose(float(d), price, rel_tol=0, abs_tol=0.005):
                return True
        except ValueError:
            continue
    return False


def accept_answer(
    answer: Any, searched: bool, allowed_urls: Sequence[str], *, city: str | None
) -> tuple[dict[str, str] | None, list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Code decides what stands: (oem, offers, places, dropped reasons)."""
    if validate(answer, ANSWER_SCHEMA):
        return None, [], [], ["model answer did not match the expected JSON shape"]
    dropped: list[str] = []
    allowed = {_norm_url(u) for u in allowed_urls}

    def cited(kind: str, label: str, url: str, quote: str) -> bool:
        if not searched:
            dropped.append(f"{kind} {label!r}: dropped — no web search ran, so it has no source")
            return False
        if not _http(url):
            dropped.append(f"{kind} {label!r}: dropped — no http(s) source URL")
            return False
        if _norm_url(url) not in allowed:
            dropped.append(f"{kind} {label!r}: dropped — {url} was not among the pages the search returned")
            return False
        if not quote.strip():
            dropped.append(f"{kind} {label!r}: dropped — no quote from the page")
            return False
        return True

    oem: dict[str, str] | None = None
    o = answer.get("oem")
    if isinstance(o, dict) and str(o.get("name") or "").strip():
        name, url, quote = str(o["name"]).strip()[:200], str(o.get("url") or ""), str(o.get("quote") or "")
        if cited("OEM part", name, url, quote):
            oem = {"name": name, "number": str(o.get("number") or "").strip()[:80], "url": url.strip(),
                   "quote": quote.strip()[:300]}  # fmt: skip

    offers: list[dict[str, Any]] = []
    for x in answer.get("offers", []):
        seller = str(x.get("seller") or "").strip()[:120] or "?"
        url, quote = str(x["url"]), str(x.get("quote") or "")
        if not cited("offer", seller, url, quote):
            continue
        price = float(x["price"])
        if not math.isfinite(price) or price <= 0:
            dropped.append(f"offer {seller!r}: dropped — unusable price {x['price']}")
            continue
        cur = currency_code(str(x.get("currency") or ""))
        if cur is None:
            dropped.append(f"offer {seller!r}: dropped — unknown currency {x.get('currency')!r}")
            continue
        if not price_in_quote(price, quote):
            dropped.append(f"offer {seller!r}: dropped — the quote does not show the price {price:g}")
            continue
        if any(_norm_url(o2["url"]) == _norm_url(url) for o2 in offers):
            dropped.append(f"offer {seller!r}: duplicate page ignored")
            continue
        offers.append({"seller": seller, "price": round(price, 2), "currency": cur, "url": url.strip(),
                       "quote": quote.strip()[:300], "title": str(x.get("title") or "")[:200],
                       "availability": str(x.get("availability") or "")[:80]})  # fmt: skip

    places: list[dict[str, Any]] = []
    for x in answer.get("places", []):
        name = str(x.get("name") or "").strip()[:120] or "?"
        if not city:
            dropped.append(f"place {name!r}: dropped — no city was given")
            continue
        url, quote = str(x["url"]), str(x.get("quote") or "")
        if not cited("place", name, url, quote):
            continue
        kind = str(x.get("kind") or "other")
        places.append({"name": name, "kind": kind if kind in PLACE_KINDS else "other", "url": url.strip(),
                       "quote": quote.strip()[:300], "city": str(x.get("city") or city)[:80]})  # fmt: skip
    if len(offers) > MAX_OFFERS:
        dropped.append(f"{len(offers) - MAX_OFFERS} more offer(s) not shown")
    if len(places) > MAX_PLACES:
        dropped.append(f"{len(places) - MAX_PLACES} more place(s) not shown")
    return oem, offers[:MAX_OFFERS], places[:MAX_PLACES], dropped


def _user_text(query: str, city: str | None) -> str:
    return f"Part: {query}" + (f"\nCity: {city}" if city else "\nNo city given: skip local places.")


def _live(route: Route, query: str, city: str | None) -> Outcome[dict[str, Any]]:
    timeout = max(settings().timeout_s, 300.0)
    client = meta.client_for(route, timeout)
    tool: dict[str, Any] = {"type": "web_search", "search_context_size": "medium"}
    if city:
        tool["user_location"] = {"type": "approximate", "city": city}
    kwargs = {
        "model": route.model,
        "input": [
            {"type": "message", "role": "developer", "content": INSTRUCTIONS},
            {"type": "message", "role": "user", "content": [{"type": "input_text", "text": _user_text(query, city)}]},
        ],
        "tools": [tool],
        "tool_choice": "auto",
        "include": ["web_search_call.results"],
        "reasoning": {"effort": "low", "summary": "auto"},
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
        raise ProviderError("buy lookup stream ended without a completed response", provider=route.provider)
    searched, queries, _, sources = search_evidence(final)
    try:
        answer = extract_json(text)
    except ValueError:
        answer = {"offers": []}
    oem, offers, places, dropped = accept_answer(answer, searched, sources, city=city)
    notes = [f"model note: {str(answer['notes'])[:300]}"] if isinstance(answer, dict) and answer.get("notes") else []
    usage = meta.usage_of(final)
    usd = pricing.token_cost_usd(route.provider, route.model, usage) + pricing.web_search_cost_usd(
        route.provider, queries
    )
    payload = {"oem": oem, "offers": offers, "places": places, "dropped": dropped, "searched": searched,
               "queries": queries, "notes": notes}  # fmt: skip
    return Outcome(payload, usage, route.model, round(usd, 8))


def _mock(query: str, city: str | None, fixture: Mapping[str, Any] | None) -> dict[str, Any]:
    supplied: Mapping[str, Any] | None = fixture
    handler = mocks.handler_for("buy_lookup")
    if supplied is None and handler is not None:
        supplied = handler(ModelRequest(messages=[{"role": "user", "content": _user_text(query, city)}],
                                        mock_context={"query": query, "city": city}))  # fmt: skip
    if not supplied:
        return {"oem": None, "offers": [], "places": [], "dropped": [], "searched": False, "queries": 0,
                "notes": [MOCK_NOTE]}  # fmt: skip
    # A fixture is a live-shaped answer: the same code rules apply, with its own list of "search results".
    sources = [str(u) for u in supplied.get("sources", [])]
    oem, offers, places, dropped = accept_answer(dict(supplied.get("answer", {})), bool(sources), sources, city=city)
    return {"oem": oem, "offers": offers, "places": places, "dropped": dropped, "searched": False, "queries": 0,
            "notes": [MOCK_NOTE + " (fixture answer checked by the live rules)"]}  # fmt: skip


def buy_lookup(query: str, *, city: str | None = None, fixture: Mapping[str, Any] | None = None) -> BuyResult:
    """Where to buy the original part described by `query` (and print shops near `city`), every item cited."""
    query = query.strip()
    if not query:
        raise ValueError("buy_lookup needs a part description")
    city = (city or "").strip() or None
    request = {"query": query, "city": city}
    digest = replay.request_hash("buy_lookup", "buy_lookup", request)
    out = dispatch(
        "buy_lookup",
        digest,
        request=request,
        mock=lambda: _mock(query, city, fixture),
        attempt=lambda route: _live(route, query, city),
        encode=dict,
        decode=dict,
    )
    v = out.value
    return BuyResult(
        query=query, city=city, oem=v.get("oem"), offers=list(v.get("offers", [])), places=list(v.get("places", [])),
        dropped=list(v.get("dropped", [])), searched=bool(v.get("searched")), queries=int(v.get("queries", 0)),
        mode=out.mode, provider=out.provider, model=out.model, usd=out.usd, notes=list(v.get("notes", [])),
    )  # fmt: skip
