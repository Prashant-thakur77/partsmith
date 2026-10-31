// Unit tests for the buy-or-print card helpers and its tolerant schema (node --test; no browser, no network).
import assert from "node:assert/strict";
import test from "node:test";
import { BuyOrPrintSchema } from "../src/lib/api-types.ts";
import { cardBadge, cardCurrency, cardMode, citedOem, citedOffers, citedPlaces, cityParam, costEntries, costIn, hostOf, localeCurrency, lookupState, money, safeHref } from "../src/lib/buy-or-print.ts";

const offer = (o = {}) => ({ seller: "Spares Co", price: 349, currency: "INR", url: "https://spares.example.in/p/1", quote: "Price: ₹349", title: "", availability: "", ...o });

test("only absolute http(s) links count as a source", () => {
  assert.equal(safeHref("https://a.example/x"), "https://a.example/x");
  assert.equal(safeHref("http://a.example"), "http://a.example/");
  for (const bad of ["javascript:alert(1)", "data:text/html,hi", "/relative", "ftp://a.example", "", null, undefined, "not a url"]) {
    assert.equal(safeHref(bad), null, String(bad));
  }
  assert.equal(hostOf("https://www.shop.example/x"), "shop.example");
});

test("a price is never shown without its link, a positive finite amount and an ISO currency", () => {
  const lookup = {
    offers: [
      offer(),
      offer({ url: "javascript:alert(1)" }),
      offer({ url: "" }),
      offer({ price: 0 }),
      offer({ price: -5 }),
      offer({ currency: "rupees" }),
      offer({ seller: "  " }),
      offer({ currency: "usd", price: 4.5, url: "https://b.example/" }),
    ],
  };
  const out = citedOffers(lookup);
  assert.deepEqual(
    out.map((o) => [o.seller, o.price, o.currency, o.href]),
    [
      ["Spares Co", 349, "INR", "https://spares.example.in/p/1"],
      ["Spares Co", 4.5, "USD", "https://b.example/"],
    ],
  );
  assert.deepEqual(citedOffers(null), []);
});

test("places only exist when the lookup had a city, and only with a link", () => {
  const places = [
    { name: "MakerHub", kind: "maker_space", url: "https://makerhub.example", quote: "open Sat", city: "Pune" },
    { name: "No link", kind: "print_shop", url: "mailto:x@y", quote: "", city: "Pune" },
  ];
  assert.deepEqual(citedPlaces({ city: null, places }), []);
  assert.deepEqual(citedPlaces({ city: "Pune", places }).map((p) => p.name), ["MakerHub"]);
});

test("the OEM part name needs its source link", () => {
  assert.equal(citedOem({ oem: { name: "Lid hinge", number: "A12", url: "javascript:x", quote: "q" } }), null);
  assert.equal(citedOem({ oem: null }), null);
  assert.equal(citedOem({ oem: { name: "Lid hinge", number: "A12", url: "https://oem.example/a12", quote: "q" } })?.href, "https://oem.example/a12");
});

test("money is formatted in its own currency, unknown codes fall back to plain text", () => {
  assert.match(money(1200, "INR"), /1,200/);
  assert.match(money(20, "USD"), /20/);
  assert.equal(money(12.5, "NOTACODE"), "12.50 NOTACODE");
  assert.deepEqual(
    costEntries({ filament_cost: { USD: 0.2, EUR: 0.19, INR: 14.8, BAD: Number.NaN } }).map((c) => c.currency),
    ["INR", "USD", "EUR"],
  );
});

test("the city sent with a lookup is trimmed, collapsed and capped at 80 characters", () => {
  assert.equal(cityParam("  New   Delhi "), "New Delhi");
  assert.equal(cityParam("   "), null);
  assert.equal(cityParam(null), null);
  assert.equal(cityParam("x".repeat(120))?.length, 80);
});

test("lookup state and mode badge", () => {
  assert.equal(lookupState({ lookup: null }), "none");
  assert.equal(lookupState({ lookup: { mode: "mock", searched: false } }), "mock");
  assert.equal(lookupState({ lookup: { mode: "live", searched: true } }), "searched");
  assert.equal(lookupState({ lookup: { mode: "replay", searched: false } }), "not_searched");
  assert.equal(cardMode({ lookup: null, mode: "mock" }), "mock");
  assert.equal(cardMode({ lookup: { mode: "live" }, mode: "mock" }), "live");
});

