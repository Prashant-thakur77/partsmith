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
