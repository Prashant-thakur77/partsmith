"""The story's illustrations, drawn by Muse Image through the project's own providers layer (each call logged with its cost).

    PROVIDER_MODE=live uv run python video/story_images.py [name ...]  ->  ~/Videos/partsmith/stills/story-<name>.png

An existing image is kept, so a rerun only pays for what is missing. They are drawings, and the film labels them so.
"""

from __future__ import annotations

import os
import sys

from services.agent import providers

OUT = os.path.expanduser("~/Videos/partsmith/stills")
STYLE = (
    "Wide 16:9 hand-painted gouache illustration, warm muted colours, soft lamplight, gentle film grain, quiet and dignified "
    "mood, an Indian home. Clearly a painting, not a photograph. No text, no letters, no logos anywhere in the image. "
)
SCENES = {
    "father": "A calm older Indian man in a cardigan sits on a sofa at night, in a modest living room lit by one warm lamp "
    "and the blue glow of an old television. He reaches for a TV remote on the side table. Seen from the side.",
    "band": "Close-up of an older man's weathered hands holding a plain dark grey TV remote. A red rubber band is wrapped "
    "tightly around the back of the remote, holding two AA batteries in where the battery cover is missing.",
    "snapped": "Close-up on a wooden side table at night: one small snapped grey plastic battery cover, its little latch "
    "tab broken off and lying beside it, next to two loose AA batteries. Warm lamp light, shallow depth of field.",
    "shop": "A small crowded electronics repair shop counter in an Indian market in the evening. A shopkeeper, seen from behind "
    "the counter, gently shakes his head and points at a shelf of new boxed remotes. Wires and old parts on the shelves.",
    "printer": "A small desktop 3D printer on a workbench in a tiny print shop at night, printing a small grey plastic piece. "
    "Warm light. Beside it a closed notebook. Nobody in the frame.",
    "heap": "A large sad heap of discarded remotes, mixers, fans, small appliances and plastic parts, at dusk, at the edge of "
    "a city. Muted colours, seen from low down.",
    "resolved": "The same calm older Indian man on the sofa at night, smiling slightly, pointing a plain dark grey TV remote at "
    "the glowing television. The remote is whole, with no rubber band on it. One warm lamp. Seen from the side.",
}


def main(only: set[str]) -> None:
    os.makedirs(OUT, exist_ok=True)
    total = 0.0
    for name, scene in SCENES.items():
        path = f"{OUT}/story-{name}.png"
        if (only and name not in only) or os.path.exists(path):
            continue
        res = providers.generate_image(STYLE + scene, [])
        if res.mode != "live":
            raise SystemExit(f"{name}: image stage is {res.mode}, not live; nothing written")
        open(path, "wb").write(res.data)
        total += res.usd or 0.0
        print(f"{name}: {res.model} ${res.usd} -> {path}", flush=True)
    print(f"total ${total:.3f}")


if __name__ == "__main__":
    main(set(sys.argv[1:]))
