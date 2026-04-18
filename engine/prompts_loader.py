"""
Prompt file loader. Stages 3, 4, 8 use externalized markdown prompts so Ray
can tune them without touching code, and so each audit can record which
prompt version produced it (reproducibility).

Prompt files live under `prompts/<slug>.md`. The first line may contain a
version marker comment: `<!-- version: N -->`. If absent, version == "1".
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from shared.config import Config


_VERSION_RE = re.compile(r"<!--\s*version:\s*(\S+?)\s*-->", re.IGNORECASE)


@lru_cache(maxsize=32)
def _cached_read(path_str: str, mtime: float) -> tuple[str, str]:
    """Cache keyed on (path, mtime) — edits are picked up automatically."""
    p = Path(path_str)
    raw = p.read_text(encoding="utf-8")
    m = _VERSION_RE.search(raw.splitlines()[0] if raw else "")
    version = m.group(1) if m else "1"
    return raw, version


def load_prompt(cfg: Config, slug: str) -> tuple[str, str]:
    """Load prompt by slug (e.g. 's3_moat'). Returns (body, version)."""
    path = cfg.prompts_dir / f"{slug}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt not found: {path}")
    return _cached_read(str(path), path.stat().st_mtime)
