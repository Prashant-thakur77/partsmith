"""Load versioned prompt files from `services/agent/prompts/<id>.v<N>.md` (front matter + `# developer` / `# user` sections).

Placeholders are `{name}` and are substituted literally (JSON braces in the prompt text are left alone).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


@dataclass(frozen=True)
class Prompt:
    id: str
    version: int
    developer: str
    user: str

    @property
    def tag(self) -> str:
        return f"{self.id}.v{self.version}"

    def render(self, **values: object) -> tuple[str, str]:
        return _fill(self.developer, values), _fill(self.user, values)


def _fill(text: str, values: dict[str, object]) -> str:
    for key, val in values.items():
        text = text.replace("{" + key + "}", str(val))
    return text


@cache
def load(prompt_id: str, version: int | None = None) -> Prompt:
    """Load a prompt; the highest version wins when `version` is None."""
    files = sorted(PROMPTS_DIR.glob(f"{prompt_id}.v*.md"), key=lambda p: int(p.stem.rsplit(".v", 1)[1]))
    if version is not None:
        files = [p for p in files if p.stem.endswith(f".v{version}")]
    if not files:
        raise FileNotFoundError(f"no prompt {prompt_id!r} (version {version}) in {PROMPTS_DIR}")
    path = files[-1]
    body = re.sub(r"\A---\n.*?\n---\n", "", path.read_text(encoding="utf-8"), flags=re.S)
    parts = re.split(r"^# (developer|user)\s*$", body, flags=re.M)
    sections = {parts[i]: parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}
    return Prompt(prompt_id, int(path.stem.rsplit(".v", 1)[1]), sections.get("developer", ""), sections.get("user", ""))
