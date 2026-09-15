"""GE-113 — governed resources and selectors."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable


@dataclass(frozen=True)
class Resource:
    resource_id: str
    resource_class: str
    attributes: dict[str, Any] = field(default_factory=dict)
    tags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ResourceSelector:
    resource_class: str | None = None
    resource_ids: tuple[str, ...] = ()
    tags_all: tuple[str, ...] = ()
    attributes: dict[str, Any] = field(default_factory=dict)

    def matches(self, resource: Resource) -> bool:
        if self.resource_class and resource.resource_class != self.resource_class:
            return False
        if self.resource_ids and resource.resource_id not in self.resource_ids:
            return False
        if self.tags_all and not set(self.tags_all).issubset(set(resource.tags)):
            return False
        return all(resource.attributes.get(k) == v for k, v in self.attributes.items())


def select_resources(resources: Iterable[Resource], selector: ResourceSelector) -> list[Resource]:
    return [r for r in resources if selector.matches(r)]
