"""Per-run audit directory: every prompt, response, diff and check result is preserved."""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from .config import S


class Run:
    def __init__(self, task: str, repo: str):
        self.id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        self.dir = Path(S.runs_dir) / self.id
        self.dir.mkdir(parents=True, exist_ok=True)
        self._n = 0
        self.meta = {"id": self.id, "task": task, "repo": repo, "status": "running"}
        self.save_meta()

    def log(self, name: str, content: str) -> None:
        self._n += 1
        (self.dir / f"{self._n:02d}-{name}").write_text(content, encoding="utf-8")

    def event(self, kind: str, **data) -> None:
        with (self.dir / "events.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"t": time.time(), "kind": kind, **data}) + "\n")

    def save_meta(self, **updates) -> None:
        self.meta.update(updates)
        (self.dir / "run.json").write_text(json.dumps(self.meta, indent=2), encoding="utf-8")
