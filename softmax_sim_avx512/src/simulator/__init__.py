"""ISA-neutral simulator facade with lazily selected execution backends."""

from __future__ import annotations

from typing import Any


__all__ = ["Profile", "SimulationResult", "load_profile", "simulate"]


def __getattr__(name: str) -> Any:
    if name in {"Profile", "load_profile"}:
        from .profile import Profile, load_profile

        return {"Profile": Profile, "load_profile": load_profile}[name]
    if name in {"SimulationResult", "simulate"}:
        from .engine import SimulationResult, simulate

        return {"SimulationResult": SimulationResult, "simulate": simulate}[name]
    raise AttributeError(name)
