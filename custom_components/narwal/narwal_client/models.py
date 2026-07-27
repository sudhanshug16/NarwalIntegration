"""Data models for Narwal vacuum state."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import struct
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, ClassVar

from .capabilities import CapabilityMap
from .config import ConfigSnapshot
from .const import (
    ACTIVE_CLEANING_STATUSES,
    TOPIC_CMD_GET_ROBOT_TASK_STATUS,
    TOPIC_ROBOT_TASK_STATUS,
    CommandResult,
    TelecontrolStatus,
    WorkingStatus,
)
from .consumables import ConsumableInfoPayload
from .plan import CleanPlan
from .schedule import CleanSchedule
from .task import CurrentCleanTask

if TYPE_CHECKING:
    from .device_metadata import (
        FirmwareVersionResponse,
        GetCurrentVoiceInfoResponse,
        GetLanguageResponse,
        GetSupportedLanguagesResponse,
    )
    from .history import GetCleanTimeLineResponse
    from .map_inventory import (
        CheckMapUpdateInfoResponse,
        GetEditableMapResponse,
        StaticMapPayload,
    )

_LOGGER = logging.getLogger(__name__)
_ACTIVE_WORKING_STATUS_TTL = 15.0


@dataclass
class DeviceInfo:
    """Device identity from get_device_info response."""

    product_key: str = ""
    device_id: str = ""
    firmware_version: str = ""


@dataclass
class RoomInfo:
    """A room on the map.

    Fields from get_map / get_editable_map field 2.12:
      field 1: room_id (matches pixel value >> 8 in map grid)
      field 2: room_sub_type — ROOM_TYPE enum from APK (0=unspecified,
               1=main bedroom, 2=secondary room, 3=living room, 4=kitchen,
               5=study, 6=bathroom, 7=dining room, 8=corridor, 9=balcony,
               10=utility room, 11=cloak room, 12=nursery, 13=recreation,
               14=shower room, 15=other)
      field 3: user-assigned name (UTF-8, empty if not named by user)
      field 4: category (1=room, 2=utility/small space)
      field 8: instance_index (1-based, for numbering duplicates: Bathroom 1, 2, 3...)
    """

    room_id: int = 0
    name: str = ""  # user-assigned name from field 3
    room_sub_type: int = 0  # ROOM_TYPE enum from field 2
    category: int = 0  # 1=room, 2=utility (field 4)
    instance_index: int = 0  # numbering for duplicates (field 8)
    model_key: str = ""  # product_key — selects per-model name overrides

    # ROOM_TYPE enum → default display name (from APK libapp.so string analysis)
    ROOM_TYPE_NAMES: dict[int, str] = field(default=None, repr=False)

    # Per-model overrides where Narwal renamed sub-types between models.
    # Confirmed on Narwal Flow 2 (QxMSPG6VSO, firmware v01.07.16.01) — see #22.
    MODEL_ROOM_TYPE_OVERRIDES: ClassVar[dict[str, dict[int, str]]] = {
        "QxMSPG6VSO": {  # Flow 2
            1: "Master Bedroom",
            5: "Bathroom",
            10: "Corridor",
        },
        "iSuVlI1If2": {  # Flow 2 alternate product key
            1: "Master Bedroom",
            5: "Bathroom",
            10: "Corridor",
        },
    }

    def __post_init__(self):
        if self.ROOM_TYPE_NAMES is None:
            object.__setattr__(self, "ROOM_TYPE_NAMES", {
                0: "Room",
                1: "Primary Bedroom",
                2: "Secondary Bedroom",
                3: "Living Room",
                4: "Kitchen",
                5: "Study",
                6: "Bathroom",
                7: "Dining Room",
                8: "Corridor",
                9: "Balcony",
                10: "Utility Room",
                11: "Cloak Room",
                12: "Nursery",
                13: "Recreation Room",
                14: "Shower Room",
                15: "Other",
            })

    @property
    def display_name(self) -> str:
        """Return user name if set, otherwise generate default from ROOM_TYPE enum.

        Matches Narwal app behavior: unnamed rooms show their type name
        with an instance number suffix for duplicates (e.g. "Bathroom 2").
        Per-model overrides apply where Narwal renamed sub-types (e.g. Flow 2
        renames sub_type 1 → "Master Bedroom" vs Flow 1's "Primary Bedroom").
        """
        if self.name:
            return self.name
        overrides = self.MODEL_ROOM_TYPE_OVERRIDES.get(self.model_key, {})
        base = overrides.get(self.room_sub_type) or \
            self.ROOM_TYPE_NAMES.get(self.room_sub_type, "Room")
        if self.instance_index > 1:
            return f"{base} {self.instance_index}"
        return base


@dataclass
class ObstacleInfo:
    """An obstacle/furniture annotation on the map.

    Parsed from get_map field 2.32 (MapFurnitureInfoList).
    The typeId maps to the furniture enum from APK map_furniture.json.

    bbp field mapping (confirmed from probe data + APK schema):
      bbp field 1 -> id (int32)
      bbp field 2 -> typeId (uint32, furniture enum)
      bbp field 3.1.1 -> centerX (float32)
      bbp field 3.1.2 -> centerY (float32)
      bbp field 3.2 -> width (float32)
      bbp field 3.3 -> height (float32)
      bbp field 4 -> angle (float32, degrees)
    """

    id: int = 0
    type_id: int = 0       # Furniture enum from APK map_furniture.json
    center_x: float = 0.0  # World X coordinate
    center_y: float = 0.0  # World Y coordinate
    width: float = 0.0     # Object width in grid units
    height: float = 0.0    # Object height in grid units
    angle: float = 0.0     # Rotation in degrees

    # Full furniture type enum from APK map_furniture.json
    TYPE_NAMES: ClassVar[dict[int, str]] = {
        0: "Placeholder",
        1: "Single Bed",
        2: "Double Bed",
        3: "Baby Bed",
        4: "Dining Table",
        5: "Round Table",
        6: "Tea Table",
        7: "Round Tea Table",
        8: "TV Stand",
        9: "Bedside Table",
        10: "Locker",
        11: "Wardrobe",
        12: "Shoe Cabinet",
        13: "Armchair",
        14: "Sofa",
        15: "L-Shaped Sofa",
        16: "Lazy Chair",
        17: "Chair",
        18: "Bar Chair",
        19: "Cat Toilet",
        20: "Pet Feeder",
        21: "Pet House",
        22: "Washing Machine",
        23: "Refrigerator",
        24: "Air Conditioner",
        25: "Fan",
        26: "Potted Plant",
        27: "Floor Mirror",
        28: "Toilet",
        29: "Piano",
        30: "U-Shaped Sofa",
        31: "Desk",
        32: "Grand Piano",
        33: "Washbasin",
        34: "Stove",
        75: "Cat House",
        76: "Dog House",
        77: "Round Placeholder",
        78: "Weighing Scale",
    }

    @property
    def display_name(self) -> str:
        """Return human-readable name for the obstacle type."""
        return self.TYPE_NAMES.get(self.type_id, f"Object {self.type_id}")

    def to_grid_coords(self, origin_x: int, origin_y: int) -> tuple[float, float]:
        """Convert world coordinates to grid pixel coordinates.

        Same transform as dock/robot: pixel = raw - origin.
        """
        return (self.center_x - origin_x, self.center_y - origin_y)


def _to_float32(val: Any) -> float | None:
    """Convert a protobuf value to float32.

    blackboxprotobuf may return fixed32 fields as either:
      - Python float (if it detects wire type 5 as float)
      - Python int (raw uint32 bit pattern)
    Handle both cases.
    """
    if isinstance(val, float):
        return val
    if isinstance(val, int):
        try:
            return struct.unpack("f", struct.pack("I", val & 0xFFFFFFFF))[0]
        except struct.error:
            return None
    return None


def _parse_obstacles(field32: dict) -> list[ObstacleInfo]:
    """Parse obstacle/furniture annotations from bbp-decoded field 2.32.

    Args:
        field32: The decoded dict from map payload field "32".

    Returns:
        List of ObstacleInfo objects. Skips items that fail to parse.
    """
    items = field32.get("1", [])
    if isinstance(items, dict):
        items = [items]

    obstacles: list[ObstacleInfo] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            pos = item.get("3", {})
            center = pos.get("1", {}) if isinstance(pos, dict) else {}

            cx = _to_float32(center.get("1")) if isinstance(center, dict) else None
            cy = _to_float32(center.get("2")) if isinstance(center, dict) else None
            w = _to_float32(pos.get("2")) if isinstance(pos, dict) else None
            h = _to_float32(pos.get("3")) if isinstance(pos, dict) else None
            angle = _to_float32(item.get("4"))

            obstacles.append(ObstacleInfo(
                id=int(item.get("1", 0)),
                type_id=int(item.get("2", 0)),
                center_x=cx or 0.0,
                center_y=cy or 0.0,
                width=w or 0.0,
                height=h or 0.0,
                angle=angle or 0.0,
            ))
        except (ValueError, TypeError, AttributeError):
            continue
    return obstacles


def _coerce_bytes(value: Any) -> bytes:
    """Return a protobuf bytes value as bytes."""
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, str):
        return value.encode("latin-1", "ignore")
    return b""


def _count_cleaned_pixels(value: Any, expected_pixels: int) -> int:
    """Count non-zero cells in a display_map cleaned-area overlay."""
    data = _coerce_bytes(value)
    if not data:
        return 0

    from .map_renderer import _decode_packed_varints, decompress_map

    decompressed = decompress_map(data)
    pixels = _decode_packed_varints(decompressed)
    if pixels:
        if expected_pixels > 0:
            pixels = pixels[:expected_pixels]
        return sum(1 for pixel in pixels if pixel)

    raw = decompressed or data
    if expected_pixels > 0:
        raw = raw[:expected_pixels]
    return sum(1 for byte in raw if byte)


def _extract_ints(value: Any) -> list[int]:
    """Extract integer values from a loosely-decoded protobuf field."""
    if isinstance(value, bool):
        return []
    if isinstance(value, int):
        return [value]
    if isinstance(value, list):
        result: list[int] = []
        for item in value:
            result.extend(_extract_ints(item))
        return result
    if isinstance(value, dict):
        result: list[int] = []
        for item in value.values():
            result.extend(_extract_ints(item))
        return result
    return []


def _positive_int_field(decoded: dict[str, Any], field: str) -> bool:
    """Return true when a decoded protobuf field is a positive integer."""
    try:
        return int(decoded.get(field, 0) or 0) > 0
    except (TypeError, ValueError):
        return False


def _optional_int(value: Any) -> int | None:
    """Return value coerced to int, or None when it cannot be coerced."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_finite_number(value: Any) -> bool:
    """Return true only for a finite, non-boolean int or float."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


class MapCellType(StrEnum):
    """Safety-relevant classification of a decoded map grid value."""

    UNKNOWN = "unknown"
    ROOM_FLOOR = "room_floor"
    UNASSIGNED_FLOOR = "unassigned_floor"
    WALL = "wall"
    OBSTACLE = "obstacle"


def classify_map_pixel(value: int) -> MapCellType:
    """Classify one decoded Narwal map-grid value without guessing.

    The low byte stores pixel flags and the remaining bits store the room ID.
    Only assigned room floor is accepted by navigation target validation.
    """
    if value == 0:
        return MapCellType.UNKNOWN
    if value == 0x20:
        return MapCellType.UNASSIGNED_FLOOR

    pixel_type = value & 0xFF
    if pixel_type & 0x08:
        return MapCellType.OBSTACLE
    if pixel_type & 0x10:
        return MapCellType.WALL
    if value >> 8:
        return MapCellType.ROOM_FLOOR
    return MapCellType.UNKNOWN


@dataclass(frozen=True)
class MapBorder:
    """Raw map coordinate bounds from StaticMapPayload field 6."""

    bottom: int
    top: int
    left: int
    right: int

    def is_valid_for(self, width: int, height: int) -> bool:
        """Return whether the inclusive border exactly matches the grid."""
        values = (width, height, self.bottom, self.top, self.left, self.right)
        if any(not isinstance(value, int) or isinstance(value, bool) for value in values):
            return False
        return (
            width > 0
            and height > 0
            and self.right >= self.left
            and self.top >= self.bottom
            and self.right - self.left + 1 == width
            and self.top - self.bottom + 1 == height
        )


@dataclass
class MapData:
    """Map data from get_map response."""

    width: int = 0
    height: int = 0
    resolution: int = 0
    rooms: list[RoomInfo] = field(default_factory=list)
    compressed_map: bytes = b""
    area: int = 0
    created_at: int = 0
    dock_x: float | None = None  # dock position in grid coordinates
    dock_y: float | None = None
    origin_x: int = 0  # x pixel offset from field 2.6.3
    origin_y: int = 0  # y pixel offset from field 2.6.1
    obstacles: list[ObstacleInfo] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
    map_id: int = 0  # active map id (field 2.1) — required by clean/start_clean
    # Corrected StaticMapPayload schema fields. Appended to preserve the legacy
    # dataclass positional argument order above.
    map_version: int = 0  # field 2
    border_top: int = 0  # field 6.2
    border_right: int = 0  # field 6.4
    rotate_angle: int = 0  # field 25; app display rotation, not raw renderer
    edit_version: int = 0  # field 33; also retained in legacy ``area``
    generation_time: int = 0  # field 34; also retained in ``created_at``

    @classmethod
    def from_response(
        cls, decoded: dict[str, Any], product_key: str = ""
    ) -> MapData:
        """Parse map data from a get_map field5 response.

        Args:
            decoded: blackboxprotobuf-decoded get_map response.
            product_key: Device product key — propagated to RoomInfo so model-
                specific room-type name overrides apply (see #22 for Flow 2).
        """
        payload = decoded.get("2", {})
        if not payload:
            return cls()

        rooms = []
        room_list = payload.get("12", [])
        if isinstance(room_list, dict):
            room_list = [room_list]
        for room in room_list:
            if isinstance(room, dict):
                name_raw = room.get("3", b"")
                if isinstance(name_raw, bytes):
                    name = name_raw.decode("utf-8", errors="replace")
                elif isinstance(name_raw, str):
                    # blackboxprotobuf sometimes returns "b'...'" strings
                    name = name_raw
                    if name.startswith("b'") and name.endswith("'"):
                        name = name[2:-1]
                else:
                    name = str(name_raw)
                rooms.append(RoomInfo(
                    room_id=int(room.get("1", 0)),
                    name=name,
                    room_sub_type=int(room.get("2", 0)),
                    category=int(room.get("4", 0)),
                    instance_index=int(room.get("8", 0)),
                    model_key=product_key,
                ))

        compressed = payload.get("17", b"")
        if isinstance(compressed, str):
            compressed = compressed.encode("latin-1")

        resolution = int(payload.get("3", 0))

        # StaticMapPayload field 6 is an inclusive Border:
        # {1: bottom, 2: top, 3: left, 4: right}. Preserve origin_x/y as
        # compatibility aliases for left/bottom.
        origin_x = 0
        origin_y = 0
        border_top = 0
        border_right = 0
        field6 = payload.get("6")
        if isinstance(field6, dict):
            parsed_origin_x = _optional_int(field6.get("3", 0))
            if parsed_origin_x is not None:
                origin_x = parsed_origin_x
            parsed_origin_y = _optional_int(field6.get("1", 0))
            if parsed_origin_y is not None:
                origin_y = parsed_origin_y
            parsed_border_top = _optional_int(field6.get("2", 0))
            if parsed_border_top is not None:
                border_top = parsed_border_top
            parsed_border_right = _optional_int(field6.get("4", 0))
            if parsed_border_right is not None:
                border_right = parsed_border_right

        # Parse dock position from field 8 (dock/charging station location).
        # Field 8 structure: {1: {1: x_dm, 2: y_dm}, 2: heading_rad}
        # Coordinates are in decimeters (same as display_map field 5).
        # Matches display_map field 5 (confirmed via live capture cross-reference).
        # Pixel transform: px = (x_dm * 10) / cm_per_pixel - origin
        dock_x = None
        dock_y = None
        field8 = payload.get("8")
        if isinstance(field8, dict) and resolution > 0:
            pos = field8.get("1")
            if isinstance(pos, dict) and "1" in pos and "2" in pos:
                try:
                    x_dm = _to_float32(pos["1"])
                    y_dm = _to_float32(pos["2"])
                    if x_dm is not None and y_dm is not None:
                        dock_x = x_dm - origin_x
                        dock_y = y_dm - origin_y
                except (struct.error, OverflowError, ValueError, TypeError):
                    pass

        # Parse obstacle/furniture annotations from field 32 (MapFurnitureInfoList)
        obstacles: list[ObstacleInfo] = []
        field32 = payload.get("32")
        if isinstance(field32, dict):
            obstacles = _parse_obstacles(field32)

        return cls(
            map_id=int(payload.get("1", 0)),
            width=int(payload.get("4", 0)),
            height=int(payload.get("5", 0)),
            resolution=resolution,
            rooms=rooms,
            compressed_map=compressed if isinstance(compressed, bytes) else b"",
            area=int(payload.get("33", 0)),
            created_at=int(payload.get("34", 0)),
            dock_x=dock_x,
            dock_y=dock_y,
            origin_x=origin_x,
            origin_y=origin_y,
            obstacles=obstacles,
            raw=payload,
            map_version=int(payload.get("2", 0)),
            border_top=border_top,
            border_right=border_right,
            rotate_angle=int(payload.get("25", 0)),
            edit_version=int(payload.get("33", 0)),
            generation_time=int(payload.get("34", 0)),
        )

    @property
    def border(self) -> MapBorder:
        """Return the field-6 border using legacy left/bottom aliases."""
        return MapBorder(
            bottom=self.origin_y,
            top=self.border_top,
            left=self.origin_x,
            right=self.border_right,
        )

    def has_valid_navigation_geometry(self) -> bool:
        """Return whether this map can safely support navigation transforms."""
        return (
            self.border.is_valid_for(self.width, self.height)
            and isinstance(self.resolution, int)
            and not isinstance(self.resolution, bool)
            and self.resolution > 0
            and isinstance(self.rotate_angle, int)
            and not isinstance(self.rotate_angle, bool)
            and self.rotate_angle in (0, 90, 180, 270)
        )

    def navigation_revision(self) -> str | None:
        """Return a stable SHA-256 identity for navigation-relevant map state.

        The current renderer uses the raw unrotated grid. ``rotate_angle`` is
        still part of the revision so an app-side map orientation change
        invalidates any pending navigation preview.
        """
        if not self.has_valid_navigation_geometry() or not isinstance(
            self.compressed_map, bytes
        ):
            return None

        edit_version = self.edit_version or self.area
        generation_time = self.generation_time or self.created_at
        identity = {
            "border": {
                "bottom": self.origin_y,
                "left": self.origin_x,
                "right": self.border_right,
                "top": self.border_top,
            },
            "edit_version": edit_version,
            "generation_time": generation_time,
            "height": self.height,
            "map_id": self.map_id,
            "map_version": self.map_version,
            "resolution": self.resolution,
            "rotate_angle": self.rotate_angle,
            "width": self.width,
        }
        digest = hashlib.sha256()
        digest.update(
            json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        digest.update(b"\0")
        digest.update(self.compressed_map)
        return digest.hexdigest()

    def room_markers(self) -> list[dict[str, int | str | float]]:
        """Return named room-floor centroids in rendered image coordinates.

        The map grid stores Y increasing upward, while the rendered PNG is
        vertically flipped.  Marker coordinates therefore use the same
        unrotated, image-top-left convention as ``normalized_image_to_world``.
        This deliberately fails closed: a marker is emitted only when the raw
        grid has an exact valid size, the room is known by map metadata, and
        its contributing cells are classified as assigned room floor.
        """
        pixels = self._navigation_pixels()
        if pixels is None or not isinstance(self.rooms, list):
            return []

        room_names: dict[int, str] = {}
        room_order: list[int] = []
        duplicate_room_ids: set[int] = set()
        for room in self.rooms:
            if (
                not isinstance(room, RoomInfo)
                or not isinstance(room.room_id, int)
                or isinstance(room.room_id, bool)
                or room.room_id <= 0
            ):
                continue

            name = room.display_name
            if not isinstance(name, str) or not name:
                continue
            if room.room_id in room_names:
                duplicate_room_ids.add(room.room_id)
                continue
            room_names[room.room_id] = name
            room_order.append(room.room_id)

        for room_id in duplicate_room_ids:
            room_names.pop(room_id, None)

        room_sum_x: dict[int, int] = {}
        room_sum_y: dict[int, int] = {}
        room_count: dict[int, int] = {}
        for index, value in enumerate(pixels):
            if classify_map_pixel(value) is not MapCellType.ROOM_FLOOR:
                continue
            room_id = value >> 8
            if room_id not in room_names:
                continue
            grid_x = index % self.width
            grid_y = index // self.width
            room_sum_x[room_id] = room_sum_x.get(room_id, 0) + grid_x
            room_sum_y[room_id] = room_sum_y.get(room_id, 0) + grid_y
            room_count[room_id] = room_count.get(room_id, 0) + 1

        markers: list[dict[str, int | str | float]] = []
        for room_id in room_order:
            count = room_count.get(room_id, 0)
            if room_id in duplicate_room_ids or count == 0:
                continue
            grid_x = room_sum_x[room_id] // count
            image_y = self.height - 1 - (room_sum_y[room_id] // count)
            markers.append(
                {
                    "id": room_id,
                    "name": room_names[room_id],
                    "x": (grid_x + 0.5) / self.width,
                    "y": (image_y + 0.5) / self.height,
                    "area_cells": count,
                }
            )
        return markers

    def world_to_grid(
        self, world_x: float, world_y: float
    ) -> tuple[float, float] | None:
        """Convert raw world coordinates to the unrotated bottom-up grid."""
        if (
            not self.has_valid_navigation_geometry()
            or not _is_finite_number(world_x)
            or not _is_finite_number(world_y)
            or world_x < self.origin_x
            or world_x > self.border_right
            or world_y < self.origin_y
            or world_y > self.border_top
        ):
            return None
        return (world_x - self.origin_x, world_y - self.origin_y)

    def grid_to_world(
        self, grid_x: float, grid_y: float
    ) -> tuple[float, float] | None:
        """Convert an in-bounds bottom-up grid coordinate to raw world space."""
        if (
            not self.has_valid_navigation_geometry()
            or not _is_finite_number(grid_x)
            or not _is_finite_number(grid_y)
            or grid_x < 0
            or grid_x > self.width - 1
            or grid_y < 0
            or grid_y > self.height - 1
        ):
            return None
        return (self.origin_x + grid_x, self.origin_y + grid_y)

    def grid_to_image(
        self, grid_x: float, grid_y: float, render_scale: int = 1
    ) -> tuple[float, float] | None:
        """Convert grid coordinates to the current unrotated PNG coordinates."""
        if (
            not isinstance(render_scale, int)
            or isinstance(render_scale, bool)
            or render_scale < 1
        ):
            return None
        if self.grid_to_world(grid_x, grid_y) is None:
            return None
        return (
            grid_x * render_scale,
            (self.height - 1 - grid_y) * render_scale,
        )

    def image_to_grid_cell(
        self, image_x: float, image_y: float, render_scale: int = 1
    ) -> tuple[int, int] | None:
        """Convert a natural unrotated PNG pixel to its bottom-up grid cell."""
        if (
            not self.has_valid_navigation_geometry()
            or not isinstance(render_scale, int)
            or isinstance(render_scale, bool)
            or render_scale < 1
            or not _is_finite_number(image_x)
            or not _is_finite_number(image_y)
            or image_x < 0
            or image_y < 0
            or image_x >= self.width * render_scale
            or image_y >= self.height * render_scale
        ):
            return None
        image_cell_x = math.floor(image_x / render_scale)
        image_cell_y = math.floor(image_y / render_scale)
        return (image_cell_x, self.height - 1 - image_cell_y)

    def normalized_image_to_world(
        self, normalized_x: float, normalized_y: float
    ) -> tuple[float, float] | None:
        """Map a normalized natural-image click in ``[0, 1)`` to raw world.

        Normalization makes this independent of renderer scale. The result is
        deliberately snapped to the selected occupancy cell; ``rotate_angle``
        is not applied because the integration renders the raw map.
        """
        if (
            not self.has_valid_navigation_geometry()
            or not _is_finite_number(normalized_x)
            or not _is_finite_number(normalized_y)
            or normalized_x < 0
            or normalized_y < 0
            or normalized_x >= 1
            or normalized_y >= 1
        ):
            return None
        grid = self.image_to_grid_cell(
            normalized_x * self.width,
            normalized_y * self.height,
        )
        if grid is None:
            return None
        return self.grid_to_world(*grid)

    def classify_grid_cell(self, grid_x: int, grid_y: int) -> MapCellType | None:
        """Return the exact map-cell class, or ``None`` for invalid map data."""
        pixels = self._navigation_pixels()
        if (
            pixels is None
            or not isinstance(grid_x, int)
            or isinstance(grid_x, bool)
            or not isinstance(grid_y, int)
            or isinstance(grid_y, bool)
            or grid_x < 0
            or grid_y < 0
            or grid_x >= self.width
            or grid_y >= self.height
        ):
            return None
        return classify_map_pixel(pixels[grid_y * self.width + grid_x])

    def is_navigation_target_clear(
        self,
        grid_x: int,
        grid_y: int,
        clearance_cells: int = 0,
        *,
        reject_furniture: bool = True,
    ) -> bool:
        """Validate assigned floor and a square clearance around a target cell."""
        pixels = self._navigation_pixels()
        if (
            pixels is None
            or not isinstance(grid_x, int)
            or isinstance(grid_x, bool)
            or not isinstance(grid_y, int)
            or isinstance(grid_y, bool)
            or not isinstance(clearance_cells, int)
            or isinstance(clearance_cells, bool)
            or clearance_cells < 0
            or grid_x < 0
            or grid_y < 0
            or grid_x >= self.width
            or grid_y >= self.height
            or classify_map_pixel(pixels[grid_y * self.width + grid_x])
            is not MapCellType.ROOM_FLOOR
        ):
            return False

        for check_y in range(grid_y - clearance_cells, grid_y + clearance_cells + 1):
            for check_x in range(
                grid_x - clearance_cells, grid_x + clearance_cells + 1
            ):
                if (
                    check_x < 0
                    or check_y < 0
                    or check_x >= self.width
                    or check_y >= self.height
                    or classify_map_pixel(pixels[check_y * self.width + check_x])
                    is not MapCellType.ROOM_FLOOR
                ):
                    return False

        if not reject_furniture:
            return True
        for obstacle in self.obstacles:
            contains = self._furniture_contains_grid_cell(
                obstacle, grid_x, grid_y, clearance_cells
            )
            if contains is None or contains:
                return False
        return True

    def _navigation_pixels(self) -> list[int] | None:
        """Decode an exact-size map grid, failing closed on malformed data."""
        if (
            not self.has_valid_navigation_geometry()
            or not isinstance(self.compressed_map, bytes)
            or not self.compressed_map
        ):
            return None

        from .map_renderer import _decode_packed_varints, decompress_map

        pixels = _decode_packed_varints(decompress_map(self.compressed_map))
        if len(pixels) != self.width * self.height:
            return None
        return pixels

    def _furniture_contains_grid_cell(
        self,
        obstacle: ObstacleInfo,
        grid_x: int,
        grid_y: int,
        padding: int,
    ) -> bool | None:
        """Return whether a cell intersects an expanded rotated furniture box."""
        values = (
            obstacle.center_x,
            obstacle.center_y,
            obstacle.width,
            obstacle.height,
            obstacle.angle,
        )
        if not all(_is_finite_number(value) for value in values):
            return None
        if obstacle.width < 0 or obstacle.height < 0:
            return None

        center_x = obstacle.center_x - self.origin_x
        center_y = obstacle.center_y - self.origin_y
        delta_x = grid_x - center_x
        delta_y = grid_y - center_y
        angle = math.radians(obstacle.angle)
        cos_angle = math.cos(angle)
        sin_angle = math.sin(angle)
        local_x = delta_x * cos_angle + delta_y * sin_angle
        local_y = -delta_x * sin_angle + delta_y * cos_angle
        half_width = obstacle.width / 2 + padding + 0.5
        half_height = obstacle.height / 2 + padding + 0.5
        return abs(local_x) <= half_width and abs(local_y) <= half_height

    def cleanable_area_cm2(self, room_ids: list[int] | None = None) -> int:
        """Estimate cleanable area in cm² from room floor pixels."""
        if not self.compressed_map or self.width <= 0 or self.height <= 0:
            return 0
        if self.resolution <= 0:
            return 0

        from .map_renderer import _decode_packed_varints, decompress_map

        pixels = _decode_packed_varints(decompress_map(self.compressed_map))
        expected = self.width * self.height
        if len(pixels) < expected:
            pixels.extend([0] * (expected - len(pixels)))
        elif len(pixels) > expected:
            pixels = pixels[:expected]

        selected = {int(room_id) for room_id in room_ids or []}
        floor_pixels = 0
        for val in pixels:
            if val in (0, 0x28):
                continue
            if val == 0x20:
                if selected:
                    continue
                floor_pixels += 1
                continue
            room_id = val >> 8
            pixel_type = val & 0xFF
            if pixel_type & 0x10:
                continue
            if selected and room_id not in selected:
                continue
            floor_pixels += 1

        cm_per_pixel = self.resolution / 10
        return round(floor_pixels * cm_per_pixel * cm_per_pixel)


@dataclass
class MapDisplayData:
    """Real-time robot position from map/display_map broadcasts.

    Sent every ~1.5s during active cleaning. Contains robot position in cm,
    heading in radians, and a small cleaned-area grid overlay (NOT the full
    house map — that comes from get_map).

    Validated field layout (live capture 2026-02-28, 13 broadcasts):
      field 1.1: {1: x_cm, 2: y_cm} — robot position as float32 centimeters
      field 1.2: heading as float32 radians
      field 5: dock/reference position (constant, same format)
      field 7: cleaned-area grid {1: width, 2: height, 3: compressed_bytes}
      field 10: timestamp in milliseconds since epoch
      field 12: active room list
    """

    robot_x: float = 0.0  # decimeters, world coordinates
    robot_y: float = 0.0  # decimeters, world coordinates
    robot_heading: float = 0.0  # degrees (converted from radians for renderer)
    timestamp: int = 0  # milliseconds since epoch (field 10)
    # Dock/reference position from field 5 (same coordinate system as robot)
    dock_ref_x: float = 0.0
    dock_ref_y: float = 0.0
    cleaned_width: int = 0
    cleaned_height: int = 0
    cleaned_pixel_count: int = 0
    active_room_ids: list[int] = field(default_factory=list)

    def to_grid_coords(
        self, resolution: int, origin_x: int, origin_y: int,
    ) -> tuple[float, float] | None:
        """Convert world-coordinate position (dm) to grid pixel coordinates.

        display_map positions are in decimeters (validated via live capture).
        Same coordinate system as get_map field 8 (dock position).
          pixel = (x_dm * 10) / cm_per_pixel - origin_offset

        Args:
            resolution: Map resolution in mm/pixel (e.g. 60).
            origin_x: X pixel offset (MapData.origin_x, from field 2.6.3).
            origin_y: Y pixel offset (MapData.origin_y, from field 2.6.1).

        Returns:
            (pixel_x, pixel_y) tuple, or None if no valid position.
        """
        if self.robot_x == 0.0 and self.robot_y == 0.0:
            return None
        if resolution <= 0:
            return None
        # Positions are in grid-offset units: pixel = raw - origin
        px = self.robot_x - origin_x
        py = self.robot_y - origin_y
        return (px, py)

    @classmethod
    def from_broadcast(cls, decoded: dict[str, Any]) -> MapDisplayData:
        """Parse display_map broadcast payload."""
        import math

        result = cls()

        # Robot position — field 1.1 = {1: x_cm, 2: y_cm}, field 1.2 = heading_rad
        field1 = decoded.get("1", {})
        if isinstance(field1, dict):
            pos = field1.get("1", {})
            if isinstance(pos, dict):
                x_f = _to_float32(pos.get("1"))
                if x_f is not None and math.isfinite(x_f):
                    result.robot_x = x_f
                y_f = _to_float32(pos.get("2"))
                if y_f is not None and math.isfinite(y_f):
                    result.robot_y = y_f

            heading_raw = field1.get("2")
            if heading_raw is not None:
                h_f = _to_float32(heading_raw)
                if h_f is not None and math.isfinite(h_f):
                    result.robot_heading = math.degrees(h_f)

        # Dock/reference position — field 5 (same format as field 1)
        field5 = decoded.get("5", {})
        if isinstance(field5, dict):
            pos5 = field5.get("1", {})
            if isinstance(pos5, dict):
                dx = _to_float32(pos5.get("1"))
                if dx is not None and math.isfinite(dx):
                    result.dock_ref_x = dx
                dy = _to_float32(pos5.get("2"))
                if dy is not None and math.isfinite(dy):
                    result.dock_ref_y = dy

        # Timestamp — field 10 (milliseconds since epoch)
        if "10" in decoded:
            try:
                result.timestamp = int(decoded["10"])
            except (ValueError, TypeError):
                pass

        field7 = decoded.get("7")
        if isinstance(field7, list):
            field7 = field7[0] if field7 else None
        if isinstance(field7, dict):
            try:
                result.cleaned_width = int(field7.get("1", 0))
                result.cleaned_height = int(field7.get("2", 0))
            except (ValueError, TypeError):
                result.cleaned_width = 0
                result.cleaned_height = 0
            result.cleaned_pixel_count = _count_cleaned_pixels(
                field7.get("3"),
                result.cleaned_width * result.cleaned_height,
            )

        if "12" in decoded:
            seen: set[int] = set()
            room_ids: list[int] = []
            for room_id in _extract_ints(decoded["12"]):
                if room_id > 0 and room_id not in seen:
                    seen.add(room_id)
                    room_ids.append(room_id)
            result.active_room_ids = room_ids

        return result

    def cleaned_area_cm2(self, resolution: int) -> int:
        """Return the cleaned overlay area in cm²."""
        if self.cleaned_pixel_count <= 0 or resolution <= 0:
            return 0
        cm_per_pixel = resolution / 10
        return round(self.cleaned_pixel_count * cm_per_pixel * cm_per_pixel)


@dataclass
class Position:
    """Robot position from map/display_map."""

    x: float = 0.0
    y: float = 0.0
    heading: float = 0.0


@dataclass
class CommandResponse:
    """Response from a command sent to the robot."""

    result_code: int = 0
    data: dict[str, Any] = field(default_factory=dict)
    raw_payload: bytes = b""
    # False when payload field 1 is absent or structured query data. Callers
    # must not infer action success from the placeholder result_code in that case.
    result_known: bool = True

    @property
    def success(self) -> bool:
        return self.result_known and self.result_code == CommandResult.SUCCESS

    @property
    def not_applicable(self) -> bool:
        return (
            self.result_known
            and self.result_code == CommandResult.NOT_APPLICABLE
        )


@dataclass
class NarwalState:
    """Complete state of a Narwal vacuum.

    Updated incrementally as different topic messages arrive.
    """

    # Core status
    working_status: WorkingStatus = WorkingStatus.UNKNOWN
    battery_level: int = 0  # real-time SOC from field 2 (float32)
    battery_health: int = 0  # static design capacity from field 38 (always 100)
    inferred_docked_from_battery: bool = False
    firmware_version: str = ""
    firmware_target: str = ""

    # Device identity
    device_info: DeviceInfo | None = None
    capabilities: CapabilityMap = field(default_factory=dict)
    capabilities_fetched: bool = False
    config_snapshot: ConfigSnapshot | None = None
    current_clean_task: CurrentCleanTask | None = None
    current_clean_plan: CleanPlan | None = None
    clean_plans: tuple[CleanPlan, ...] = ()
    clean_schedules: tuple[CleanSchedule, ...] = ()
    consumable_info: ConsumableInfoPayload | None = None
    firmware_metadata: FirmwareVersionResponse | None = None
    configured_language: GetLanguageResponse | None = None
    supported_languages: GetSupportedLanguagesResponse | None = None
    current_voice_info: GetCurrentVoiceInfoResponse | None = None
    clean_timeline: GetCleanTimeLineResponse | None = None

    # Session
    session_id: str = ""
    timestamp: int = 0

    # Position (from map data)
    position: Position | None = None

    # Cleaning stats
    cleaning_area: int = 0  # cm²
    cleaning_time: int = 0  # seconds
    last_active_working_status_time: float = 0.0
    task_progress_percent: int | None = None
    task_elapsed_time: int = 0
    current_room_id: int | None = None
    current_room_name: str = ""
    dry_mop_remaining_time: int | None = None

    # Map
    map_data: MapData | None = None
    map_display_data: MapDisplayData | None = None
    saved_maps: tuple[StaticMapPayload, ...] = ()
    saved_maps_fetched: bool = False
    editable_map: GetEditableMapResponse | None = None
    editable_map_fetched: bool = False
    map_update_info: CheckMapUpdateInfoResponse | None = None
    map_update_info_fetched: bool = False
    point_navigation_path: list[tuple[float, float]] = field(default_factory=list)
    point_navigation_target: tuple[float, float] | None = None

    # Vision obstacles (camera-detected transient objects during cleaning)
    # Download/upgrade status
    download_status: int = 0
    upgrade_status_code: int = 0

    # Pause overlay (field 3 sub-field 2 = 1 means paused)
    is_paused: bool = False

    # Dock sub-state (field 3 sub-field 10: 1=docked, 2=docking in progress)
    dock_sub_state: int = 0

    # Returning flag (field 3 sub-field 7: 1=returning to dock)
    # Confirmed via live test: appears when robot is navigating back to dock
    is_returning_to_dock: bool = False

    # Dock activity (field 3 sub-field 12: 2/6 observed when docked)
    dock_activity: int = 0

    # Station activity (field 3 sub-field 18)
    # Observed: 1 during dust gathering, 4 during dock dry/disinfection work.
    station_activity: int = 0

    # Dock presence (field 3 sub-field 3)
    # Values observed: 1=on dock, 2=off dock, 6=on dock (charged idle)
    dock_presence: int = 0

    # APK RobotBaseStatus telecontrol diagnostics. Field 3.19 is the
    # RobotTaskStatus telecontrol status (0=unspecified, 3=point navigation),
    # field 17 reports the telecontrol stage, and field 31 reports the active
    # manual-control mode.
    telecontrol_status: int = int(TelecontrolStatus.UNSPECIFIED)
    telecontrol_stage: int = 0
    manual_control_state: int = 0

    # Newer Flow firmware sub-state (field 3 sub-field 4).
    # Observed during active clean startup/navigation: 8 -> 7 -> 3.
    flow_activity: int = 0

    # Newer Flow firmware task flag (field 3 sub-field 14). Observed as 1
    # during active cleaning/navigation.
    flow_task_flag: int = 0

    # Dock indicator from field 11 (top-level base_status field)
    # Validated via dock_research.py guided test (5 captures):
    #   2 = on dock (all 3 on-dock captures)
    #   1 = off dock (both off-dock captures)
    # Perfect dock correlation — primary STANDBY dock signal.
    dock_field11: int = 0

    # Dock indicator from field 47 (top-level base_status field)
    # Validated via dock_research.py guided test (5 captures):
    #   3 = on dock (all 3 on-dock captures)
    #   2 = off dock (both off-dock captures)
    # Secondary confirmation signal.
    dock_field47: int = 0

    # Raw data for fields we haven't fully decoded yet
    raw_base_status: dict[str, Any] = field(default_factory=dict)
    raw_working_status_value: int | None = None
    raw_working_status: dict[str, Any] = field(default_factory=dict)
    raw_aux_status: dict[str, dict[str, Any]] = field(default_factory=dict)

    def _working_status_is_cleaning_like(self) -> bool:
        """True when the cached working_status looks like a cleaning task."""
        return self.working_status in (
            WorkingStatus.CLEANING,
            WorkingStatus.CLEANING_V2,
            WorkingStatus.CLEANING_ALT,
            WorkingStatus.CLEANING_FLOW2,
        )

    def _dock_fields_indicate_docked(self) -> bool:
        """True when base-status dock fields indicate the robot is on dock."""
        if self.dock_sub_state == 1:
            return True
        if self.dock_activity > 0:
            return True
        if self.station_activity > 0:
            return True
        if self.dock_field11 >= 2:
            return True
        if self.dock_field47 in (1, 3):
            return True
        return False

    @property
    def is_station_active(self) -> bool:
        """True when the base station is running a dock-side task."""
        return self.station_activity > 0 or (
            self.working_status == WorkingStatus.CLEANING_ALT and self.is_docked
        )

    def _set_battery_level(self, battery_level: int) -> None:
        """Update battery level and infer docked state from charging trend."""
        if (
            self.battery_level > 0
            and battery_level > self.battery_level
            and self._working_status_is_cleaning_like()
            and not self.has_recent_active_working_status
        ):
            self.inferred_docked_from_battery = True
        self.battery_level = battery_level

    @property
    def has_recent_active_working_status(self) -> bool:
        """True while working_status is actively reporting task counters."""
        if self.working_status not in ACTIVE_CLEANING_STATUSES:
            return False
        if self.last_active_working_status_time <= 0:
            return False
        return time.monotonic() - self.last_active_working_status_time <= _ACTIVE_WORKING_STATUS_TTL

    @property
    def is_paused_during_active_task(self) -> bool:
        """True only when the pause overlay belongs to a live off-dock task.

        RobotBaseStatus field 3.2 can remain set after a task completes and
        the robot docks. It must not indefinitely block unrelated settings or
        motion preparation after that stale docked state.
        """
        return (
            self.is_paused
            and not self.is_docked
            and (
                self._working_status_is_cleaning_like()
                or self.has_recent_active_working_status
            )
        )

    @property
    def is_cleaning(self) -> bool:
        """True when actively cleaning (not paused, not returning to dock)."""
        if self.has_recent_active_working_status:
            return not self.is_paused and not self.is_returning
        if self._dock_fields_indicate_docked() or self.inferred_docked_from_battery:
            return False
        return (
            self._working_status_is_cleaning_like()
            and not self.is_paused
            and not self.is_returning_to_dock
        )

    @property
    def is_docked(self) -> bool:
        """True when on dock: DOCKED(10), CHARGED(14), DOCKED_V2(2), or dock field signals.

        Dock signals (checked for STANDBY, UNKNOWN, and any unmapped status):
          - dock_sub_state == 1 (field 3.10, old FW only)
          - dock_activity > 0 (field 3.12, old FW only)
          - dock_field11 >= 2 (field 11: old FW 2=docked/1=undocked,
                               v01.07.23 3=docked)
          - dock_field47 in (1, 3) (field 47: old FW 3=docked/2=undocked,
                                    v01.07.23 1=docked)

        Dock fields are checked for STANDBY/UNKNOWN and any status where
        cleaning is not active, since the robot can report unmapped states
        (e.g. self-test) while physically docked.
        """
        if self.has_recent_active_working_status:
            return False
        if self.working_status in (
            WorkingStatus.DOCKED, WorkingStatus.CHARGED, WorkingStatus.DOCKED_V2,
        ):
            return True
        # For STANDBY, UNKNOWN, or any other status: check dock field signals.
        # Values differ across firmware versions:
        #   Old FW: dock_sub_state=1, dock_field11=2, dock_field47=3
        #   v01.07.23.00: dock_sub_state absent, dock_field11=3, dock_field47=1
        #
        # Narwal can keep reporting a stale CLEANING working_status after the
        # active working_status payload has stopped. Once that live payload is
        # no longer recent, dock fields are a better source of truth.
        return self._dock_fields_indicate_docked() or self.inferred_docked_from_battery

    @property
    def is_returning(self) -> bool:
        """True when the robot is actively returning to the dock.

        Live-validated: during return-to-dock, field 3 shows:
          {1=4, 7=1, 10=2} — working_status stays CLEANING(4),
          field 7=1 (returning flag), field 10=2 (docking in progress).

        Requires BOTH field 3.7=1 AND field 3.10=2 to avoid false
        positives — either field alone can be stale during normal
        cleaning (confirmed 2026-03-08: robot cleaning in Pantry
        showed returning=True from a single stale field).

        Only valid while working_status is CLEANING — once the robot
        transitions to STANDBY/DOCKED/CHARGED, it has already docked
        even if field 3.7 is momentarily still set.
        """
        if not self.has_recent_active_working_status and self.working_status not in (
            WorkingStatus.CLEANING,
            WorkingStatus.CLEANING_V2,
            WorkingStatus.CLEANING_ALT,
            WorkingStatus.CLEANING_FLOW2,
        ):
            return False
        return self.is_returning_to_dock and self.dock_sub_state == 2

    def update_from_working_status(self, decoded: dict[str, Any]) -> None:
        """Update state from a decoded working_status message.

        Confirmed via 35-min monitor capture (2026-02-27):
          Field 3  = current session elapsed time (seconds)
                     (confirmed: 2136→2159 over 35-min clean)
          Field 13 = cleaning area (cm²) — CONFIRMED (18000 = 1.8m²)
          Field 15 = 600 during cleaning (purpose uncertain)
        """
        self.raw_working_status = decoded
        previous_cleaning_time = self.cleaning_time
        previous_cleaning_area = self.cleaning_area
        if "3" in decoded:
            try:
                self.cleaning_time = int(decoded["3"])
            except (ValueError, TypeError):
                pass
        if "13" in decoded:
            self.cleaning_area = int(decoded["13"])
        if "15" in decoded:
            # Field 15 may be cumulative time; prefer field 3 for current session
            pass
        has_active_payload = any(
            _positive_int_field(decoded, field) for field in ("3", "13")
        )
        active_payload_changed = (
            self.cleaning_time != previous_cleaning_time
            or self.cleaning_area != previous_cleaning_area
        )
        if has_active_payload and active_payload_changed:
            self.last_active_working_status_time = time.monotonic()
            self.inferred_docked_from_battery = False
        if (
            has_active_payload
            and active_payload_changed
            and self.working_status
            in (
                WorkingStatus.UNKNOWN,
                WorkingStatus.STANDBY,
                WorkingStatus.DOCKED,
                WorkingStatus.CHARGED,
                WorkingStatus.DOCKED_V2,
            )
        ):
            self.working_status = WorkingStatus.CLEANING
            self.dock_field11 = 1
            self.dock_field47 = 2
            self.dock_sub_state = 0
            self.dock_activity = 0
            self.station_activity = 0

    def update_from_base_status(self, decoded: dict[str, Any]) -> None:
        """Update state from a decoded robot_base_status message.

        Battery (confirmed via 35-min monitor capture):
          Field 2  = real-time battery as IEEE 754 float32
                     (1118175232 → 83.0%, matching app ~84%)
          Field 38 = static battery health (always 100; design capacity)

        Field 3 sub-fields (confirmed via live test):
          3.1  = WorkingStatus enum
          3.2  = 1 means PAUSED
          3.7  = 1 means RETURNING to dock (live-validated)
          3.10 = dock sub-state (1=docked, 2=docking in progress)
          3.12 = dock activity (values 2, 6 observed)
          3.18 = station activity (1=dust gathering, 4=dry/disinfection observed)
          3.19 = telecontrol status (0=unspecified, 3=point navigation)

        Dock indicators (validated via dock_research.py, 5 captures):
          Field 11 = 2 when docked, 1 when undocked
          Field 47 = 3 when docked, 2 when undocked

        Note: field 32 mirrors field 3 exactly (redundant).
        """
        self.raw_base_status = decoded
        if "17" in decoded:
            try:
                self.telecontrol_stage = int(decoded["17"])
            except (ValueError, TypeError):
                self.telecontrol_stage = 0
        if "31" in decoded:
            try:
                self.manual_control_state = int(decoded["31"])
            except (ValueError, TypeError):
                self.manual_control_state = 0
        # Field 11 = dock indicator (2=docked, 1=undocked)
        if "11" in decoded:
            try:
                self.dock_field11 = int(decoded["11"])
            except (ValueError, TypeError):
                self.dock_field11 = 0
        # Field 47 = dock indicator (3=docked, 2=undocked)
        if "47" in decoded:
            try:
                self.dock_field47 = int(decoded["47"])
            except (ValueError, TypeError):
                self.dock_field47 = 0
        # Field 3 is a nested message: {1: state_int, ...}
        # Sub-field layout differs across firmware versions:
        #   Old FW: {1: ws, 2: paused, 3: dock_presence, 7: returning,
        #            10: dock_sub, 12: dock_activity}
        #   v01.07.23+: {1: ws, 4: ?, 11: ?} — sub-fields 2/3/7/10/12 absent
        # bbp may also return a list for repeated messages.
        field3 = decoded.get("3")
        if isinstance(field3, list):
            field3 = field3[0] if field3 else None
        if isinstance(field3, dict):
            telecontrol_status = field3.get("19")
            if isinstance(telecontrol_status, int) and not isinstance(
                telecontrol_status, bool
            ):
                self.telecontrol_status = telecontrol_status
            if "1" in field3:
                try:
                    self.raw_working_status_value = int(field3["1"])
                except (ValueError, TypeError):
                    self.raw_working_status_value = None
                try:
                    if self.raw_working_status_value is None:
                        raise ValueError("working status is not numeric")
                    self.working_status = WorkingStatus(self.raw_working_status_value)
                except (ValueError, TypeError):
                    raw_val = field3["1"]
                    _LOGGER.warning(
                        "Unknown working_status value: %s — treating as UNKNOWN. "
                        "Please report this value at the GitHub repo.",
                        raw_val,
                    )
                    self.working_status = WorkingStatus.UNKNOWN
            # Sub-field 2: paused overlay (0 or absent = not paused, 1 = paused)
            self.is_paused = bool(field3.get("2"))
            # Sub-field 7: returning to dock on old FW (value 1 = returning).
            # On newer FW, field 7 is repurposed (e.g. value 7 during cleaning).
            # Only treat value 1 as returning — other values are not the flag.
            self.is_returning_to_dock = field3.get("7") == 1
            if "10" in field3:
                try:
                    self.dock_sub_state = int(field3["10"])
                except (ValueError, TypeError):
                    pass
            if "12" in field3:
                try:
                    self.dock_activity = int(field3["12"])
                except (ValueError, TypeError):
                    pass
            self.station_activity = 0
            if "18" in field3:
                try:
                    self.station_activity = int(field3["18"])
                except (ValueError, TypeError):
                    pass
            if "3" in field3:
                try:
                    self.dock_presence = int(field3["3"])
                except (ValueError, TypeError):
                    pass
            self.flow_activity = 0
            if "4" in field3:
                try:
                    self.flow_activity = int(field3["4"])
                except (ValueError, TypeError):
                    pass
            self.flow_task_flag = 0
            if "14" in field3:
                try:
                    self.flow_task_flag = int(field3["14"])
                except (ValueError, TypeError):
                    pass
            if self.working_status in ACTIVE_CLEANING_STATUSES:
                if "11" not in decoded:
                    self.dock_field11 = 1
                if "47" not in decoded:
                    self.dock_field47 = 2
                if "10" not in field3:
                    self.dock_sub_state = 0
                if "12" not in field3:
                    self.dock_activity = 0
                self.inferred_docked_from_battery = False
            # Log unrecognized sub-fields for future firmware mapping
            _known_f3 = {"1", "2", "3", "4", "7", "10", "11", "12", "14", "18"}
            _unknown_f3 = set(field3.keys()) - _known_f3
            if _unknown_f3:
                _LOGGER.debug(
                    "field3 unrecognized sub-fields: %s",
                    {k: field3[k] for k in sorted(_unknown_f3)},
                )
        elif field3 is not None:
            _LOGGER.warning(
                "field3 is %s (expected dict): %r — state may not update. "
                "Please report this at the GitHub repo.",
                type(field3).__name__, field3,
            )
        explicitly_off_dock = (
            ("11" in decoded and self.dock_field11 == 1)
            or ("47" in decoded and self.dock_field47 == 2)
        )
        if not self.is_returning_to_dock and explicitly_off_dock:
            self.dock_sub_state = 0
            self.dock_activity = 0
        if "2" in decoded:
            # Field 2 = real-time battery SOC as float32
            # (e.g. 1118175232 → 83.0%; bbp may return int or float)
            bat = _to_float32(decoded["2"])
            if bat is not None:
                self._set_battery_level(round(bat))
        if explicitly_off_dock:
            self.inferred_docked_from_battery = False
        if "38" in decoded:
            # Field 38 = static battery health (always 100, design capacity)
            self.battery_health = int(decoded["38"])
        if "36" in decoded:
            self.timestamp = int(decoded["36"])
        if "13" in decoded:
            raw = decoded["13"]
            if isinstance(raw, bytes):
                self.session_id = raw.decode("utf-8", errors="replace")
            else:
                self.session_id = str(raw)
                if self.session_id.startswith("b'"):
                    self.session_id = self.session_id[2:-1]

    def update_battery_from_base_status(self, decoded: dict[str, Any]) -> None:
        """Update ONLY hardware-sampled fields from a base_status response.

        Used when the robot is not broadcasting (deep sleep on dock).
        In this mode, get_status() returns current battery (hardware counter)
        but stale working_status (firmware cache from last active session).
        We update only the fields we can trust.
        """
        self.raw_base_status = decoded
        if "2" in decoded:
            bat = _to_float32(decoded["2"])
            if bat is not None:
                self._set_battery_level(round(bat))
        if "38" in decoded:
            self.battery_health = int(decoded["38"])
        if "36" in decoded:
            self.timestamp = int(decoded["36"])

    def update_from_upgrade_status(self, decoded: dict[str, Any]) -> None:
        """Update state from a decoded upgrade_status message."""
        if "7" in decoded:
            raw = decoded["7"]
            if isinstance(raw, bytes):
                self.firmware_version = raw.decode("utf-8", errors="replace")
            else:
                self.firmware_version = str(raw)
                if self.firmware_version.startswith("b'"):
                    self.firmware_version = self.firmware_version[2:-1]
        if "8" in decoded:
            raw = decoded["8"]
            if isinstance(raw, bytes):
                self.firmware_target = raw.decode("utf-8", errors="replace")
            else:
                self.firmware_target = str(raw)
                if self.firmware_target.startswith("b'"):
                    self.firmware_target = self.firmware_target[2:-1]
        if "4" in decoded:
            self.upgrade_status_code = int(decoded["4"])

    def update_from_download_status(self, decoded: dict[str, Any]) -> None:
        """Update state from a decoded download_status message."""
        if "1" in decoded:
            self.download_status = int(decoded["1"])

    def update_from_aux_status(self, topic: str, decoded: dict[str, Any]) -> None:
        """Store decoded status payloads that are not mapped yet."""
        self.raw_aux_status[topic] = decoded
        if topic in {TOPIC_ROBOT_TASK_STATUS, TOPIC_CMD_GET_ROBOT_TASK_STATUS}:
            payload = decoded.get("2")
            if not isinstance(payload, dict):
                return
            progress = _optional_int(payload.get("1"))
            if progress is not None:
                self.task_progress_percent = max(0, min(100, progress))
            elapsed = _optional_int(payload.get("2"))
            if elapsed is not None:
                self.task_elapsed_time = elapsed
            room = payload.get("6")
            if not isinstance(room, dict):
                room = payload.get("8")
            if isinstance(room, dict):
                self.current_room_id = _optional_int(room.get("1"))
                name = room.get("3")
                if isinstance(name, (bytes, bytearray)):
                    self.current_room_name = bytes(name).decode(
                        "utf-8", errors="replace"
                    )
                else:
                    self.current_room_name = str(name) if name else ""
                    if self.current_room_name.startswith(
                        "b'"
                    ) and self.current_room_name.endswith("'"):
                        self.current_room_name = self.current_room_name[2:-1]
                if self.current_room_id is not None and self.map_data is not None:
                    map_room = next(
                        (
                            candidate
                            for candidate in self.map_data.rooms
                            if candidate.room_id == self.current_room_id
                        ),
                        None,
                    )
                    if map_room is not None:
                        self.current_room_name = map_room.display_name
        elif topic == "supply/get_dry_mop_remain_time":
            self.dry_mop_remaining_time = _optional_int(decoded.get("2"))
