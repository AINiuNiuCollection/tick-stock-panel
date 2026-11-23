"""Backend extension registry with version checks and deterministic freezing."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Generic, TypeVar

from fastapi import APIRouter

from app.extensions.contracts import (
    BACKEND_EXTENSION_API_VERSION,
    CenterBuilder,
    DefaultNotificationFormatter,
    DivergencePolicy,
    NotificationFormatter,
)

_ID_RE = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
T = TypeVar("T")


@dataclass(frozen=True)
class RegisteredImplementation(Generic[T]):
    extension_id: str
    implementation_id: str
    implementation: T
    order: int


class BackendExtensionRegistrar:
    """Staging area: a failed setup is discarded without partial registration."""

    def __init__(self, extension_id: str, *, api_version: int) -> None:
        self.extension_id = extension_id
        self.api_version = api_version
        self.routers: list[APIRouter] = []
        self.notification_formatters: list[tuple[str, NotificationFormatter, int]] = []
        self.center_builders: list[tuple[str, CenterBuilder, int]] = []
        self.divergence_policies: list[tuple[str, DivergencePolicy, int]] = []

    def include_router(self, router: APIRouter) -> None:
        if not isinstance(router, APIRouter):
            raise TypeError("router must be fastapi.APIRouter")
        self.routers.append(router)

    def register_notification_formatter(
        self,
        implementation_id: str,
        formatter: NotificationFormatter,
        *,
        order: int = 100,
    ) -> None:
        self.notification_formatters.append((implementation_id, formatter, order))

    def register_center_builder(
        self,
        implementation_id: str,
        builder: CenterBuilder,
        *,
        order: int = 100,
    ) -> None:
        self.center_builders.append((implementation_id, builder, order))

    def register_divergence_policy(
        self,
        implementation_id: str,
        policy: DivergencePolicy,
        *,
        order: int = 100,
    ) -> None:
        self.divergence_policies.append((implementation_id, policy, order))


class BackendExtensionRegistry:
    def __init__(self) -> None:
        self._extension_ids: set[str] = set()
        self._notification_formatters: list[RegisteredImplementation[NotificationFormatter]] = []
        self._center_builders: list[RegisteredImplementation[CenterBuilder]] = []
        self._divergence_policies: list[RegisteredImplementation[DivergencePolicy]] = []
        self._frozen = False

    @property
    def frozen(self) -> bool:
        return self._frozen

    @property
    def has_customizations(self) -> bool:
        return bool(self._extension_ids)

    @property
    def has_notification_formatters(self) -> bool:
        return bool(self._notification_formatters)

    @property
    def has_center_builders(self) -> bool:
        return bool(self._center_builders)

    @property
    def has_divergence_policies(self) -> bool:
        return bool(self._divergence_policies)

    def extension_ids(self) -> frozenset[str]:
        return frozenset(self._extension_ids)

    def register(self, registrar: BackendExtensionRegistrar) -> None:
        """Validate a staged extension fully before mutating the registry."""
        self._ensure_mutable()
        extension_id = registrar.extension_id
        self._validate_id(extension_id, "extension_id")
        if registrar.api_version != BACKEND_EXTENSION_API_VERSION:
            raise ValueError(
                f"extension {extension_id!r} requires backend API v{registrar.api_version}; "
                f"current is v{BACKEND_EXTENSION_API_VERSION}"
            )
        if extension_id in self._extension_ids:
            raise ValueError(f"duplicate extension id: {extension_id}")

        staged_formatters = self._stage_notification_formatters(extension_id, registrar)
        staged_builders = self._stage_center_builders(extension_id, registrar)
        staged_policies = self._stage_divergence_policies(extension_id, registrar)

        self._extension_ids.add(extension_id)
        self._notification_formatters.extend(staged_formatters)
        self._center_builders.extend(staged_builders)
        self._divergence_policies.extend(staged_policies)

    def _stage_notification_formatters(
        self, extension_id: str, registrar: BackendExtensionRegistrar
    ) -> list[RegisteredImplementation[NotificationFormatter]]:
        known_ids = {item.implementation_id for item in self._notification_formatters}
        staged_ids: set[str] = set()
        staged: list[RegisteredImplementation[NotificationFormatter]] = []
        for implementation_id, formatter, order in registrar.notification_formatters:
            self._validate_id(implementation_id, "implementation_id")
            if not isinstance(formatter, NotificationFormatter):
                raise TypeError("formatter must inherit NotificationFormatter")
            self._validate_api_version(
                "formatter", implementation_id, formatter.api_version
            )
            if implementation_id in known_ids or implementation_id in staged_ids:
                raise ValueError(f"duplicate notification formatter id: {implementation_id}")
            staged_ids.add(implementation_id)
            staged.append(
                RegisteredImplementation(extension_id, implementation_id, formatter, order)
            )
        return staged

    def _stage_center_builders(
        self, extension_id: str, registrar: BackendExtensionRegistrar
    ) -> list[RegisteredImplementation[CenterBuilder]]:
        known_ids = {item.implementation_id for item in self._center_builders}
        staged_ids: set[str] = set()
        staged: list[RegisteredImplementation[CenterBuilder]] = []
        for implementation_id, builder, order in registrar.center_builders:
            self._validate_id(implementation_id, "implementation_id")
            if not isinstance(builder, CenterBuilder):
                raise TypeError("builder must inherit CenterBuilder")
            self._validate_api_version("center builder", implementation_id, builder.api_version)
            if implementation_id in known_ids or implementation_id in staged_ids:
                raise ValueError(f"duplicate center builder id: {implementation_id}")
            staged_ids.add(implementation_id)
            staged.append(
                RegisteredImplementation(extension_id, implementation_id, builder, order)
            )
        return staged

    def _stage_divergence_policies(
        self, extension_id: str, registrar: BackendExtensionRegistrar
    ) -> list[RegisteredImplementation[DivergencePolicy]]:
        known_ids = {item.implementation_id for item in self._divergence_policies}
        staged_ids: set[str] = set()
        staged: list[RegisteredImplementation[DivergencePolicy]] = []
        for implementation_id, policy, order in registrar.divergence_policies:
            self._validate_id(implementation_id, "implementation_id")
            if not isinstance(policy, DivergencePolicy):
                raise TypeError("policy must inherit DivergencePolicy")
            self._validate_api_version("divergence policy", implementation_id, policy.api_version)
            if implementation_id in known_ids or implementation_id in staged_ids:
                raise ValueError(f"duplicate divergence policy id: {implementation_id}")
            staged_ids.add(implementation_id)
            staged.append(
                RegisteredImplementation(extension_id, implementation_id, policy, order)
            )
        return staged

    def freeze(self) -> None:
        self._notification_formatters.sort(
            key=lambda item: (item.order, item.implementation_id)
        )
        self._center_builders.sort(key=lambda item: (item.order, item.implementation_id))
        self._divergence_policies.sort(key=lambda item: (item.order, item.implementation_id))
        self._frozen = True

    def notification_formatters(
        self,
    ) -> tuple[RegisteredImplementation[NotificationFormatter], ...]:
        self._ensure_frozen()
        if not self._notification_formatters:
            return (
                RegisteredImplementation(
                    "core", "core.notification", DefaultNotificationFormatter(), 0,
                ),
            )
        return tuple(self._notification_formatters)

    def center_builder(
        self, default: CenterBuilder | None = None
    ) -> CenterBuilder | None:
        """Return the lowest-order builder, or ``default`` when none is registered."""
        self._ensure_frozen()
        if not self._center_builders:
            return default
        return self._center_builders[0].implementation

    def divergence_policy(
        self, default: DivergencePolicy | None = None
    ) -> DivergencePolicy | None:
        """Return the lowest-order policy, or ``default`` when none is registered."""
        self._ensure_frozen()
        if not self._divergence_policies:
            return default
        return self._divergence_policies[0].implementation

    def _ensure_frozen(self) -> None:
        if not self._frozen:
            raise RuntimeError("backend extension registry must be frozen before use")

    def _ensure_mutable(self) -> None:
        if self._frozen:
            raise RuntimeError("backend extension registry is frozen")

    @staticmethod
    def _validate_api_version(kind: str, implementation_id: str, api_version: int) -> None:
        if api_version != BACKEND_EXTENSION_API_VERSION:
            raise ValueError(
                f"{kind} {implementation_id!r} requires API v{api_version}; "
                f"current is v{BACKEND_EXTENSION_API_VERSION}"
            )

    @staticmethod
    def _validate_id(value: str, label: str) -> None:
        if not isinstance(value, str) or not _ID_RE.fullmatch(value):
            raise ValueError(f"invalid {label}: {value!r}")


_active_registry: BackendExtensionRegistry | None = None


def set_active_registry(registry: BackendExtensionRegistry) -> None:
    """Expose the process-wide registry to lazily-built consumers."""
    global _active_registry
    _active_registry = registry


def get_backend_extension_registry() -> BackendExtensionRegistry | None:
    return _active_registry
