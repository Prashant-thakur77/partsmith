"""Static checks of the deploy files, without Docker, Modal or the network (`make deploy-check`).

- the Dockerfile copies only paths that exist and that its allow-list `.dockerignore` lets into the build context;
  secrets, runtime data and private notes stay out;
- the image and the Modal app ship the same directories and default to a no-spend provider mode;
- the env templates name every variable the API and the web app read, carry no secret values, and the public
  defaults are replay/mock with an admin token required;
- the judge path's data is present: committed replays and the lying-model evidence (overlays within size).

    uv run python infra/deploy/check.py
"""

from __future__ import annotations

import ast
import fnmatch
import json
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEPLOY = REPO / "infra" / "deploy"
FILES = ("Dockerfile", "Dockerfile.dockerignore", "entrypoint.sh", "api.env.example", "web.env.example",
         "modal_app.py", "README.md")  # fmt: skip
REQUIRED_API = ("PARTSMITH_ADMIN_TOKEN", "PROVIDER_MODE", "PARTSMITH_CORS_ORIGINS", "PARTSMITH_PUBLIC_URL",
                "PARTSMITH_WEB_URL", "PARTSMITH_MCP_ALLOWED_HOSTS", "PARTSMITH_HOME")  # fmt: skip
REQUIRED_WEB = ("NEXT_PUBLIC_API_URL", "NEXT_PUBLIC_SITE_URL")
NO_SPEND_MODES = ("replay", "mock")
SECRET_RE = re.compile(r"(_KEY|_TOKEN|_SECRET|PASSWORD|DATABASE_URL)$")
NEVER_IN_IMAGE = (".env", "var/blobs/x", "PLAN.md", "KICKOFF_PROMPT.md", "docs/REUSE_LOG.md", "apps/web/package.json",
                  "data/real/part/top.jpg", "node_modules/x", ".venv/bin/python")  # fmt: skip
MAX_OVERLAY_BYTES = 150_000


def parse_env(path: Path) -> dict[str, str]:
    """KEY=value lines of an env template (comments and blanks skipped)."""
    out: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def dockerfile_copies(text: str) -> list[str]:
    """Sources of COPY instructions that read the build context (multi-stage `--from=` copies are skipped)."""
    srcs: list[str] = []
    for line in text.replace("\\\n", " ").splitlines():
        parts = line.split()
        if not parts or parts[0].upper() != "COPY" or any(p.startswith("--from") for p in parts):
            continue
        args = [p for p in parts[1:] if not p.startswith("--")]
        srcs += args[:-1]
    return srcs


def dockerfile_env(text: str) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in text.replace("\\\n", " ").splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and parts[0].upper() == "ENV":
            for k, v in re.findall(r"([A-Z_][A-Z0-9_]*)=(\S+)", parts[1]):
                env[k] = v
    return env


def in_context(rel: str, patterns: list[str]) -> bool:
    """Docker's .dockerignore rule for one path: the last matching pattern wins; `!` re-includes. A pattern matches
    the path itself or any of its parent directories."""
    included = True
    parents = [rel] + [str(Path(*Path(rel).parts[:i])) for i in range(1, len(Path(rel).parts))]
    for pat in patterns:
        neg = pat.startswith("!")
        p = pat[1:] if neg else pat
        p = p.rstrip("/")
        # fnmatch's `*` also crosses `/`, so `**/name` matches at any depth; `p[3:]` covers the top level
        hit = any(fnmatch.fnmatch(x, p) or (p.startswith("**/") and fnmatch.fnmatch(x, p[3:])) for x in parents)
        if hit:
            included = neg
    return included


def ignore_patterns(path: Path) -> list[str]:
    return [ln.strip() for ln in path.read_text().splitlines() if ln.strip() and not ln.strip().startswith("#")]


def env_read_by(root: Path, globs: tuple[str, ...], pattern: re.Pattern[str]) -> set[str]:
    names: set[str] = set()
    for g in globs:
        for f in root.glob(g):
            if "/tests/" in f.as_posix() or "node_modules" in f.parts:
                continue
            names |= set(pattern.findall(f.read_text(errors="ignore")))
    return names


PY_ENV = re.compile(r"(?:os\.environ\.get|os\.getenv|\benv)\(\s*\"([A-Z][A-Z0-9_]+)\"")
WEB_ENV = re.compile(r"process\.env\.(NEXT_PUBLIC_[A-Z0-9_]+)")


def modal_sources(path: Path) -> tuple[set[str], dict[str, str]]:
    tree = ast.parse(path.read_text())
    sources: set[str] = set()
    env: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "SOURCES" for t in node.targets):
            sources = {str(e.value) for e in getattr(node.value, "elts", []) if isinstance(e, ast.Constant)}
        is_env = isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "ENV" for t in node.targets)
        if is_env and isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
            for k, v in zip(node.value.keys, node.value.values, strict=True):
                if isinstance(k, ast.Constant) and isinstance(v, ast.Constant):
                    env[str(k.value)] = str(v.value)
    return sources, env


