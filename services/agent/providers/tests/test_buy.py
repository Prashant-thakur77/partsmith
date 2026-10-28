"""Buy-or-print lookup: code keeps only cited offers/places; mock is labelled and never invents a price."""

from __future__ import annotations

import json
from typing import Any

import pytest

from services.agent import providers
from services.agent.providers import buy, mocks

from .conftest import FakeHub

SOURCES = ["https://shop.example.com/remote-cover", "https://oem.example.com/part/RC-123", "https://fab.example.in/"]


def _answer() -> dict[str, Any]:
    return {
        "oem": {"name": "Remote battery door", "number": "RC-123", "url": SOURCES[1], "quote": "Part no. RC-123"},
        "offers": [
            {"seller": "Shop", "price": 349, "currency": "₹", "url": SOURCES[0], "quote": "Price: ₹349.00 incl. tax"},
            {"seller": "NoLink", "price": 99, "currency": "INR", "url": "", "quote": "₹99"},
            {"seller": "Ftp", "price": 99, "currency": "INR", "url": "ftp://x.example.com/a", "quote": "₹99"},
            {"seller": "Made up", "price": 5, "currency": "USD", "url": "https://made-up.example.org/x", "quote": "$5"},
            {"seller": "NoQuote", "price": 7, "currency": "USD", "url": SOURCES[0] + "?b", "quote": " "},
            {"seller": "WrongPrice", "price": 1299, "currency": "INR", "url": SOURCES[2], "quote": "Only ₹1,199!"},
            {"seller": "Thousands", "price": 1199, "currency": "INR", "url": SOURCES[2], "quote": "Only ₹1,199!"},
            {"seller": "Coins", "price": 3, "currency": "doubloons", "url": SOURCES[1], "quote": "3 doubloons"},
        ],
        "places": [
            {"name": "Fab Lab", "kind": "maker_space", "url": SOURCES[2], "quote": "3D printing on demand"},
            {"name": "Ghost cafe", "kind": "repair_cafe", "url": "https://ghost.example.net", "quote": "Repairs"},
        ],
        "notes": "prices change daily",
    }


def test_mock_is_labelled_and_never_invents() -> None:
    out = providers.buy_lookup("battery compartment cover", city="Pune")
    assert out.mode == "mock" and out.label == buy.MOCK_NOTE
    assert out.offers == [] and out.places == [] and out.oem is None and not out.searched
    with pytest.raises(ValueError):
        providers.buy_lookup("  ")


def test_fixture_goes_through_the_same_rules() -> None:
    out = providers.buy_lookup("battery cover", city="Pune", fixture={"answer": _answer(), "sources": SOURCES})
    assert out.mode == "mock" and not out.searched and buy.MOCK_NOTE in out.notes[0]
    assert [o["seller"] for o in out.offers] == ["Shop", "Thousands"]
    assert out.offers[0]["currency"] == "INR" and out.offers[0]["price"] == 349
    assert [p["name"] for p in out.places] == ["Fab Lab"] and out.places[0]["city"] == "Pune"
    joined = " | ".join(out.dropped)
    for why in ("'NoLink': dropped — no http(s) source URL", "'Ftp': dropped — no http(s)",
                "'Made up': dropped — https://made-up.example.org/x was not among", "'NoQuote': dropped",
                "'WrongPrice': dropped — the quote does not show the price 1299", "unknown currency 'doubloons'",
                "'Ghost cafe': dropped"):  # fmt: skip
        assert why in joined, why
    # a registered mock works the same way; without a city every place is dropped
    mocks.register_mock("buy_lookup", lambda req: {"answer": _answer(), "sources": SOURCES})
    no_city = providers.buy_lookup("battery cover")
    assert no_city.places == [] and "place 'Fab Lab': dropped — no city was given" in no_city.dropped


def test_price_in_quote_and_currency() -> None:
    assert buy.price_in_quote(1199, "Only ₹1,199!") and buy.price_in_quote(349, "₹349.00")
    assert buy.price_in_quote(12.5, "$12.50 each") and not buy.price_in_quote(12.5, "$125")
    assert buy.currency_code("₹") == "INR" and buy.currency_code("usd") == "USD" and buy.currency_code("??") is None


def _response(searched: bool) -> dict[str, Any]:
    text = "Found: " + json.dumps(_answer())
    output: list[dict[str, Any]] = []
    if searched:
        output.append({"type": "web_search_call", "status": "completed",
                       "action": {"type": "search", "sources": [{"url": u} for u in SOURCES]}})  # fmt: skip
    output.append({"type": "message", "content": [{"type": "output_text", "text": text, "annotations": []}]})
    return {"output": output, "usage": {"input_tokens": 1000, "output_tokens": 200}}


@pytest.mark.parametrize("searched", [True, False])
def test_live_keeps_only_cited_items(monkeypatch: pytest.MonkeyPatch, hub: FakeHub, searched: bool) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "k-meta-000000")
    resp = _response(searched)
    text = resp["output"][-1]["content"][0]["text"]
    lane = {"item_id": "m", "output_index": 0, "content_index": 0}
    hub.handlers[("responses", "meta")] = [
        [
            {"type": "response.output_text.delta", **lane, "delta": text},
            {"type": "response.completed", "response": resp},
        ]
    ]
    events: list[Any] = []
    with providers.job_context("j_test", events.append):
        out = providers.buy_lookup("remote battery cover", city="Pune")
    kw = hub.calls_for("responses")[0]
    assert kw["model"] == "muse-wonder-1.0" and kw["tool_choice"] == "auto"
    assert kw["tools"][0]["type"] == "web_search" and kw["tools"][0]["user_location"]["city"] == "Pune"
    assert out.mode == "live" and out.label == "web search with citations"
    calls = [e for e in events if getattr(e, "t", None) == "model_call"]
    assert calls and calls[0].stage == "buy_lookup"
    if searched:
        assert [o["seller"] for o in out.offers] == ["Shop", "Thousands"] and out.oem is not None
        assert out.oem["number"] == "RC-123" and out.queries == 1
        assert out.usd == pytest.approx((1000 * 4.0 + 200 * 20.0) / 1e6 + 0.0025)
    else:
        assert out.offers == [] and out.places == [] and out.oem is None
        assert all("no web search ran" in d for d in out.dropped)
