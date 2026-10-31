"""Small job pictures: the rectified top photo cropped to the part (list thumbnail, ≤ 240 px), and a shaded picture of
the job's model (the poster phones see before they tap "View in 3D").

Both are rendered on first request and cached under `$PARTSMITH_HOME/thumbs/jobs/`, keyed by the source blob's sha, so a
new photo or a new model (a reviewer round) gets a new file. Jobs without the source (describe-only, failed before
rectification, no model built) answer 404. Pictures only: no measurement is taken from either.
"""

from __future__ import annotations

import io

import cv2
import numpy as np
from fastapi import APIRouter
from fastapi.responses import FileResponse

from services.agent.jobs import Job
from services.api.common import _job
from services.api.errors import ApiError
from services.common import blobs
from services.common.paths import sub
from services.review.images import part_box, top_rectified_key
from services.verifier.shade import shaded_png

router = APIRouter(prefix="/api/v1", tags=["jobs"])

THUMB_PX = 240
MODEL_PX = 480


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


def model_key(job: Job) -> str | None:
    """The blob of the job's latest STL export (artifact events, newest first), or None when no model was built."""
    for e in reversed(job.events):
        if e.t == "artifact" and e.kind == "stl" and isinstance(e.sha, str) and blobs.exists(e.sha):
            return str(e.sha)
    return None


def render_model(stl: bytes, size_px: int = MODEL_PX) -> bytes:
    """PNG of the mesh in `stl`, shaded and seen from above at an angle (the same picture the judge model is shown)."""
    import trimesh

    try:
        mesh = trimesh.load(io.BytesIO(stl), file_type="stl", force="mesh")
    except Exception as exc:  # trimesh raises a variety of errors on bad input
        raise ValueError(f"not a mesh: {exc}") from exc
    if not isinstance(mesh, trimesh.Trimesh):
        raise ValueError("not a single mesh")
    out = shaded_png(np.asarray(mesh.vertices), np.asarray(mesh.faces), size_px=size_px)
    if out is None:
        raise ValueError("empty mesh")
    return out


@router.get("/jobs/{job_id}/model.png", summary="A shaded picture of the job's model (poster for the 3D view)",
            response_class=FileResponse)  # fmt: skip
def job_model_picture(job_id: str) -> FileResponse:
    job = _job(job_id)
    key = model_key(job)
    if key is None:
        raise ApiError(404, "no_model", f"job {job_id!r} has no model yet")
    out = sub("thumbs/jobs") / f"{job.id}-model-{key.split('.')[0][:16]}.png"
    if not out.exists():
        try:
            data = render_model(blobs.get(key))
        except ValueError as exc:  # an unreadable or empty mesh: no picture rather than a broken one
            raise ApiError(404, "no_model", f"job {job_id!r}: the model could not be drawn") from exc
        tmp = out.with_suffix(".tmp")
        tmp.write_bytes(data)
        tmp.replace(out)
    return FileResponse(out, media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})
