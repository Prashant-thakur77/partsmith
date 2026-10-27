"""Repair-shop batch mode: group jobs by customer and print one job sheet per batch.

A batch is a JSON file under `$PARTSMITH_HOME/batches/`. The sheet lists, per customer, each part with its code-decided
status and max error, suggested print settings, PLA grams and a price estimate = grams × `PARTSMITH_PRICE_PER_G_INR`
(+ `PARTSMITH_PRICE_BASE_INR` per part). Prices are estimates from the configured rate, shown with the rate used.
"""

from __future__ import annotations

import io
import json
import os
import re
import secrets
import threading
import time
from collections.abc import Callable, Sequence
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from services.common.paths import sub
from services.media.repair_card import PrintSettings

VERIFIED = colors.HexColor("#15803d")
BEST_EFFORT = colors.HexColor("#b45309")
FAILED = colors.HexColor("#b41414")
_lock = threading.Lock()

JobInfo = Callable[[str], dict[str, Any] | None]


def price_rate() -> tuple[float, float]:
    """(₹ per gram of PLA, ₹ base fee per part) from the environment."""
    return float(os.environ.get("PARTSMITH_PRICE_PER_G_INR", "3.0")), float(
        os.environ.get("PARTSMITH_PRICE_BASE_INR", "0")
    )


def _path(bid: str) -> Any:
    if not re.fullmatch(r"b_[0-9a-z_]+", bid):
        raise KeyError(bid)
    return sub("batches") / f"{bid}.json"


def _clean_customers(customers: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for c in customers:
        name = str(c.get("name", "")).strip()[:80]
        if not name:
            raise ValueError("every customer needs a name")
        jobs = [str(j) for j in c.get("jobs", []) if re.fullmatch(r"[A-Za-z0-9_\-]{3,64}", str(j))]
        out.append({"name": name, "contact": str(c.get("contact", "")).strip()[:80], "jobs": list(dict.fromkeys(jobs))})
    return out


def create(name: str, customers: Sequence[dict[str, Any]]) -> dict[str, Any]:
    bid = "b_" + time.strftime("%y%m%d") + "_" + secrets.token_hex(4)
    batch = {"id": bid, "name": name.strip()[:120] or "Batch", "created_at": time.time(),
             "customers": _clean_customers(customers)}  # fmt: skip
    _save(batch)
    return batch


def _save(batch: dict[str, Any]) -> None:
    p = _path(batch["id"])
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(batch, indent=1))
    tmp.replace(p)


def get(bid: str) -> dict[str, Any]:
    p = _path(bid)
    if not p.exists():
        raise KeyError(bid)
    data: dict[str, Any] = json.loads(p.read_text())
    return data


