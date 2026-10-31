/**
 * Buy-or-print card helpers. The server already drops every offer, place and OEM name without a cited page and quote;
 * the browser re-applies the one rule it can check on its own: a price, a place or a part name is shown only with an
 * http(s) link to its source. Money is formatted, never computed, here.
 *
 * Kept free of runtime imports so `node --test` can load it directly.
 */
import type { BuyLookup, BuyOrPrint, CitedOffer, CitedPlace, OemPart, PrintEstimate } from "./api-types";

/** The link itself when it is an absolute http(s) URL, else null (javascript:, data:, relative and junk are refused). */
export function safeHref(url: string | null | undefined): string | null {
  if (!url) return null;
  try {
    const u = new URL(url);
    return u.protocol === "https:" || u.protocol === "http:" ? u.href : null;
  } catch {
    return null;
  }
}

/** Host name for a link label ("www.example.in" → "example.in"). */
export function hostOf(url: string): string {
  try {
    return new URL(url).host.replace(/^www\./, "");
  } catch {
    return url;
  }
}

const ISO = /^[A-Z]{3}$/;

/** Offers that can be shown: a seller, a finite positive price, an ISO currency and an http(s) link. */
export function citedOffers(lookup: BuyLookup | null | undefined): (CitedOffer & { href: string })[] {
  const out: (CitedOffer & { href: string })[] = [];
  for (const o of lookup?.offers ?? []) {
    const href = safeHref(o.url);
    if (!href || !o.seller.trim() || !Number.isFinite(o.price) || o.price <= 0 || !ISO.test(o.currency.toUpperCase())) continue;
    out.push({ ...o, currency: o.currency.toUpperCase(), href });
  }
  return out;
}

/** Places that can be shown (http(s) link and a name). Places only exist when the lookup was given a city. */
export function citedPlaces(lookup: BuyLookup | null | undefined): (CitedPlace & { href: string })[] {
  if (!lookup?.city) return [];
  const out: (CitedPlace & { href: string })[] = [];
  for (const p of lookup.places) {
    const href = safeHref(p.url);
    if (href && p.name.trim()) out.push({ ...p, href });
  }
  return out;
}

/** The OEM part name, only with its source link. */
export function citedOem(lookup: BuyLookup | null | undefined): (OemPart & { href: string }) | null {
  const o = lookup?.oem;
  const href = safeHref(o?.url);
  return o && href && o.name.trim() ? { ...o, href } : null;
}

/** Amount in its own currency ("₹1,200.00", "US$20.00"); an unknown code falls back to "12.50 XYZ". */
export function money(amount: number, currency: string, locale = "en-IN"): string {
  try {
    return new Intl.NumberFormat(locale, { style: "currency", currency, maximumFractionDigits: 2 }).format(amount);
  } catch {
    return `${amount.toFixed(2)} ${currency}`;
  }
}

/** Filament cost per currency in a stable order (INR, USD, then the rest alphabetically). */
export function costEntries(p: Pick<PrintEstimate, "filament_cost">): { currency: string; amount: number }[] {
  const rank = (c: string) => (c === "INR" ? 0 : c === "USD" ? 1 : 2);
  return Object.entries(p.filament_cost)
    .filter(([, a]) => Number.isFinite(a))
    .map(([currency, amount]) => ({ currency, amount }))
    .sort((a, b) => rank(a.currency) - rank(b.currency) || a.currency.localeCompare(b.currency));
}

/** The city a POST should carry: trimmed, at most 80 characters (the server's limit), or null when empty. */
export function cityParam(city: string | null | undefined): string | null {
  const c = (city ?? "").trim().replace(/\s+/g, " ");
  return c ? c.slice(0, 80) : null;
}

export type LookupState = "none" | "mock" | "searched" | "not_searched";

/** What the buy side can say: no lookup stored, a labelled mock, a live search, or a lookup where no search ran. */
export function lookupState(card: Pick<BuyOrPrint, "lookup"> | null | undefined): LookupState {
  const l = card?.lookup;
  if (!l) return "none";
  if (l.mode === "mock") return "mock";
  return l.searched ? "searched" : "not_searched";
}

/** The mode badge for the card: the lookup's own mode when one ran, else the card's. */
export function cardMode(card: Pick<BuyOrPrint, "lookup" | "mode">): string {
  return card.lookup?.mode ?? card.mode ?? "mock";
}

/** The currency the viewer most likely reads: INR for an Indian locale ("en-IN", "hi-IN"), else USD. */
export function localeCurrency(locale: string | null | undefined): string {
  return /-IN\b/i.test(locale ?? "") || /^(hi|bn|ta|te|mr|gu|kn|ml|pa)\b/i.test(locale ?? "") ? "INR" : "USD";
}

/**
 * One currency for a whole card, so ₹ and $ never sit side by side: the currency most cited offers are priced in (the
 * price source), else the viewer's locale currency when the filament estimate has it, else the estimate's first
 * currency. Money is never converted here.
 */
export function cardCurrency(card: Pick<BuyOrPrint, "lookup" | "prints"> | null | undefined, locale?: string | null): string {
  const counts = new Map<string, number>();
  for (const o of citedOffers(card?.lookup)) counts.set(o.currency, (counts.get(o.currency) ?? 0) + 1);
  if (counts.size) return [...counts.entries()].sort((a, b) => b[1] - a[1])[0]![0];
  const want = localeCurrency(locale);
  const have = new Set((card?.prints ?? []).flatMap((p) => costEntries(p).map((c) => c.currency)));
  if (have.has(want) || !have.size) return want;
  return costEntries(card!.prints.find((p) => costEntries(p).length)!)[0]!.currency;
}

/** The filament cost in the card's currency only (null when the estimate has none in it). */
export function costIn(p: Pick<PrintEstimate, "filament_cost">, currency: string): number | null {
  const a = p.filament_cost[currency];
  return typeof a === "number" && Number.isFinite(a) ? a : null;
}

/** The locale to format a currency in: Indian grouping for INR, US for the rest. */
export function moneyLocale(currency: string): string {
  return currency === "INR" ? "en-IN" : "en-US";
}
