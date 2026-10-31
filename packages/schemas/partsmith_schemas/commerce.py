"""Buy-or-print card: what printing the part costs (computed by code from the mesh) next to what buying the original
costs (proposed by a search-grounded model, kept only with a cited page and quote). docs/API.md "Buy or print"."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import Strict
from .registry import ProviderMode

Material = Literal["PLA", "PETG"]


class PrintEstimate(Strict):
    """Code's numbers for one material. Grams are the solid volume times the density (100 % infill), an upper
    bound; minutes and costs are labelled estimates (`assumptions` lists every constant used)."""

    material: Material
    volume_mm3: float
    grams: float
    print_minutes: float
    filament_cost: dict[str, float]  # currency code -> cost of `grams` at the assumed spool price
    price_per_kg: dict[str, float]  # currency code -> assumed spool price per kg
    assumptions: list[str] = Field(default_factory=list)


class OemPart(Strict):
    """The original part as a cited page names it."""

    name: str
    number: str = ""
    url: str
    quote: str


class CitedOffer(Strict):
    """A price for the original part. Code keeps it only with an http(s) URL the search returned and a quote that
    contains the price."""

    seller: str
    price: float
    currency: str  # ISO 4217 code
    url: str
    quote: str
    title: str = ""
    availability: str = ""


class CitedPlace(Strict):
    """A nearby print shop, repair café or maker space, kept only with a cited URL and quote."""

    name: str
    kind: Literal["print_shop", "repair_cafe", "maker_space", "other"] = "other"
    url: str
    quote: str
    city: str = ""


class BuyLookup(Strict):
    """The search half of the card. `mode` "mock" means no search ran and nothing here came from the web."""

    query: str
    city: str | None = None
    oem: OemPart | None = None
    offers: list[CitedOffer] = Field(default_factory=list)
    places: list[CitedPlace] = Field(default_factory=list)
    dropped: list[str] = Field(default_factory=list)  # what code removed, and why
    searched: bool = False
    queries: int = 0
    mode: ProviderMode = "mock"
    provider: str = ""
    model: str = ""
    usd: float = 0.0
    label: str = ""  # e.g. "MOCK — no web search ran"


class BuyOrPrint(Strict):
    """One card per job (or published part). Building it never touches the verification: `status` is copied from it."""

    job_id: str | None = None
    slug: str | None = None
    title: str = ""
    status: Literal["verified", "best_effort", "failed", "unknown"] = "unknown"
    prints: list[PrintEstimate] = Field(default_factory=list)
    lookup: BuyLookup | None = None
    mode: ProviderMode = "mock"  # the lookup's mode ("mock" when no lookup ran)
    # True only when this card's lookup was played back: its job is a recorded run, or the lookup's own mode is
    # "replay". A card without a lookup is never recorded. The web then shows "Recorded run", never "live".
    recorded: bool = False
    # True when this answer is a stored card read back (GET): the lookup ran earlier with `mode` (see created_at),
    # nothing was searched for this request. The web shows "<mode> · stored", never the live chip.
    stored: bool = False
    created_at: float = 0.0
    notes: list[str] = Field(default_factory=list)
