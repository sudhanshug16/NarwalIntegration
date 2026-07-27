"""Late capability/config discovery adds entities exactly once."""

# ruff: noqa: E402

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import tests.ha_stubs

tests.ha_stubs.install()

from custom_components.narwal.button import async_setup_entry as setup_buttons
from custom_components.narwal.dynamic_entities import setup_dynamic_entities
from custom_components.narwal.narwal_client import Capability
from custom_components.narwal.narwal_client.config import (
    ConfigSnapshot,
    Language,
    SetConfigField,
)
from custom_components.narwal.number import async_setup_entry as setup_numbers
from custom_components.narwal.select import async_setup_entry as setup_selects
from custom_components.narwal.sensor import async_setup_entry as setup_sensors
from custom_components.narwal.switch import async_setup_entry as setup_switches


class _Coordinator:
    """Small coordinator that can reveal capabilities after platform setup."""

    def __init__(self) -> None:
        state = SimpleNamespace(
            capabilities={},
            config_snapshot=None,
            firmware_version="",
        )
        self.client = SimpleNamespace(state=state)
        self.data = state
        self.last_update_success = True
        self.config_entry = SimpleNamespace(
            data={"device_id": "ax15-id"},
            title="Freo X10 Pro",
        )
        self.select_options: dict[str, str] = {}
        self.parameterized_clean_enabled = False
        self.device_profile = _profile()
        self._listeners: list[object] = []

    def async_add_listener(self, callback):
        self._listeners.append(callback)

        def unsubscribe() -> None:
            self._listeners.remove(callback)

        return unsubscribe

    def notify(self) -> None:
        for callback in tuple(self._listeners):
            callback()


class _Entry:
    def __init__(self, coordinator: _Coordinator) -> None:
        self.runtime_data = coordinator
        self.unload_callbacks: list[object] = []

    def async_on_unload(self, callback) -> None:
        self.unload_callbacks.append(callback)


