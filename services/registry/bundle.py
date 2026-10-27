"""Download bundle (`bundle.zip`) and the iframe viewer (`/embed/{slug}`).

The zip holds everything needed to print and to keep editing a part: `part.py` (PARAMS defaults baked to the
requested values), STEP, STL, 3MF, `verification.json` (the verifier's record plus sha256 of every file), a README
(how to print, which dimensions were measured and which were not, licence), LICENSE and an offline `index.html`
viewer with the mesh embedded (three.js comes from a CDN).
"""

from __future__ import annotations

import hashlib
import html
import io
import json
import time
import zipfile
from collections.abc import Mapping
from typing import Any

from partsmith_schemas import PartRecord

from services.geom_worker.bake import FACT_NOTES
from services.registry import parts as P
from services.registry.gate import ShipDecision

THREE = "https://cdn.jsdelivr.net/npm/three@0.160.0"
LICENCE_URLS = {"CC-BY-4.0": "https://creativecommons.org/licenses/by/4.0/"}

VIEWER_JS = """
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
const el = document.getElementById("view");
const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
el.appendChild(renderer.domElement);
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 10000);
camera.up.set(0, 0, 1);
const controls = new OrbitControls(camera, renderer.domElement);
scene.add(new THREE.HemisphereLight(0xffffff, 0x666666, 2.2));
const sun = new THREE.DirectionalLight(0xffffff, 1.6); sun.position.set(-1, -2, 3); scene.add(sun);
function show(view) {
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(view.mesh.positions, 3));
  if (view.mesh.normals && view.mesh.normals.length === view.mesh.positions.length)
    g.setAttribute("normal", new THREE.Float32BufferAttribute(view.mesh.normals, 3));
  else g.computeVertexNormals();
  g.setIndex(view.mesh.indices);
  scene.add(new THREE.Mesh(g, new THREE.MeshStandardMaterial({ color: 0x9a9da3, roughness: 0.55,
    polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1 })));
  const seg = [];
  for (const line of view.edges || []) for (let i = 0; i + 5 < line.length; i += 3) seg.push(...line.slice(i, i + 6));
  const eg = new THREE.BufferGeometry(); eg.setAttribute("position", new THREE.Float32BufferAttribute(seg, 3));
  scene.add(new THREE.LineSegments(eg, new THREE.LineBasicMaterial({ color: 0x222428 })));
  g.computeBoundingSphere();
  const s = g.boundingSphere; controls.target.copy(s.center);
  camera.position.copy(s.center).add(new THREE.Vector3(1.2, -1.6, 1.1).normalize().multiplyScalar(s.radius * 3.2));
  resize();
}
function resize() {
  const w = el.clientWidth, h = el.clientHeight; renderer.setSize(w, h); camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
window.addEventListener("resize", resize);
renderer.setAnimationLoop(() => { controls.update(); renderer.render(scene, camera); });
const data = document.getElementById("view-data");
if (data) show(JSON.parse(data.textContent));
else fetch(el.dataset.src).then((r) => r.json()).then(show)
  .catch(() => { el.textContent = "Could not load the model."; });
"""


def viewer_html(title: str, *, view: Mapping[str, Any] | None = None, src: str | None = None, caption: str = "",
                link: str | None = None) -> str:  # fmt: skip
    """A self-contained viewer page: the mesh inline (`view`, offline) or fetched from `src` (embeds)."""
    data = ""
    if view is not None:
        payload = json.dumps(view, separators=(",", ":")).replace("</", "<\\/")
        data = f'<script id="view-data" type="application/json">{payload}</script>'
    cap = html.escape(caption)
    a = f' · <a href="{html.escape(link)}" target="_blank" rel="noopener">open in PartSmith</a>' if link else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} — PartSmith</title>
