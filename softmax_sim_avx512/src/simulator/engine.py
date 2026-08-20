from __future__ import annotations

from typing import Any

from ..backend.common import ExecutionModel, SimulationResult, SimulatorError
from ..backend.xsai import GenericTokenEngine, XsaiRvvEngine
from ..backend.zen4 import Engine as Zen4Engine
from .memory import CacheMode
from .model import BoundTrace
from .profile import Profile


def backend_name(profile: Profile) -> str:
    """Resolve the execution backend while retaining the old profile alias."""
    configured = str(profile.backend.get("execution_model", "zen4"))
    if configured == "generic-token":
        return "generic-token"
    if configured in {"zen4", "xsai-rvv"}:
        return configured
    raise SimulatorError(f"unsupported execution backend: {configured}")


def _engine_type(
    profile: Profile,
) -> type[Zen4Engine] | type[XsaiRvvEngine] | type[GenericTokenEngine]:
    selected = backend_name(profile)
    if selected == "zen4":
        return Zen4Engine
    if selected == "xsai-rvv":
        return XsaiRvvEngine
    # Compatibility profiles used by topology tests predate the explicit
    # backend split. They retain the feature-complete XSAI-side token loop,
    # while production profiles must name zen4 or xsai-rvv explicitly.
    return GenericTokenEngine


class Engine:
    """Compatibility constructor that returns the selected concrete backend."""

    def __new__(
        cls,
        trace: BoundTrace,
        profile: Profile,
        execution_model: ExecutionModel = "out_of_order",
        cache_mode: CacheMode = "hot-l1",
        memory_compute_overlap_limit: bool | None = None,
    ) -> Any:
        return _engine_type(profile)(
            trace,
            profile,
            execution_model,
            cache_mode,
            memory_compute_overlap_limit,
        )


def simulate(
    trace: BoundTrace,
    profile: Profile,
    execution_model: ExecutionModel = "out_of_order",
    cache_mode: CacheMode = "hot-l1",
    memory_compute_overlap_limit: bool | None = None,
) -> SimulationResult:
    return Engine(
        trace,
        profile,
        execution_model,
        cache_mode,
        memory_compute_overlap_limit,
    ).run()


__all__ = [
    "Engine",
    "ExecutionModel",
    "SimulationResult",
    "SimulatorError",
    "backend_name",
    "simulate",
]
