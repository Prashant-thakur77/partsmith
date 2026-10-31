"""Small job thumbnails for lists: the rectified top photo cropped to the part (the review page's focus box), ≤ 240 px.

Rendered on first request and cached as `$PARTSMITH_HOME/thumbs/jobs/<job>-<photo sha>.jpg`, so a new photo (a reviewer
round) gets a new file. Jobs without a measured photo (describe-only, failed before rectification) answer 404.
"""

from __future__ import annotations

import cv2
import numpy as np
from fastapi import APIRouter
from fastapi.responses import FileResponse

from services.api.common import _job
from services.api.errors import ApiError
from services.common import blobs
from services.common.paths import sub
from services.review.images import part_box, top_rectified_key

router = APIRouter(prefix="/api/v1", tags=["jobs"])

THUMB_PX = 240


def render(photo: bytes, box: list[float] | None, size_px: int = THUMB_PX) -> bytes:
    """JPEG of `photo` cropped to `box` ([u0, v0, u1, v1] fractions; whole photo when None), longest side `size_px`."""
    img = cv2.imdecode(np.frombuffer(photo, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("not an image")
    h, w = img.shape[:2]
    if box:
        u0, v0, u1, v1 = box
        x0, y0, x1, y1 = int(u0 * w), int(v0 * h), max(int(u1 * w), int(u0 * w) + 1), max(int(v1 * h), int(v0 * h) + 1)
        img = img[y0:y1, x0:x1]
        h, w = img.shape[:2]
    scale = size_px / max(h, w)
    if scale < 1:
        img = cv2.resize(img, (max(1, round(w * scale)), max(1, round(h * scale))), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 82])
    if not ok:
        raise ValueError("could not encode thumbnail")
    return bytes(buf)


@router.get("/jobs/{job_id}/thumbnail.jpg", summary="The job's measured photo cropped to the part (list thumbnail)",
            response_class=FileResponse)  # fmt: skip
def job_thumbnail(job_id: str) -> FileResponse:
    job = _job(job_id)
    key = top_rectified_key(job)
    if key is None:
        raise ApiError(404, "no_photo", f"job {job_id!r} has no measured photo")
    out = sub("thumbs/jobs") / f"{job.id}-{key.split('.')[0][:16]}.jpg"
    if not out.exists():
        try:
            box = part_box(job, key, margin_mm=4.0)
        except Exception:  # an outline that cannot be projected still gets the whole photo
            box = None
        try:
            data = render(blobs.get(key), box)
        except ValueError as exc:
            raise ApiError(404, "no_photo", str(exc)) from exc
        tmp = out.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(out)
    return FileResponse(out, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=3600"})
