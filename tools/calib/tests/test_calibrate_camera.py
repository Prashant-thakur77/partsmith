import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pytest

from services.metrology import testing as T
from tools.calib.calibrate_camera import calibrate_from_images, load_intrinsics


def _views(n: int) -> list[np.ndarray]:
    rng = np.random.default_rng(3)
    out = []
    for i in range(n):
        cam = T.camera_above(
            (105 + rng.uniform(-15, 15), 65 + rng.uniform(-10, 10)),
            height_mm=rng.uniform(230, 300),
            tilt_deg=rng.uniform(15, 35),
            azimuth_deg=i * 360.0 / n,
            roll_deg=rng.uniform(-20, 20),
            f_px=900.0,
            size=(960, 720),
        )
        out.append(T.render_part_scene("screen-m", cam, None).image)
    return out


def test_calibration_recovers_focal(tmp_path: Path) -> None:
    cal = calibrate_from_images(_views(12))
    assert cal.n_images == 12 and cal.mat_ids == ["screen-m"]
    assert cal.K[0][0] == pytest.approx(900.0, rel=0.015)
    assert cal.K[0][2] == pytest.approx(479.5, abs=8) and cal.K[1][2] == pytest.approx(359.5, abs=8)
    assert cal.rms_px < 0.3
    p = tmp_path / "cal.json"
    p.write_text(json.dumps(asdict(cal)))
    K, dist = load_intrinsics(p)
    assert K.shape == (3, 3) and dist.size == 5


def test_too_few_views() -> None:
    with pytest.raises(ValueError, match="at least 10"):
        calibrate_from_images(_views(3))