def run_checks(repo: Path = REPO) -> list[tuple[str, str | None]]:
    """[(check, problem or None)]."""
    deploy = repo / "infra" / "deploy"
    res: list[tuple[str, str | None]] = []

    def check(name: str, problem: str | None) -> None:
        res.append((name, problem))

    missing = [f for f in FILES if not (deploy / f).is_file()]
    check("deploy files present", f"missing: {', '.join(missing)}" if missing else None)
    if missing:
        return res

    docker = (deploy / "Dockerfile").read_text()
    pats = ignore_patterns(deploy / "Dockerfile.dockerignore")
    copies = dockerfile_copies(docker)
    absent = [s for s in copies if not (repo / s).exists()]
    check("Dockerfile COPY sources exist", f"not in the repo: {absent}" if absent else None)
    blocked = [s for s in copies if not in_context(s, pats)]
    check(
        "COPY sources allowed by Dockerfile.dockerignore", f"excluded from the context: {blocked}" if blocked else None
    )
    leaked = [p for p in NEVER_IN_IMAGE if in_context(p, pats)]
    check("secrets, runtime data, private notes stay out of the image", f"would be sent: {leaked}" if leaked else None)
    denv = dockerfile_env(docker)
    check("image defaults to a no-spend provider mode",
          None if denv.get("PROVIDER_MODE") in NO_SPEND_MODES else f"PROVIDER_MODE={denv.get('PROVIDER_MODE')!r}")  # fmt: skip
    check(
        "image keeps runtime data under PARTSMITH_HOME", None if denv.get("PARTSMITH_HOME") else "PARTSMITH_HOME unset"
    )
    baked = [k for k, v in denv.items() if SECRET_RE.search(k) and v]
    check("no secret baked into the image", f"ENV with values: {baked}" if baked else None)

    entry = deploy / "entrypoint.sh"
    etext = entry.read_text()
    ok = etext.startswith("#!") and os.access(entry, os.X_OK) and "PARTSMITH_ADMIN_TOKEN" in etext
    check("entrypoint is executable and refuses an empty admin token", None if ok else "check entrypoint.sh")
    check("entrypoint path is copied into the image", None if "infra/deploy/entrypoint.sh" in copies else "not copied")

    api_env = parse_env(deploy / "api.env.example")
    miss = [k for k in REQUIRED_API if k not in api_env]
    check("api.env.example has the required variables", f"missing: {miss}" if miss else None)
    mode = api_env.get("PROVIDER_MODE")
    check("api.env.example defaults to replay/mock", None if mode in NO_SPEND_MODES else f"PROVIDER_MODE={mode!r}")
    filled = [k for k, v in api_env.items() if SECRET_RE.search(k) and v]
    check("api.env.example carries no secret values", f"filled in: {filled}" if filled else None)
    read = env_read_by(repo / "services", ("**/*.py",), PY_ENV)
    undocumented = sorted(read - set(api_env))
    check("every variable the API reads is in api.env.example",
          f"undocumented: {undocumented}" if undocumented else None)  # fmt: skip

    web_env = parse_env(deploy / "web.env.example")
    miss = [k for k in REQUIRED_WEB if k not in web_env]
    check("web.env.example has the required variables", f"missing: {miss}" if miss else None)
    used = env_read_by(repo / "apps" / "web", ("src/**/*.ts", "src/**/*.tsx", "next.config.ts"), WEB_ENV)
    undocumented = sorted(used - set(web_env))
    check("every NEXT_PUBLIC_ variable the web reads is in web.env.example",
          f"undocumented: {undocumented}" if undocumented else None)  # fmt: skip
    nc = (repo / "apps" / "web" / "next.config.ts").read_text()
    check("web proxies /api/v1 to NEXT_PUBLIC_API_URL", None if "NEXT_PUBLIC_API_URL" in nc else "next.config.ts")

    msrc, menv = modal_sources(deploy / "modal_app.py")
    dsrc = {s.rstrip("/") for s in copies if (repo / s).is_dir()}  # the data/code trees, not the lockfiles
    diff = sorted(msrc ^ dsrc)
    check("Modal app ships the same directories as the image", f"differ: {diff}" if diff else None)
    absent = [s for s in msrc if not (repo / s).exists()]
    check("Modal app sources exist", f"missing: {absent}" if absent else None)
    m = menv.get("PROVIDER_MODE")
    check("Modal app defaults to a no-spend provider mode", None if m in NO_SPEND_MODES else f"PROVIDER_MODE={m!r}")

    replays = [d for d in (repo / "data" / "replays").glob("*/run.jsonl")]
    check("committed replays present for the public judge path", None if replays else "data/replays has no runs")
    bypass = repo / "eval" / "reports" / "latest" / "bypass.json"
    problem: str | None = None
    if not bypass.is_file():
        problem = "eval/reports/latest/bypass.json missing (uv run python -m eval.bypass)"
    else:
        caught = json.loads(bypass.read_text()).get("caught") or []
        if not caught:
            problem = "bypass.json has no caught-lie records (uv run python -m eval.bypass)"
        for c in caught:
            f = repo / "eval" / "reports" / str(c.get("overlay") or "")
            if not f.is_file() or f.stat().st_size > MAX_OVERLAY_BYTES:
                problem = f"overlay {c.get('overlay')!r} missing or over {MAX_OVERLAY_BYTES} bytes"
    check("lying-model evidence for /judges present", problem)
    return res


def main() -> int:
    rows = run_checks()
    for name, problem in rows:
        print(f"{'ok ' if problem is None else 'FAIL'}  {name}" + (f": {problem}" if problem else ""))
    bad = sum(p is not None for _, p in rows)
    print(f"{len(rows) - bad}/{len(rows)} deploy checks passed (static: no image was built, nothing was deployed)")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
