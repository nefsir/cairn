"""Per-invocation context handed to every command handler: the resolved config plus
the in-process lib seam (built once, module cache shared across a command's lib calls).
"""
from __future__ import annotations

from dataclasses import dataclass

from .config import Config
from .libseam import LibRunner


@dataclass(frozen=True)
class Context:
    cfg: Config
    lib: LibRunner

    @classmethod
    def build(cls, cfg: Config) -> "Context":
        return cls(cfg=cfg, lib=LibRunner(cfg.lib))