test("the provenance chip follows the card's own flags, never the server's mode", () => {
  // no lookup stored: no mode to claim (a part page used to say "Recorded run · mock models" here)
  assert.deepEqual(cardBadge({ lookup: null, mode: "mock", recorded: true, stored: false }), { kind: "none", mode: "mock" });
  // a live job's stored lookup read back on a replaying server: stored, not a recorded run, never the LIVE chip
  assert.deepEqual(cardBadge({ lookup: { mode: "live" }, mode: "live", recorded: false, stored: true }), { kind: "stored", mode: "live" });
  // a recorded run's card: played back
  assert.deepEqual(cardBadge({ lookup: { mode: "live" }, mode: "live", recorded: true, stored: true }), { kind: "recorded", mode: "live" });
  // a lookup that ran for this request
  assert.deepEqual(cardBadge({ lookup: { mode: "mock" }, mode: "mock", recorded: false, stored: false }), { kind: "fresh", mode: "mock" });
  // older servers send neither flag: the schema defaults both to false
  const parsed = BuyOrPrintSchema.parse({ title: "x", status: "verified", mode: "live", prints: [], lookup: null });
  assert.equal(parsed.stored, false);
  assert.equal(parsed.recorded, false);
});

test("the card schema drops malformed offers, places and estimates instead of failing the page", () => {
  const raw = {
    job_id: "j1",
    status: "verified",
    mode: "live",
    prints: [{ material: "PLA", volume_mm3: 1000, grams: 1.24, print_minutes: 12, filament_cost: { INR: 1.49 }, price_per_kg: { INR: 1200 }, assumptions: ["PLA 1.24 g/cm³"] }, { material: "PETG" }],
    lookup: {
      query: "lid hinge",
      city: "Pune",
      oem: { name: 42 },
      offers: [offer(), { seller: "x", price: "cheap" }, null],
      places: "nope",
      dropped: ["offer from blog.example: no quote", 7],
      searched: true,
      mode: "live",
      label: "",
    },
    notes: ["n1"],
  };
  const r = BuyOrPrintSchema.safeParse(raw);
  assert.equal(r.success, true);
  const d = r.data;
  assert.equal(d.prints.length, 1);
  assert.equal(d.lookup.oem, null);
  assert.equal(d.lookup.offers.length, 1);
  assert.deepEqual(d.lookup.places, []);
  assert.deepEqual(d.lookup.dropped, ["offer from blog.example: no quote"]);
  // a lookup that is not an object at all reads as "no lookup", the print side still shows
  const r2 = BuyOrPrintSchema.safeParse({ prints: raw.prints, lookup: "broken" });
  assert.equal(r2.success, true);
  assert.equal(r2.data.lookup, null);
  assert.equal(r2.data.prints.length, 1);
});

test("one currency per card: the cited offers' currency, else the viewer's locale; never converted", () => {
  const prints = [{ material: "PLA", grams: 2, filament_cost: { INR: 2.4, USD: 0.03 }, assumptions: [] }];
  const offer = (currency) => ({ seller: "S", price: 10, currency, url: "https://s.example.com", quote: "" });
  const card = (offers) => BuyOrPrintSchema.parse({ prints, lookup: offers ? { offers } : null });
  assert.equal(cardCurrency(card([offer("usd"), offer("USD"), offer("INR")]), "en-IN"), "USD"); // the price source wins
  assert.equal(cardCurrency(card(null), "en-IN"), "INR");
  assert.equal(cardCurrency(card(null), "en-US"), "USD");
  assert.equal(cardCurrency(BuyOrPrintSchema.parse({ prints: [{ ...prints[0], filament_cost: { EUR: 0.03 } }] }), "en-US"), "EUR");
  assert.equal(localeCurrency("hi"), "INR");
  assert.equal(costIn(prints[0], "USD"), 0.03);
  assert.equal(costIn(prints[0], "EUR"), null);
});
