"""Stable, small-grained contracts for in-repository secondary development."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

BACKEND_EXTENSION_API_VERSION = 1


class RepositoryAccess(Protocol):
    """Read-oriented repository surface exposed to backend extensions."""

    def get_name_map(self, symbols: list[str] | None = None) -> dict[str, str]: ...


@dataclass(frozen=True)
class ExtensionContext:
    api_version: int
    data_dir: Path
    repository: RepositoryAccess


@dataclass(frozen=True)
class NotificationFormatContext:
    api_version: int


class NotificationFormatter(ABC):
    """Customize notification copy without changing the event schema or semantics."""

    api_version = BACKEND_EXTENSION_API_VERSION

    @abstractmethod
    def format_message(
        self,
        event: dict[str, Any],
        context: NotificationFormatContext,
    ) -> str:
        """Return notification copy. The input event must not be mutated."""
        raise NotImplementedError


class DefaultNotificationFormatter(NotificationFormatter):
    def format_message(
        self,
        event: dict[str, Any],
        context: NotificationFormatContext,
    ) -> str:
        del context
        return str(event.get("message") or "")


class CenterBuilder(ABC):
    """Replace the center (中枢) construction algorithm.

    Payloads are intentionally opaque to the core package: extensions receive
    their own domain objects and return their own domain objects.  The caller
    always supplies a default implementation, so an empty registry preserves
    the current behavior.
    """

    api_version = BACKEND_EXTENSION_API_VERSION

    @abstractmethod
    def build(self, bis: Sequence[Any], /, **options: Any) -> Sequence[Any]:
        """Return centers built from ``bis``.  Inputs must not be mutated."""
        raise NotImplementedError


class DivergencePolicy(ABC):
    """Replace trend/consolidation divergence decisions.

    The core package does not interpret the MACD or center payloads; it only
    forwards them to the registered policy.  The default policy is the caller's
    current strict implementation.
    """

    api_version = BACKEND_EXTENSION_API_VERSION

    @abstractmethod
    def check_trend_divergence(
        self,
        a_bi: Any,
        c_bi: Any,
        macd_out: Sequence[Any],
        dt_index: Any,
        macd_area_mode: str,
        use_dif: bool,
        use_macd_area: bool,
        logic: str = "and",
        use_zero_axis: bool = False,
    ) -> dict[str, Any]:
        """Return a divergence result dict for the trend case."""
        raise NotImplementedError

    @abstractmethod
    def check_consolidation_divergence(
        self,
        a_bi: Any,
        c_bi: Any,
        macd_out: Sequence[Any],
        dt_index: Any,
        macd_area_mode: str,
        use_dif: bool,
        use_macd_area: bool,
        logic: str = "and",
        use_zero_axis: bool = False,
    ) -> dict[str, Any]:
        """Return a divergence result dict for the consolidation case."""
        raise NotImplementedError
