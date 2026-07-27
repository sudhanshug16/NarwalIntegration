"""Late discovery support for capability- and snapshot-backed entities."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

EntityFactory = Callable[[], Any]
EntityDiscovery = Callable[[], Iterable[tuple[str, EntityFactory]]]


def setup_dynamic_entities(
    entry,
    coordinator,
    async_add_entities,
    discover: EntityDiscovery,
) -> None:
    """Add each discovered entity once, including after an asleep startup."""
    added: set[str] = set()
    discovery_in_progress = False

    def add_new_entities() -> None:
        nonlocal discovery_in_progress
        if discovery_in_progress:
            return

        discovery_in_progress = True
        entities = []
        discovered_keys: list[str] = []
        pending: set[str] = set()
        try:
            for key, factory in discover():
                if key in added or key in pending:
                    continue
                entities.append(factory())
                discovered_keys.append(key)
                pending.add(key)
            if entities:
                async_add_entities(entities)
                added.update(discovered_keys)
        finally:
            discovery_in_progress = False

    add_new_entities()

    add_listener = getattr(coordinator, "async_add_listener", None)
    on_unload = getattr(entry, "async_on_unload", None)
    if callable(add_listener) and callable(on_unload):
        on_unload(add_listener(add_new_entities))


__all__ = ["setup_dynamic_entities"]
