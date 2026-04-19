"""
Wisdom quote loader + selector.

Loads prompts/wisdom.yaml and serves quotes by:
- stage (pick_for_stage)   — one quote to show at the end of a given audit stage
- trigger (pick_for_trigger) — one quote triggered by a decision state
  (e.g. action_buy + low_mos)
- theme (filter_by_theme)  — browse /wisdom library grouped by topic

Design goals:
- Deterministic per (session_seed, stage_or_trigger) so re-rendering a chat
  session always shows the same quote (reproducibility).
- No repeat within a session — `pick_for_stage(sid, seed)` excludes any quote
  already picked for earlier stages in the same seed.
- mtime-aware cache so edits to wisdom.yaml are picked up without restart.
- Tolerates partial YAML (missing fields get safe defaults).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

from shared.config import Config


WISDOM_FILENAME = "wisdom.yaml"


@dataclass
class Quote:
    id: str
    author: str = ""
    text_en: str = ""
    text_cn: str = ""
    source: str = ""
    themes: list[str] = field(default_factory=list)
    stages: list[int] = field(default_factory=list)
    triggers: list[str] = field(default_factory=list)
    ray_note: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id, "author": self.author,
            "text_en": self.text_en, "text_cn": self.text_cn,
            "source": self.source, "themes": list(self.themes),
            "stages": list(self.stages), "triggers": list(self.triggers),
            "ray_note": self.ray_note,
        }


def wisdom_path(cfg: Config) -> Path:
    return cfg.prompts_dir / WISDOM_FILENAME


@lru_cache(maxsize=4)
def _cached_parse(path_str: str, mtime: float) -> list[Quote]:
    p = Path(path_str)
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        return []
    out: list[Quote] = []
    seen_ids: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        qid = item.get("id")
        if not qid or qid in seen_ids:
            continue
        seen_ids.add(qid)
        out.append(Quote(
            id=str(qid),
            author=str(item.get("author", "")),
            text_en=str(item.get("text_en", "")),
            text_cn=str(item.get("text_cn", "")),
            source=str(item.get("source", "")),
            themes=list(item.get("themes") or []),
            stages=[int(x) for x in (item.get("stages") or []) if isinstance(x, (int, str))],
            triggers=list(item.get("triggers") or []),
            ray_note=str(item.get("ray_note", "")),
        ))
    return out


def load_wisdom(cfg: Config) -> list[Quote]:
    p = wisdom_path(cfg)
    if not p.exists():
        return []
    return _cached_parse(str(p), p.stat().st_mtime)


def _stable_pick(items: list[Quote], seed: str) -> Quote | None:
    """Deterministic pick — same seed always returns same index."""
    if not items:
        return None
    h = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    idx = int(h, 16) % len(items)
    return items[idx]


def pick_for_stage(
    cfg: Config, stage_id: int, session_seed: str,
    exclude_ids: set[str] | None = None,
) -> Quote | None:
    """Pick one quote suited for a given stage. Excludes ids already used."""
    exclude_ids = exclude_ids or set()
    candidates = [
        q for q in load_wisdom(cfg)
        if stage_id in q.stages and q.id not in exclude_ids
    ]
    return _stable_pick(candidates, f"{session_seed}|stage|{stage_id}")


def pick_for_trigger(
    cfg: Config, trigger: str, session_seed: str,
    exclude_ids: set[str] | None = None,
) -> Quote | None:
    exclude_ids = exclude_ids or set()
    candidates = [
        q for q in load_wisdom(cfg)
        if trigger in q.triggers and q.id not in exclude_ids
    ]
    return _stable_pick(candidates, f"{session_seed}|trigger|{trigger}")


def filter_by_theme(cfg: Config, theme: str) -> list[Quote]:
    return [q for q in load_wisdom(cfg) if theme in q.themes]


def group_by_theme(cfg: Config) -> dict[str, list[Quote]]:
    """Build {theme: [quotes...]} for browsing /wisdom. Quote with multiple themes appears in each bucket."""
    out: dict[str, list[Quote]] = {}
    for q in load_wisdom(cfg):
        for theme in q.themes or ["misc"]:
            out.setdefault(theme, []).append(q)
    return out


def get_quote_by_id(cfg: Config, qid: str) -> Quote | None:
    for q in load_wisdom(cfg):
        if q.id == qid:
            return q
    return None
