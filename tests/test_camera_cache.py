"""Map camera cache identity follows navigation-relevant revisions."""

# ruff: noqa: E402

from __future__ import annotations

import asyncio
from dataclasses import replace
from unittest.mock import MagicMock

import tests.ha_stubs

tests.ha_stubs.install()

import custom_components.narwal.camera as camera_module
from custom_components.narwal.camera import (
    NarwalMapCamera,
    _RenderRequest,
    _static_map_cache_key,
)
from custom_components.narwal.narwal_client.models import MapData


def _map(**overrides: object) -> MapData:
    values: dict[str, object] = {
        "width": 2,
        "height": 2,
        "resolution": 60,
        "compressed_map": b"grid",
        "origin_x": 0,
        "origin_y": 0,
        "border_top": 1,
        "border_right": 1,
        "map_id": 1,
        "map_version": 2,
        "edit_version": 3,
        "generation_time": 4,
    }
    values.update(overrides)
    return MapData(**values)


def test_camera_cache_changes_when_edit_version_changes() -> None:
    original = _map()
    edited = replace(original, edit_version=original.edit_version + 1)

    assert _static_map_cache_key(edited) != _static_map_cache_key(original)


def test_camera_cache_changes_when_grid_changes() -> None:
    original = _map()
    edited = replace(original, compressed_map=b"different-grid")

    assert _static_map_cache_key(edited) != _static_map_cache_key(original)


def test_invalid_legacy_maps_do_not_share_cache_across_payload_objects() -> None:
    first = _map(border_top=9)
    second = replace(first)

    assert first.navigation_revision() is None
    assert second.navigation_revision() is None
    assert _static_map_cache_key(second) != _static_map_cache_key(first)


def test_camera_advertises_revision_of_cached_png_not_newer_client_map() -> None:
    camera = NarwalMapCamera.__new__(NarwalMapCamera)
    camera._render_count = 1
    camera._cached_navigation_revision = "rendered-revision"
    camera._cached_map_width = 207
    camera._cached_map_height = 223
    camera._cached_navigation_image_width = 828
    camera._cached_navigation_image_height = 892
    camera._cached_room_markers = (
        {
            "id": 4,
            "name": "Kitchen",
            "x": 0.25,
            "y": 0.75,
            "area_cells": 100,
        },
    )
    state = type(
        "State",
        (),
        {
            "map_data": _map(edit_version=99),
            "point_navigation_path": [],
        },
    )()
    client = type(
        "Client",
        (),
        {
            "state": state,
            "manual_control_active": False,
            "manual_control_state": 0,
            "point_navigation_active": False,
        },
    )()
    camera.coordinator = type("Coordinator", (), {"client": client})()

    assert camera.extra_state_attributes["navigation_map_revision"] == "rendered-revision"
    assert (
        state.map_data.navigation_revision()
        != camera.extra_state_attributes["navigation_map_revision"]
    )
    assert camera.extra_state_attributes["map_width"] == 207
    assert camera.extra_state_attributes["map_height"] == 223
    assert camera.extra_state_attributes["navigation_image_width"] == 828
    assert camera.extra_state_attributes["navigation_image_height"] == 892
    assert camera.extra_state_attributes["room_markers"] == [
        {
            "id": 4,
            "name": "Kitchen",
            "x": 0.25,
            "y": 0.75,
            "area_cells": 100,
        }
    ]


def test_coalesced_renders_keep_each_overlay_with_its_matching_base(
    monkeypatch,
) -> None:
    """A new map broadcast cannot swap the base under an older overlay."""
    monkeypatch.setattr(camera_module, "_MIN_RENDER_INTERVAL", 0)

    async def exercise() -> None:
        first_base_started = asyncio.Event()
        release_first_base = asyncio.Event()
        overlay_bases: list[bytes] = []

        class _Hass:
            async def async_add_executor_job(self, func, *args):
                if func.__name__ == "render_base_map":
                    compressed_map = args[0]
                    if compressed_map == b"map-a":
                        first_base_started.set()
                        await release_first_base.wait()
                    return b"base-" + compressed_map
                if func.__name__ == "render_overlay":
                    overlay_bases.append(args[0])
                    return b"png-" + args[0]
                if func.__name__ == "room_markers":
                    compressed_map = func.__self__.compressed_map
                    return [
                        {
                            "id": 1,
                            "name": compressed_map.decode(),
                            "x": 0.5,
                            "y": 0.5,
                            "area_cells": 1,
                        }
                    ]
                raise AssertionError(f"unexpected renderer: {func.__name__}")

            def async_create_task(self, coroutine):
                return asyncio.create_task(coroutine)

        camera = NarwalMapCamera.__new__(NarwalMapCamera)
        camera.hass = _Hass()
        camera._cached_image = None
        camera._cached_navigation_revision = None
        camera._cached_map_width = None
        camera._cached_map_height = None
        camera._cached_navigation_image_width = None
        camera._cached_navigation_image_height = None
        camera._cached_room_markers = ()
        camera._cached_room_markers_revision = None
        camera._cache_key = ()
        camera._last_render_time = 0.0
        camera._render_count = 0
        camera._base_map_image = None
        camera._base_map_revision = None
        camera._render_lock = asyncio.Lock()
        camera._render_task = None
        camera._pending_render = None
        camera.async_write_ha_state = MagicMock()

        map_a = _map(compressed_map=b"map-a")
        map_b = _map(compressed_map=b"map-b", edit_version=4)
        request_a = _RenderRequest(
            display=None,
            cache_key=("map-a",),
            static_map=map_a,
            trail=(),
            navigation_path=(),
            navigation_target=None,
        )
        request_b = _RenderRequest(
            display=None,
            cache_key=("map-b",),
            static_map=map_b,
            trail=(),
            navigation_path=(),
            navigation_target=None,
        )

        worker = asyncio.create_task(camera._async_render(request_a))
        camera._render_task = worker
        await first_base_started.wait()
        camera._queue_render(request_b)
        release_first_base.set()
        await worker

        assert overlay_bases == [b"base-map-a", b"base-map-b"]
        assert camera._cached_image == b"png-base-map-b"
        assert camera._cached_navigation_revision == map_b.navigation_revision()
        assert camera._cache_key == ("map-b",)
        assert camera._cached_room_markers == (
            {
                "id": 1,
                "name": "map-b",
                "x": 0.5,
                "y": 0.5,
                "area_cells": 1,
            },
        )

    asyncio.run(exercise())