<style>html,body{{margin:0;height:100%;font:13px system-ui,sans-serif;background:#f4f4f2;color:#18181b}}
#view{{position:absolute;inset:0 0 28px 0}}footer{{position:absolute;left:0;right:0;bottom:0;height:28px;line-height:28px;
padding:0 10px;background:#fff;border-top:1px solid #ddd;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
@media (prefers-color-scheme: dark){{html,body{{background:#18181b;color:#eee}}footer{{background:#111;border-color:#333}}
a{{color:#93c5fd}}}}</style>
<script type="importmap">{{"imports":{{"three":"{THREE}/build/three.module.js","three/addons/":"{THREE}/examples/jsm/"}}}}</script>
</head><body><div id="view" role="img" aria-label="3D view of {html.escape(title)}"{f' data-src="{html.escape(src)}"' if src else ""}></div>
<footer><strong>{html.escape(title)}</strong> · {cap}{a}</footer>{data}
<script type="module">{VIEWER_JS}</script></body></html>
"""


def _status_line(part: PartRecord, decision: ShipDecision) -> str:
    v = part.verification
    if v is not None and v.verified:
        err = f" · {v.max_error_mm:.2f} mm max error" if v.max_error_mm is not None else ""
        return f"Verified{err}"
    return decision.reason


def readme(part: PartRecord, values: Mapping[str, float], decision: ShipDecision, *, preset: dict[str, Any] | None,
           files: Mapping[str, str]) -> str:  # fmt: skip
    v = part.verification
    origin = part.provenance.origin.value
    lines = [
        f"# {part.title}",
        "",
        f"PartSmith part `{part.slug}` v{part.version} — {_status_line(part, decision)}.",
        f"Origin: **{origin}**"
        + (" — verified against rendered images, not a photo of a real part." if origin == "synthetic" else "."),
        "",
        "A part is a program: open `part.py` (CadQuery), change a value in `PARAMS` and rebuild. All lengths are mm.",
        "",
        "## Files",
        *[f"- `{name}` — sha256 `{sha[:16]}…`" for name, sha in files.items()],
        "",
        "## Parameters in this bundle",
        "| knob | value | range | default |",
        "|---|---|---|---|",
    ]
    for p in part.params:
        val = float(values.get(p.name, p.default))
        unit = f" {p.unit}" if p.unit else ""
        lines.append(
            f"| {p.name} ({p.label}) | {val:g}{unit} | {p.min:g}–{p.max:g} | {float(part.defaults.get(p.name, p.default)):g} |"
        )
    if preset:
        lines += ["", f"Fit preset **{preset['title']}**: +{preset['delta_mm']:g} mm on internal fits "
                      f"({', '.join(c['param'] for c in preset['changes']) or 'no fit knobs on this part'})."]  # fmt: skip
    lines += ["", "## Measured vs not measured"]
    if v is not None and v.residuals:
        lines += ["Compared with the photo by the verifier (model − measured):", "",
                  "| feature | quantity | measured | model | Δ |", "|---|---|---|---|---|"]  # fmt: skip
        for r in v.residuals:
            lines.append(f"| {r.feature_id} | {r.quantity} | {r.measured_mm:.2f} mm | {r.model_mm:.2f} mm | "
                         f"{r.delta_mm:+.2f} mm |")  # fmt: skip
        lines.append("")
        lines.append("Every other dimension comes from the program (template default or a value inferred from the "
                     "measured ones), not from a measurement.")  # fmt: skip
    else:
        lines.append("No dimension of this part was compared with a photo; every value comes from the program.")
    if v is not None and v.reasons:
        lines += ["", "Verifier notes:", *[f"- {r}" for r in v.reasons[:6]]]
    f = part.facts
    lines += ["", "## How to print"]
    if f is not None:
        lines += [
            f"- Orientation: {f.orientation}",
            f"- Supports: {'needed' if f.supports_needed else 'not needed'} ({FACT_NOTES['supports_needed']})",
            f"- Size: {f.bbox_mm[0]:.1f} × {f.bbox_mm[1]:.1f} × {f.bbox_mm[2]:.1f} mm",
            f"- Mass: {f.mass_g_pla:.1f} g PLA / {f.mass_g_petg:.1f} g PETG ({FACT_NOTES['mass']})",
            f"- Print time: ~{f.print_minutes_est:.0f} min ({FACT_NOTES['print_minutes_est']})",
        ]
    lines += [
        "- Suggested: 0.2 mm layers, 4 walls, 40 % infill (suggestions, not measurements).",
        "- Print the fit-test coupon first when the fit matters; then report tight/loose on the part page.",
        "",
        "## Licence",
        f'{part.licence} — see LICENSE. Attribute: "{part.title}" from PartSmith.',
        "",
        "Open `index.html` for a 3D view (needs internet for the viewer library).",
    ]
    return "\n".join(lines) + "\n"


def licence_text(part: PartRecord) -> str:
    url = LICENCE_URLS.get(part.licence, "")
    return (
        f"{part.title} ({part.slug}) — PartSmith registry part.\n\n"
        f"Licensed under {part.licence}{f' ({url})' if url else ''}.\n"
        "You may share and adapt it for any purpose, including commercially, as long as you give appropriate credit, "
        "link to the licence and indicate if changes were made.\n"
    )


def build_bundle(part: PartRecord, values: Mapping[str, float], decision: ShipDecision, *,
                 preset: dict[str, Any] | None = None) -> bytes:  # fmt: skip
    """The zip bytes. Bakes (or reuses from the cache) py, step, stl, 3mf and view at `values`."""
    out = P.bake_output(part, values, ["py", "step", "stl", "3mf", "view"])
    files: dict[str, bytes] = {}
    for fmt, name in (("py", "part.py"), ("step", "part.step"), ("stl", "part.stl"), ("3mf", "part.3mf")):
        files[name] = out.files[fmt].read_bytes()
    view = json.loads(out.files["view"].read_text())
    files["index.html"] = viewer_html(part.title, view=view, caption=_status_line(part, decision)).encode()
    files["LICENSE"] = licence_text(part).encode()
    shas = {name: hashlib.sha256(data).hexdigest() for name, data in files.items()}
    ver = {
        "part": {"slug": part.slug, "version": part.version, "code_sha": part.code_sha, "params": dict(out.params),
                 "bake_cache_key": out.cache_key, "preset": preset["id"] if preset else None},
        "ship": decision.to_dict(),
        "verification": part.verification.model_dump(mode="json") if part.verification else None,
        "files_sha256": shas,
        "generated_at": time.time(),
    }  # fmt: skip
    files["verification.json"] = json.dumps(ver, indent=1).encode()
    shas["verification.json"] = hashlib.sha256(files["verification.json"]).hexdigest()
    files["README.md"] = readme(part, out.params, decision, preset=preset, files=shas).encode()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name in ("README.md", "part.py", "part.step", "part.stl", "part.3mf", "verification.json", "LICENSE",
                     "index.html"):  # fmt: skip
            z.writestr(f"{part.slug}/{name}", files[name])
    return buf.getvalue()