def list_batches(limit: int = 50) -> list[dict[str, Any]]:
    files = sorted(sub("batches").glob("b_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:limit]
    out = []
    for f in files:
        b = json.loads(f.read_text())
        out.append({"id": b["id"], "name": b["name"], "created_at": b["created_at"], "customers": len(b["customers"]),
                    "jobs": sum(len(c["jobs"]) for c in b["customers"])})  # fmt: skip
    return out


def add_job(bid: str, customer: str, job_id: str, contact: str = "") -> dict[str, Any]:
    with _lock:
        batch = get(bid)
        cust = next((c for c in batch["customers"] if c["name"] == customer.strip()), None)
        if cust is None:
            cust = _clean_customers([{"name": customer, "contact": contact}])[0]
            batch["customers"].append(cust)
        if not re.fullmatch(r"[A-Za-z0-9_\-]{3,64}", job_id):
            raise ValueError(f"bad job id {job_id!r}")
        if job_id not in cust["jobs"]:
            cust["jobs"].append(job_id)
        _save(batch)
        return batch


def rows(batch: dict[str, Any], job_info: JobInfo) -> list[dict[str, Any]]:
    """One row per job with the numbers the sheet prints (also the JSON of GET /batches/{id})."""
    rate, base = price_rate()
    settings = PrintSettings()
    out = []
    for c in batch["customers"]:
        for jid in c["jobs"]:
            info = job_info(jid) or {}
            facts = info.get("facts") or {}
            grams = facts.get("mass_g_pla")
            price = round(grams * rate + base, 2) if isinstance(grams, (int, float)) else None
            out.append({
                "customer": c["name"], "contact": c.get("contact", ""), "job_id": jid,
                "title": info.get("title") or "(unknown job)", "status": info.get("status", "unknown"),
                "verified": bool(info.get("verified")), "max_error_mm": info.get("max_error_mm"),
                "origin": info.get("origin", ""), "part_slug": info.get("part_slug"),
                "grams_pla": grams, "price_inr": price, "orientation": facts.get("orientation"),
                "supports": facts.get("supports_needed"), "print_minutes": facts.get("print_minutes_est"),
                "material": settings.material, "layer_mm": settings.layer_height_mm, "walls": settings.walls,
                "infill_percent": settings.infill_percent,
            })  # fmt: skip
    return out


def _state(r: dict[str, Any]) -> tuple[str, Any]:
    if r["verified"]:
        err = f" {r['max_error_mm']:.2f} mm" if r["max_error_mm"] is not None else ""
        return f"VERIFIED{err}", VERIFIED
    if r["status"] == "done":
        err = f" {r['max_error_mm']:.2f} mm" if r["max_error_mm"] is not None else ""
        return f"BEST EFFORT{err}", BEST_EFFORT
    return r["status"].upper(), FAILED


def sheet_pdf(batch: dict[str, Any], job_info: JobInfo) -> bytes:
    """A4 job sheet: one section per customer, one row per part, totals at the end of each section."""
    rate, base = price_rate()
    data = rows(batch, job_info)
    buf = io.BytesIO()
    c = Canvas(buf, pagesize=A4, pageCompression=0, invariant=1)
    c.setTitle(f"Job sheet - {batch['name']}")
    width, height = A4
    margin = 14 * mm
    y = height - margin

    def need(space: float) -> None:
        nonlocal y
        if y - space < margin:
            c.showPage()
            y = height - margin

    def text(s: str, x: float, size: float = 9, bold: bool = False, color: Any = colors.black) -> None:
        c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        c.setFillColor(color)
        c.drawString(x, y, s)

    text("PartSmith job sheet", margin, 8, color=colors.grey)
    y -= 6 * mm
    text(batch["name"], margin, 16, bold=True)
    y -= 6 * mm
    text(f"Batch {batch['id']} · {time.strftime('%Y-%m-%d', time.localtime(batch['created_at']))} · price estimate = "
         f"PLA grams × INR {rate:g}/g" + (f" + INR {base:g} per part" if base else ""), margin, 8, color=colors.grey)  # fmt: skip
    y -= 9 * mm
    cols = [margin, margin + 62 * mm, margin + 104 * mm, margin + 150 * mm]
    for cust in batch["customers"]:
        mine = [r for r in data if r["customer"] == cust["name"]]
        need(24 * mm)
        text(cust["name"] + (f"  ·  {cust['contact']}" if cust.get("contact") else ""), margin, 11, bold=True)
        y -= 5.5 * mm
        for i, label in enumerate(("Part", "Status (code-decided)", "Print", "Grams / price")):
            text(label, cols[i], 7.5, bold=True, color=colors.grey)
        y -= 4.5 * mm
        total = 0.0
        for r in mine:
            need(14 * mm)
            text(r["title"][:42], cols[0], 8.5, bold=True)
            label, col = _state(r)
            text(label, cols[1], 8.5, bold=True, color=col)
            sup = "supports" if r["supports"] else "no supports" if r["supports"] is not None else "supports: n/a"
            text(f"{r['material']} {r['layer_mm']:g} mm, {r['walls']} walls, {r['infill_percent']}%", cols[2], 8)
            grams = f"{r['grams_pla']:.1f} g" if r["grams_pla"] is not None else "—"
            price = f"INR {r['price_inr']:.0f}" if r["price_inr"] is not None else "—"
            text(f"{grams} · {price}", cols[3], 8.5)
            y -= 4 * mm
            text(f"job {r['job_id']}" + (" · SYNTHETIC" if r["origin"] == "synthetic" else ""), cols[0], 7,
                 color=colors.grey)  # fmt: skip
            orient = (r["orientation"] or "").split(":")[0]
            mins = f", ~{r['print_minutes']:.0f} min" if r["print_minutes"] is not None else ""
            text(f"{orient or 'orientation n/a'}, {sup}{mins}", cols[2], 7, color=colors.grey)
            y -= 6 * mm
            total += r["price_inr"] or 0.0
        if not mine:
            text("no jobs yet", cols[0], 8, color=colors.grey)
            y -= 6 * mm
        text(f"Estimate for {cust['name']}: INR {total:.0f}", cols[2], 9, bold=True)
        y -= 9 * mm
        c.setStrokeColor(colors.lightgrey)
        c.line(margin, y + 4 * mm, width - margin, y + 4 * mm)
    c.showPage()
    c.save()
    return buf.getvalue()