def _profile(**overrides):
    values = {
        "display_model": "Narwal Freo X10 Pro",
        "hardware_model": "AX15",
        "station_actions": frozenset(),
        "config_writes_enabled": False,
        "clean_plan_inventory_enabled": False,
        "schedule_inventory_enabled": False,
        "consumable_inventory_enabled": False,
        "saved_map_inventory_enabled": False,
        "editable_map_inventory_enabled": False,
        "map_update_inventory_enabled": False,
        "firmware_inventory_enabled": False,
        "language_inventory_enabled": False,
        "voice_inventory_enabled": False,
        "history_inventory_enabled": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_late_discovery_adds_each_entity_once() -> None:
    available: list[str] = []
    listener = None

    class Coordinator:
        def async_add_listener(self, callback):
            nonlocal listener
            listener = callback
            return MagicMock(name="unsubscribe")

    class Entry:
        def __init__(self) -> None:
            self.async_on_unload = MagicMock()

    coordinator = Coordinator()
    entry = Entry()
    add_entities = MagicMock()

    def discover():
        for key in available:
            yield key, lambda key=key: f"entity:{key}"

    setup_dynamic_entities(
        entry,
        coordinator,
        add_entities,
        discover,
    )

    add_entities.assert_not_called()
    assert listener is not None
    entry.async_on_unload.assert_called_once()

    available.extend(("config", "map"))
    listener()
    add_entities.assert_called_once_with(["entity:config", "entity:map"])

    listener()
    assert add_entities.call_count == 1

    available.append("timeline")
    listener()
    assert add_entities.call_args_list[-1].args[0] == ["entity:timeline"]


def test_duplicate_keys_in_one_snapshot_are_created_once() -> None:
    coordinator = _Coordinator()
    entry = _Entry(coordinator)
    add_entities = MagicMock()

    setup_dynamic_entities(
        entry,
        coordinator,
        add_entities,
        lambda: (
            ("same", lambda: "first"),
            ("same", lambda: "second"),
        ),
    )

    add_entities.assert_called_once_with(["first"])
    coordinator.notify()
    add_entities.assert_called_once_with(["first"])


def test_failed_factory_is_retried_and_does_not_consume_key() -> None:
    coordinator = _Coordinator()
    entry = _Entry(coordinator)
    add_entities = MagicMock()
    ready = False
    attempts = 0

    def factory():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("factory failed")
        return "entity:late"

    def discover():
        if ready:
            yield "late", factory

    setup_dynamic_entities(
        entry,
        coordinator,
        add_entities,
        discover,
    )
    ready = True

    with pytest.raises(RuntimeError, match="factory failed"):
        coordinator.notify()
    add_entities.assert_not_called()

    coordinator.notify()
    add_entities.assert_called_once_with(["entity:late"])
    assert attempts == 2


def test_failed_add_is_retried_and_reentrant_update_is_ignored() -> None:
    coordinator = _Coordinator()
    entry = _Entry(coordinator)
    ready = False
    attempts = 0
    added: list[str] = []

    def add_entities(entities) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("add failed")
        coordinator.notify()
        added.extend(entities)

    def discover():
        if ready:
            yield "late", lambda: "entity:late"

    setup_dynamic_entities(
        entry,
        coordinator,
        add_entities,
        discover,
    )
    ready = True

    with pytest.raises(RuntimeError, match="add failed"):
        coordinator.notify()
    assert added == []

    coordinator.notify()
    assert added == ["entity:late"]
    assert attempts == 2

    coordinator.notify()
    assert added == ["entity:late"]
    assert attempts == 2


def test_listener_unsubscribes_on_entry_unload() -> None:
    coordinator = _Coordinator()
    entry = _Entry(coordinator)

    setup_dynamic_entities(
        entry,
        coordinator,
        MagicMock(),
        lambda: (),
    )

    assert len(coordinator._listeners) == 1
    assert len(entry.unload_callbacks) == 1
    entry.unload_callbacks[0]()
    assert coordinator._listeners == []


def test_all_platforms_add_late_capabilities_then_late_config_once() -> None:
    coordinator = _Coordinator()
    added: dict[str, list[object]] = {
        "button": [],
        "number": [],
        "select": [],
        "sensor": [],
        "switch": [],
    }
    setups = {
        "button": setup_buttons,
        "number": setup_numbers,
        "select": setup_selects,
        "sensor": setup_sensors,
        "switch": setup_switches,
    }
    entries: list[_Entry] = []

    for platform, setup in setups.items():
        entry = _Entry(coordinator)
        entries.append(entry)

        def add_entities(entities, *, platform=platform) -> None:
            added[platform].extend(entities)

        asyncio.run(setup(MagicMock(), entry, add_entities))

    assert added["button"] == []
    assert added["number"] == []
    assert added["select"] == []
    assert added["switch"] == []
    baseline_sensor_ids = {
        entity._attr_unique_id for entity in added["sensor"]
    }
    assert "ax15-id_clean_plans" not in baseline_sensor_ids
    assert "ax15-id_clean_timeline" not in baseline_sensor_ids
    assert all(len(entry.unload_callbacks) == 1 for entry in entries)

    coordinator.client.state.capabilities = {
        int(Capability.MULTI_ZONE_CLEAN): 1,
        int(Capability.OVERLAP_ADJUST): 1,
        int(Capability.TEMP_HUMIDITY_DETECTION_FOR_DRY_DUST_BAG): 1,
        int(Capability.DRY_STATION_BAG): 1,
        int(Capability.UPLOAD_CONFIGURATION): 1,
        int(Capability.OPERATE_LANGUAGE): 1,
        int(Capability.PET_MODE): 1,
    }
    coordinator.parameterized_clean_enabled = True
    coordinator.device_profile = _profile(
        station_actions=frozenset(
            {
                "empty_dustbin",
                "wash_mop",
                "dry_mop",
                "wash_and_dry_mop",
                "dry_dust_bag",
                "dry_station_bag",
            }
        ),
        config_writes_enabled=True,
        clean_plan_inventory_enabled=True,
        schedule_inventory_enabled=True,
        consumable_inventory_enabled=True,
        saved_map_inventory_enabled=True,
        firmware_inventory_enabled=True,
        history_inventory_enabled=True,
    )
    coordinator.notify()

    assert len(added["button"]) == 6
    assert len(added["select"]) == 6
    assert added["number"] == []
    assert added["switch"] == []
    sensor_ids = {entity._attr_unique_id for entity in added["sensor"]}
    assert {
        "ax15-id_clean_plans",
        "ax15-id_clean_schedules",
        "ax15-id_consumable_categories",
        "ax15-id_map_inventory",
        "ax15-id_device_metadata",
        "ax15-id_clean_timeline",
    } <= sensor_ids

    counts_after_capabilities = {
        platform: len(entities)
        for platform, entities in added.items()
    }
    coordinator.notify()
    assert {
        platform: len(entities)
        for platform, entities in added.items()
    } == counts_after_capabilities

    coordinator.client.state.config_snapshot = ConfigSnapshot(
        values={
            SetConfigField.VOLUME_PERCENTAGE: 30,
            SetConfigField.LANGUAGE: Language.ENGLISH,
            SetConfigField.PET_MODE: True,
            SetConfigField.CHILD_LOCK_ENABLED: False,
        },
        raw_fields={},
    )
    coordinator.notify()

    assert [entity._attr_unique_id for entity in added["number"]] == [
        "ax15-id_robot_volume"
    ]
    assert {
        entity._attr_unique_id for entity in added["select"]
    } - {
        f"ax15-id_{key}"
        for key in (
            "mode",
            "runtime_suction",
            "runtime_water",
            "scrub",
            "route",
            "passes",
        )
    } == {"ax15-id_robot_language"}
    assert {
        entity._attr_unique_id for entity in added["switch"]
    } == {
        "ax15-id_child_lock",
        "ax15-id_pet_mode",
    }

    counts_after_config = {
        platform: len(entities)
        for platform, entities in added.items()
    }
    coordinator.notify()
    assert {
        platform: len(entities)
        for platform, entities in added.items()
    } == counts_after_config
