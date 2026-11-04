"""Stage-level parts of the scale evaluation (eval/SCALE_PLAN.md): SAM 3.1 masks, Muse Wonder citations, voice edits.

    uv run python -m eval.scale_stages sam|wonder|voice
    python eval/scale_stages.py voice-audio     # in an environment with chatterbox: synthesised speech for the voice lines

Results go to eval/runs/live_scale/stages/<stage>.json. Voice audio is synthesised speech and is labelled so everywhere.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
ROOT = REPO / "var" / "scale_data"
STAGES = REPO / "eval" / "runs" / "live_scale" / "stages"
SEED = 20261105
N_SAM = 500

# line, knob, how the value changes ("+" adds to the current value, "=" sets it), millimetres, language
VOICE_LINES: list[tuple[str, str, str, float, str]] = [
    ("Make the cover one millimetre longer.", "length", "+", 1.0, "english"),
    ("Make the cover two millimetres shorter.", "length", "+", -2.0, "english"),
    ("Set the overall length to fifty millimetres.", "length", "=", 50.0, "english"),
    ("Make it one millimetre wider.", "width", "+", 1.0, "english"),
    ("Reduce the width by two millimetres.", "width", "+", -2.0, "english"),
    ("Set the width to thirty two millimetres.", "width", "=", 32.0, "english"),
    ("Make the door two millimetres thick.", "thickness", "=", 2.0, "english"),
    ("Increase the door thickness by half a millimetre.", "thickness", "+", 0.5, "english"),
    ("Make the corner radius three millimetres.", "corner_radius", "=", 3.0, "english"),
    ("Increase the corner radius by one millimetre.", "corner_radius", "+", 1.0, "english"),
    ("Make the latch two millimetres wider.", "latch_width", "+", 2.0, "english"),
    ("Set the latch height to four millimetres.", "latch_height", "=", 4.0, "english"),
    ("Make the tongue one millimetre longer.", "tongue_length", "+", 1.0, "english"),
    ("Set the tongue width to six millimetres.", "tongue_width", "=", 6.0, "english"),
    ("Cover ko ek millimeter lamba karo.", "length", "+", 1.0, "hindi"),
    ("Cover ko do millimeter chhota karo.", "length", "+", -2.0, "hindi"),
    ("Lambai pachaas millimeter kar do.", "length", "=", 50.0, "hindi"),
    ("Chaudai ek millimeter badha do.", "width", "+", 1.0, "hindi"),
    ("Chaudai do millimeter kam karo.", "width", "+", -2.0, "hindi"),
    ("Motai do millimeter kar do.", "thickness", "=", 2.0, "hindi"),
    ("Motai aadha millimeter badha do.", "thickness", "+", 0.5, "hindi"),
    ("Kone ki golai teen millimeter kar do.", "corner_radius", "=", 3.0, "hindi"),
    ("Latch ko do millimeter chauda karo.", "latch_width", "+", 2.0, "hindi"),
    ("Latch ki unchai chaar millimeter kar do.", "latch_height", "=", 4.0, "hindi"),
    ("Tongue ko ek millimeter lamba karo.", "tongue_length", "+", 1.0, "hindi"),
    ("Tongue ki chaudai chhe millimeter kar do.", "tongue_width", "=", 6.0, "hindi"),
    ("Length ko one millimeter badha do.", "length", "+", 1.0, "mixed"),
    ("Length ko two millimeter reduce karo.", "length", "+", -2.0, "mixed"),
    ("Overall length fifty millimeter set kar do.", "length", "=", 50.0, "mixed"),
    ("Width ko one millimeter increase karo.", "width", "+", 1.0, "mixed"),
    ("Width thoda kam karo, two millimeter.", "width", "+", -2.0, "mixed"),
    ("Thickness two millimeter kar do.", "thickness", "=", 2.0, "mixed"),
    ("Door thickness half millimeter badha do.", "thickness", "+", 0.5, "mixed"),
    ("Corner radius three millimeter kar do.", "corner_radius", "=", 3.0, "mixed"),
    ("Corner radius ko one millimeter badhao.", "corner_radius", "+", 1.0, "mixed"),
    ("Latch width two millimeter badha do.", "latch_width", "+", 2.0, "mixed"),
    ("Latch height four millimeter set karo.", "latch_height", "=", 4.0, "mixed"),
    ("Tongue length one millimeter increase kar do.", "tongue_length", "+", 1.0, "mixed"),
    ("Tongue width six millimeter kar do.", "tongue_width", "=", 6.0, "mixed"),
    ("Hinge tongue ki length four millimeter karo.", "tongue_length", "=", 4.0, "mixed"),
]

# query words, wanted dimensions
WONDER_PARTS: list[tuple[str, list[str]]] = [
    ("LEGO 3001 2x4 brick", ["length", "width"]),
    ("ISO 7010 M3 flat washer", ["outer_diameter", "thickness"]),
    ("DIN 125 M4 washer", ["outer_diameter", "thickness"]),
    ("608 ball bearing", ["outer_diameter", "width"]),
    ("625 ball bearing", ["outer_diameter", "width"]),
    ("Raspberry Pi 4 Model B board", ["length", "width"]),
    ("Raspberry Pi Zero 2 W board", ["length", "width"]),
    ("Arduino Uno R3 board", ["length", "width"]),
    ("NEMA 17 stepper motor", ["face_width", "shaft_diameter"]),
    ("GT2 20 tooth pulley", ["bore_diameter", "outer_diameter"]),
    ("CR2032 coin cell", ["diameter", "thickness"]),
    ("AA alkaline battery", ["diameter", "length"]),
    ("AAA alkaline battery", ["diameter", "length"]),
    ("9V PP3 battery", ["length", "width"]),
    ("standard SD memory card", ["length", "width"]),
    ("microSD memory card", ["length", "width"]),
    ("USB Type-A plug", ["width", "height"]),
    ("USB Type-C receptacle", ["width", "height"]),
    ("ID-1 ISO 7810 card", ["length", "width"]),
    ("Euro pallet EPAL 1", ["length", "width"]),
    ("Philips PH2 screwdriver bit hex shank", ["hex_size", "length"]),
    ("M3 socket head cap screw ISO 4762", ["head_diameter", "head_height"]),
    ("M4 hex nut DIN 934", ["width_across_flats", "thickness"]),
    ("Sony RMT-TX300 remote control battery cover", ["length", "width"]),
    ("Samsung BN59-01315 remote control battery cover", ["length", "width"]),
    ("Bajaj Rex 500 mixer grinder jar coupler", ["diameter", "height"]),
    ("Prestige pressure cooker gasket 3 litre", ["inner_diameter", "thickness"]),
    ("Symphony Diet 12T air cooler caster wheel", ["diameter", "width"]),
    ("IKEA KALLAX shelf insert", ["width", "height"]),
    ("Usha Striker ceiling fan regulator knob", ["diameter", "height"]),
]


def _usd(stage: str, value: float) -> None:
    STAGES.mkdir(parents=True, exist_ok=True)
    path = STAGES / "usd.json"
    data = json.loads(path.read_text()) if path.exists() else {}
    data[stage] = round(value, 6)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data))
    tmp.replace(path)


def boundary_mm(pred: Any, truth: Any, px_per_mm: float) -> dict[str, float | None]:
    """Symmetric distance between two mask outlines in millimetres: mean and 95th percentile."""
    import cv2
    import numpy as np

    def edge(m: Any) -> Any:
        u = m.astype(np.uint8)
        return (u - cv2.erode(u, np.ones((3, 3), np.uint8))).astype(bool)

    ep, et = edge(pred), edge(truth)
    if not ep.any() or not et.any():
        return {"mean_mm": None, "p95_mm": None}
    dist_t = cv2.distanceTransform((~et).astype(np.uint8), cv2.DIST_L2, 5)
    dist_p = cv2.distanceTransform((~ep).astype(np.uint8), cv2.DIST_L2, 5)
    all_d = np.concatenate([dist_t[ep], dist_p[et]]) / px_per_mm
    return {"mean_mm": round(float(all_d.mean()), 4), "p95_mm": round(float(np.percentile(all_d, 95)), 4)}


def sam_one(row: dict[str, Any]) -> dict[str, Any]:
    import cv2
    import yaml

    from services.agent import providers
    from services.agent.providers import pricing
    from services.metrology.segment import ProviderSegmenter, mask_iou

    d = ROOT / row["suite"] / row["id"]
    calls = [0]

    def call(png: bytes, prompt: str) -> Any:
        calls[0] += 1
        return providers.segment(png, prompt)

    out: dict[str, Any] = {
        "id": row["id"],
        "suite": row["suite"],
        "preset": row.get("preset"),
        "template": row.get("template"),
    }
    try:
        gray: Any = cv2.imread(str(ROOT / "masks" / row["suite"] / f"{row['id']}.png"), cv2.IMREAD_GRAYSCALE)
        bgr: Any = cv2.imread(str(d / "top.jpg"))
        truth = gray >= 128
        img: Any = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        cam = (yaml.safe_load((d / "gt.yaml").read_text()) or {})["views"]["top"]["camera"]
        px_per_mm = float(cam["K"][0][0]) / float(cam["height_mm"])
        res = ProviderSegmenter(call=call, fallback=None).segment(img, "plastic part")
        out.update(
            iou=round(float(mask_iou(res.mask, truth)), 5),
            px_per_mm=round(px_per_mm, 3),
            source=res.source,
            **boundary_mm(res.mask, truth, px_per_mm),
        )
    except Exception as exc:  # a failure is a result of this stage
        out.update(iou=None, error=f"{type(exc).__name__}: {exc}"[:200])
    out["calls"] = calls[0]
    out["usd"] = pricing.segment_cost_usd("meta", calls[0])
    return out


def run_sam() -> int:
    import random

    man = json.loads((ROOT / "manifest.json").read_text())
    rows = [
        r
        for r in man["samples"]
        if not r.get("error") and r["suite"] in ("synthetic", "extra", "reference_objects", "broken", "control_top")
    ]
    random.Random(SEED + 2).shuffle(rows)
    rows = rows[:N_SAM]
    results: list[dict[str, Any]] = []
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=8) as ex:
        for r in ex.map(sam_one, rows):
            results.append(r)
            if len(results) % 25 == 0:
                _usd("sam", sum(x["usd"] for x in results))
                print(
                    f"sam {len(results)}/{len(rows)} ${sum(x['usd'] for x in results):.2f} {time.time() - t0:.0f}s",
                    flush=True,
                )
    _usd("sam", sum(x["usd"] for x in results))
    STAGES.mkdir(parents=True, exist_ok=True)
    (STAGES / "sam.json").write_text(
        json.dumps(
            {"prompt": "plastic part", "path": "ProviderSegmenter, no threshold fallback", "rows": results}, indent=0
        )
    )
    return 0


def page_has(url: str, value: float) -> bool | None:
    """Whether the number appears on the cited page's text; None when the page cannot be read by a script."""
    import httpx

    try:
        r = httpx.get(url, timeout=20, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 PartSmith-bench"})
    except Exception:
        return None
    if r.status_code != 200 or "text" not in r.headers.get("content-type", ""):
        return None
    forms = {f"{value:g}", f"{value:.1f}", f"{value:.2f}"}
    return any(re.search(rf"(?<![\d.]){re.escape(f)}(?![\d])", r.text) for f in forms)


def run_wonder() -> int:
    from services.agent.providers.spec import lookup_spec

    def one(item: tuple[str, list[str]]) -> dict[str, Any]:
        name, want = item
        try:
            r = lookup_spec(f"{name} dimensions in millimetres", want)
            return {"part": name, "want": want, **r.to_dict(), "usd": r.usd}
        except Exception as exc:
            return {"part": name, "want": want, "error": f"{type(exc).__name__}: {exc}"[:300], "usd": 0.0, "values": []}

    with ThreadPoolExecutor(max_workers=4) as ex:
        rows = list(ex.map(one, WONDER_PARTS))
    checked: list[dict[str, Any]] = []
    for r in rows:
        for v in (r.get("values") or [])[:1]:
            url = (v.get("citation") or {}).get("url") or v.get("url")
            if url and len(checked) < 12:
                checked.append(
                    {
                        "part": r["part"],
                        "name": v.get("name"),
                        "value_mm": v.get("value_mm"),
                        "url": url,
                        "number_on_page": page_has(url, float(v.get("value_mm"))),
                    }
                )
    _usd("wonder", sum(float(r.get("usd") or 0) for r in rows))
    STAGES.mkdir(parents=True, exist_ok=True)
    (STAGES / "wonder.json").write_text(
        json.dumps(
            {"rows": rows, "page_check": checked, "note": "a citation is not a verified fact"}, indent=0, default=str
        )
    )
    print(f"wonder accepted {sum(bool(r.get('values')) for r in rows)}/{len(rows)}")
    return 0


def expected_value(line: tuple[str, str, str, float, str], values: dict[str, float]) -> float:
    _, knob, how, mm, _ = line
    return values[knob] + mm if how == "+" else mm


def score_edit(res: Any, line: tuple[str, str, str, float, str], values: dict[str, float]) -> dict[str, Any]:
    want = expected_value(line, values)
    edits = [{"param": e.param, "to": e.to} for e in res.edits]
    right = len(edits) == 1 and edits[0]["param"] == line[1] and round(abs(float(edits[0]["to"]) - want), 6) <= 0.01
    return {
        "transcript": res.transcript,
        "edits": edits,
        "expected": {"param": line[1], "to": round(want, 3)},
        "right": right,
        "not_understood": res.not_understood,
    }


def run_voice() -> int:
    from partsmith_schemas.verification import ParamSpec

    from services.geom_worker.program import parse_params
    from services.media.voice import transcribe_and_map

    code = (REPO / "data" / "replays" / "j_261029_daf26965" / "part.py").read_text()
    specs: list[ParamSpec] = parse_params(code)
    values = {p.name: float(p.default) for p in specs}
    audio_dir = ROOT / "voice"

    def one(item: tuple[int, tuple[str, str, str, float, str]]) -> dict[str, Any]:
        i, line = item
        row: dict[str, Any] = {"i": i, "line": line[0], "language": line[4], "speech": "synthesised"}
        try:
            row["typed"] = score_edit(
                transcribe_and_map(line[0], specs, values, part_title="Battery compartment cover"), line, values
            )
        except Exception as exc:
            row["typed"] = {"right": False, "error": f"{type(exc).__name__}: {exc}"[:200]}
        path = audio_dir / f"{i:02d}.wav"
        if path.exists():
            try:
                row["spoken"] = score_edit(
                    transcribe_and_map(path.read_bytes(), specs, values, part_title="Battery compartment cover"),
                    line,
                    values,
                )
            except Exception as exc:
                row["spoken"] = {"right": False, "error": f"{type(exc).__name__}: {exc}"[:200]}
        else:
            row["spoken"] = None
        return row

    with ThreadPoolExecutor(max_workers=4) as ex:
        rows = list(ex.map(one, enumerate(VOICE_LINES)))
    _usd(
        "voice", 0.02 * len(VOICE_LINES)
    )  # an upper estimate of transcription plus two mapping calls per line; exact cost is in the bench home's spend log
    STAGES.mkdir(parents=True, exist_ok=True)
    (STAGES / "voice.json").write_text(
        json.dumps({"speech": "synthesised speech from two narrator voices, not people", "rows": rows}, indent=0)
    )
    return 0


def voice_audio() -> int:
    """Synthesised speech for each voice line, alternating the two narrator voices."""
    import soundfile as sf
    import torch
    from chatterbox.tts import ChatterboxTTS

    torch.set_num_threads(3)
    out = ROOT / "voice"
    out.mkdir(parents=True, exist_ok=True)
    model = ChatterboxTTS.from_pretrained(device="cuda" if torch.cuda.is_available() else "cpu")
    for i, line in enumerate(VOICE_LINES):
        path = out / f"{i:02d}.wav"
        if path.exists():
            continue
        ref = REPO / "video" / "refs" / ("male.wav" if i % 2 == 0 else "female.wav")
        torch.manual_seed(SEED + i)
        wav = model.generate(line[0], audio_prompt_path=str(ref), exaggeration=0.6, cfg_weight=0.4, temperature=0.7)
        sf.write(str(path), wav.squeeze(0).numpy(), model.sr)
        print(f"voice {i + 1}/{len(VOICE_LINES)}", flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("stage", choices=("sam", "wonder", "voice", "voice-audio"))
    a = ap.parse_args()
    return {"sam": run_sam, "wonder": run_wonder, "voice": run_voice, "voice-audio": voice_audio}[a.stage]()


if __name__ == "__main__":
    sys.exit(main())
