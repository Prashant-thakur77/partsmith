from __future__ import annotations

import io

import numpy as np
from PIL import Image

from services.registry import thumbs


def _box_view(lx: float = 40.0, ly: float = 20.0, lz: float = 6.0) -> dict[str, object]:
    """view.json of an axis-aligned box: 12 triangles (flat normals) + its 12 edges."""
    c = np.array([[x, y, z] for x in (0, lx) for y in (0, ly) for z in (0, lz)], float)
    quads = [
        (0, 1, 3, 2, (-1, 0, 0)),
        (4, 6, 7, 5, (1, 0, 0)),
        (0, 4, 5, 1, (0, -1, 0)),
        (2, 3, 7, 6, (0, 1, 0)),
        (0, 2, 6, 4, (0, 0, -1)),
        (1, 5, 7, 3, (0, 0, 1)),
    ]
    pos: list[float] = []
    nrm: list[float] = []
    idx: list[int] = []
    for a, b, cc, d, n in quads:
        base = len(pos) // 3
        for k in (a, b, cc, d):
            pos += list(c[k])
            nrm += list(n)
        idx += [base, base + 1, base + 2, base, base + 2, base + 3]
    edges = []
    for i in range(8):
        for j in range(i + 1, 8):
            if np.count_nonzero(c[i] != c[j]) == 1:
                edges.append(list(c[i]) + list(c[j]))
    return {"mesh": {"positions": pos, "normals": nrm, "indices": idx}, "edges": edges}


def test_render_pair_sizes_transparency_and_centring() -> None:
    one, two = thumbs.render_pair(_box_view())
    a = np.asarray(Image.open(io.BytesIO(one)))
    b = np.asarray(Image.open(io.BytesIO(two)))
    assert a.shape == (480, 640, 4) and b.shape == (960, 1280, 4)
    alpha = a[..., 3]
    assert alpha[0, 0] == 0 and alpha[-1, -1] == 0  # transparent background
    ys, xs = np.nonzero(alpha > 0)
    # consistent padding: the part fills the frame up to the margin on the limiting axis
    pad_x = (xs.min(), 639 - xs.max())
    pad_y = (ys.min(), 479 - ys.max())
    assert min(min(pad_x) / 640, min(pad_y) / 480) > 0.07
    assert abs(pad_x[0] - pad_x[1]) <= 3 and abs(pad_y[0] - pad_y[1]) <= 3  # centred
    # shaded grey (not flat) with dark edge pixels present
    rgb = a[alpha == 255][:, :3].astype(int)
    assert rgb.max() > 120 and rgb.min() < 60
    assert np.ptp(rgb[:, 0]) > 30


def test_store_pair_puts_png_blobs() -> None:
    from services.common import blobs

    k1, k2 = thumbs.store_pair(_box_view())
    assert k1.endswith(".png") and k2.endswith(".png") and k1 != k2
    assert blobs.get(k1)[:8] == b"\x89PNG\r\n\x1a\n"
