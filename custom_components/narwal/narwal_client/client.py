"""WebSocket client for Narwal robot vacuum."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from collections import deque
from collections.abc import Callable
from dataclasses import replace
from typing import Any

import websockets
import websockets.exceptions

from .capabilities import CapabilityMap, normalize_feature_response
from .config import (
    ConfigSnapshot,
    SetConfigPatch,
    decode_get_config_response,
    encode_set_config_patch,
)
from .const import (
    BROADCAST_STALE_TIMEOUT,
    COMMAND_RESPONSE_TIMEOUT,
    DEFAULT_PORT,
    DEFAULT_TOPIC_PREFIX,
    HEARTBEAT_INTERVAL,
    KEEPALIVE_INTERVAL,
    KNOWN_PRODUCT_KEYS,
    LEGACY_ROOM_CLEAN_PRODUCT_KEYS,
    RECONNECT_BACKOFF_FACTOR,
    RECONNECT_INITIAL_DELAY,
    RECONNECT_MAX_DELAY,
    TOPIC_CMD_ACTIVE_ROBOT,
    TOPIC_CMD_APP_HEARTBEAT,
    TOPIC_CMD_CANCEL,
    TOPIC_CMD_CHECK_MAP_UPDATE_INFO,
    TOPIC_CMD_CLEAN_TASK,
    TOPIC_CMD_DRY_DUST_BAG,
    TOPIC_CMD_DRY_MOP,
    TOPIC_CMD_DRY_STATION_BAG,
    TOPIC_CMD_DUST_GATHERING,
    TOPIC_CMD_EASY_CLEAN,
    TOPIC_CMD_FORCE_END,
    TOPIC_CMD_GET_ALL_MAPS,
    TOPIC_CMD_GET_BASE_STATUS,
    TOPIC_CMD_GET_CLEAN_PLANS,
    TOPIC_CMD_GET_CLEAN_PROGRESS_INFO,
    TOPIC_CMD_GET_CLEAN_SCHEDULES,
    TOPIC_CMD_GET_CLEAN_TIMELINE,
    TOPIC_CMD_GET_CONFIG,
    TOPIC_CMD_GET_CONSUMABLE_INFO,
    TOPIC_CMD_GET_CURRENT_CLEAN_PLAN,
    TOPIC_CMD_GET_CURRENT_TASK,
    TOPIC_CMD_GET_CURRENT_VOICE_INFO,
    TOPIC_CMD_GET_DEVICE_INFO,
    TOPIC_CMD_GET_DRY_MOP_REMAIN_TIME,
    TOPIC_CMD_GET_EDITABLE_MAP,
    TOPIC_CMD_GET_FEATURE_LIST,
    TOPIC_CMD_GET_FIRMWARE_VERSION,
    TOPIC_CMD_GET_LANGUAGE,
    TOPIC_CMD_GET_MAP,
    TOPIC_CMD_GET_ROBOT_TASK_STATUS,
    TOPIC_CMD_GET_SUPPORTED_LANGUAGES,
    TOPIC_CMD_NOTIFY_APP_EVENT,
    TOPIC_CMD_PAUSE,
    TOPIC_CMD_PLAN_START,
    TOPIC_CMD_POINT_NAVI,
    TOPIC_CMD_RECALL,
    TOPIC_CMD_RESUME,
    TOPIC_CMD_SET_CONFIG,
    TOPIC_CMD_SET_FAN_LEVEL,
    TOPIC_CMD_SET_LED,
    TOPIC_CMD_SET_MANUAL_CONTROL_MODE,
    TOPIC_CMD_SET_MOP_HUMIDITY,
    TOPIC_CMD_TAKE_PICTURE,
    TOPIC_CMD_UPDATE_CLEAN_SCHEDULE,
    TOPIC_CMD_VELOCITY_CONTROL,
    TOPIC_CMD_WASH_AND_DRY_MOP,
    TOPIC_CMD_WASH_MOP,
    TOPIC_CMD_WASH_MOP_BY_ROBOT_STATUS,
    TOPIC_CMD_YELL,
    TOPIC_PLANNING_DEBUG,
    TOPIC_POINT_NAVI_PLAN_TRAJ,
    TOPIC_ROBOT_CURRENT_STATUS,
    TOPIC_ROBOT_STATUS,
    TOPIC_ROBOT_TASK_STATUS,
    TOPIC_TIMELINE_STATUS,
    WAKE_TIMEOUT,
    CleaningRoute,
    CommandResult,
    FanLevel,
    ManualControlMode,
    MopHumidity,
    MopStrengthLevel,
    TelecontrolStatus,
    WorkingStatus,
    WorkMode,
)
from .consumables import (
    GetConsumableInfoResponse,
    decode_get_consumable_info_response,
)
from .device_metadata import (
    FirmwareVersionResponse,
    GetCurrentVoiceInfoResponse,
    GetLanguageResponse,
    GetSupportedLanguagesResponse,
    decode_get_current_voice_info_response,
    decode_get_firmware_version_response,
    decode_get_language_response,
    decode_get_supported_languages_response,
)
from .history import (
    GetCleanTimeLineResponse,
    decode_get_clean_time_line_response,
    encode_get_clean_time_line_request,
)
from .map_inventory import (
    CheckMapUpdateInfoResponse,
    GetAllReducedMapsResponse,
    GetEditableMapRequest,
    GetEditableMapResponse,
    MapRequestFormat,
    decode_check_map_update_info_response,
    decode_get_all_reduced_maps_response,
    decode_get_editable_map_response,
    encode_get_editable_map_request,
)
from .models import CommandResponse, DeviceInfo, MapData, MapDisplayData, NarwalState
from .plan import (
    CleanPlansResponse,
    CurrentPlanResponse,
    decode_clean_plans_response,
    decode_current_plan_response,
)
from .protocol import (
    PROTOBUF_FIELD5_TAG,
    NarwalMessage,
    ProtocolError,
    build_frame,
    parse_frame,
)
from .schedule import (
    GetCleanSchedulesResponse,
    ScheduleError,
    UpdateCleanScheduleRequest,
    decode_get_clean_schedules_response,
    decode_update_clean_schedule_response,
    encode_update_clean_schedule_request,
)
from .task import CurrentCleanTask, decode_current_task_response
from .telecontrol import (
    Point,
    PoseData,
    TelecontrolCodecError,
    decode_point_navi_plan_traj,
    encode_cancel_navigation_request,
    encode_point_navi_request,
    encode_set_manual_control_mode,
    encode_telecontrol_velocity,
)

_LOGGER = logging.getLogger(__name__)

_ACTIVE_WORKING_STATUS_TTL = 15.0
_STALE_DOCK_BASE_STATUSES = {
    WorkingStatus.UNKNOWN,
    WorkingStatus.STANDBY,
    WorkingStatus.DOCKED,
    WorkingStatus.CHARGED,
    WorkingStatus.DOCKED_V2,
}
_AUX_STATUS_TOPICS = {
    TOPIC_TIMELINE_STATUS,
    TOPIC_POINT_NAVI_PLAN_TRAJ,
    TOPIC_PLANNING_DEBUG,
    TOPIC_ROBOT_STATUS,
    TOPIC_ROBOT_CURRENT_STATUS,
    TOPIC_ROBOT_TASK_STATUS,
}
_MAX_RETAINED_RESPONSES = 64
_MANUAL_CONTROL_HEARTBEAT_INTERVAL = 0.1
_MAX_MANUAL_CONTROL_COMMAND = 10
_MAX_MANUAL_CONTROL_PULSE_SECONDS = 0.5
_POINT_NAVI_PRODUCTION_EXPLORE_MODE = 2


def _is_response_message(message: NarwalMessage) -> bool:
    """Return whether a parsed frame is a command response.

    Current frames expose response routing in ``Header.properties`` and may
    start with any Header field (for example UUID field 2).  The field-5 check
    is retained only for historical direct response-topic envelopes.
    """
    properties = message.header.properties
    if properties is not None and (
        properties.response_url is not None
        or properties.correlation_data is not None
    ):
        return True
    return (
        message.field_tag == PROTOBUF_FIELD5_TAG
        and message.header.url is None
    )


def _normalise_response_topic(topic: str) -> str:
    """Normalise an absolute/short topic and remove its response suffix."""
    normalised = "/".join(part for part in topic.strip().split("/") if part)
    if normalised.endswith("/response"):
        normalised = normalised[: -len("/response")]
    return normalised


def _response_matches_topic(
    message: NarwalMessage,
    *,
    expected_full_topic: str,
    expected_short_topic: str,
) -> bool:
    """Return whether a routed response belongs to the active command.

    A response URL is authoritative when supplied.  Correlation-only frames
    cannot be matched because this client deliberately continues to send the
    robot-compatible URL-only request Header.  A field-5 frame without routing
    metadata remains a narrow FIFO fallback for older firmware.
    """
    response_url = message.header.response_url
    if response_url is None:
        if message.header.correlation_data is not None:
            return False
        return (
            message.field_tag == PROTOBUF_FIELD5_TAG
            and message.header.url is None
        )

    response_topic = _normalise_response_topic(response_url)
    expected_full = _normalise_response_topic(expected_full_topic)
    expected_short = _normalise_response_topic(expected_short_topic)
    return (
        response_topic in (expected_full, expected_short)
        or response_topic.endswith(f"/{expected_short}")
    )


def _short_repr(value: Any, limit: int = 1200) -> str:
    text = repr(value)
    if len(text) <= limit:
        return text
    return f"{text[:limit]}…"


def _normalise_blackboxprotobuf_typedef(typedef: dict[str, Any]) -> dict[str, Any]:
    """Add field names expected by some blackboxprotobuf releases."""
    for info in typedef.values():
        info.setdefault("name", "")
        message_typedef = info.get("message_typedef")
        if isinstance(message_typedef, dict):
            _normalise_blackboxprotobuf_typedef(message_typedef)
        alt_typedefs = info.get("alt_typedefs")
        if isinstance(alt_typedefs, dict):
            for alt_typedef in alt_typedefs.values():
                if isinstance(alt_typedef, dict):
                    _normalise_blackboxprotobuf_typedef(alt_typedef)
    return typedef


def _base_status_working_status(decoded: dict[str, Any] | object) -> WorkingStatus | None:
    """Extract robot_base_status field 3.1."""
    if not isinstance(decoded, dict):
        return None
    field3 = decoded.get("3")
    if isinstance(field3, list):
        field3 = field3[0] if field3 else None
    if not isinstance(field3, dict) or "1" not in field3:
        return None
    try:
        return WorkingStatus(int(field3["1"]))
    except (TypeError, ValueError):
        return None


def _base_status_telecontrol_status(
    decoded: dict[str, Any] | object,
) -> int | None:
    """Extract an explicitly encoded RobotTaskStatus field 3.19."""
    if not isinstance(decoded, dict):
        return None
    field3 = decoded.get("3")
    if isinstance(field3, list):
        field3 = field3[0] if field3 else None
    if not isinstance(field3, dict) or "19" not in field3:
        return None
    value = field3["19"]
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _full_base_status_task(
    decoded: dict[str, Any] | object,
) -> dict[str, Any] | None:
    """Return a complete base-status task block, or ``None`` if incomplete."""
    if not isinstance(decoded, dict) or not decoded:
        return None
    field3 = decoded.get("3")
    if isinstance(field3, list):
        field3 = field3[0] if field3 else None
    if not isinstance(field3, dict):
        return None
    working_status = field3.get("1")
    if isinstance(working_status, bool) or not isinstance(working_status, int):
        return None
    return field3


def _base_status_confirms_docked(
    decoded: dict[str, Any] | object, status: WorkingStatus | None
) -> bool:
    """Return true when a terminal status also carries live dock indicators."""
    if not isinstance(decoded, dict) or status not in {
        WorkingStatus.STANDBY,
        WorkingStatus.DOCKED,
        WorkingStatus.CHARGED,
        WorkingStatus.DOCKED_V2,
    }:
        return False
    field3 = decoded.get("3")
    if isinstance(field3, list):
        field3 = field3[0] if field3 else None
    field3 = field3 if isinstance(field3, dict) else {}

    def int_field(container: dict[str, Any], field: str) -> int:
        try:
            return int(container.get(field, 0))
        except (TypeError, ValueError):
            return 0

    return (
        int_field(decoded, "11") >= 2
        or int_field(decoded, "47") in (1, 3)
        or int_field(field3, "3") in (1, 6)
        or int_field(field3, "10") == 1
        or int_field(field3, "12") > 0
        or int_field(field3, "18") > 0
    )


class NarwalConnectionError(Exception):
    """Raised when connection to the vacuum fails."""


class NarwalCommandError(Exception):
    """Raised when a command fails or times out."""


class NarwalClient:
    """Async WebSocket client for communicating with a Narwal vacuum.

    Usage:
        client = NarwalClient(host="192.168.1.100", device_id="your_device_id")
        await client.connect()
        client.on_state_update = my_callback
        await client.start_listening()
        # ...later...
        await client.disconnect()
    """

    def __init__(
        self,
        host: str,
        port: int = DEFAULT_PORT,
        device_id: str = "",
        topic_prefix: str | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.device_id = device_id
        self.url = f"ws://{host}:{port}"
        self.topic_prefix = topic_prefix or DEFAULT_TOPIC_PREFIX
        self.state = NarwalState()
        self.on_state_update: Callable[[NarwalState], None] | None = None
        self.on_message: Callable[[NarwalMessage], None] | None = None

        self._ws: Any = None
        self._listen_task: asyncio.Task[None] | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._keepalive_task: asyncio.Task[None] | None = None
        self._connected = asyncio.Event()
        self._should_reconnect = True
        self._listener_active = False  # True when start_listening() is running recv loop
        self._robot_awake = False  # True once we receive a broadcast
        self._last_broadcast_time: float = 0.0  # monotonic time of last broadcast
        self._last_status_time: float = 0.0  # monotonic time of last status/base broadcast
        self._last_display_map_time: float = 0.0  # monotonic time of last display_map
        self._last_active_working_status_time: float = 0.0
        self._last_aux_log_time: dict[str, float] = {}
        self._last_base_status_log: tuple[Any, Any, Any] | None = None
        # Queue for command responses classified from Header routing metadata,
        # with a narrow field-5 fallback for old firmware.
        self._response_queue: asyncio.Queue[NarwalMessage] = asyncio.Queue()
        # Keep routed frames which cannot belong to the active request. They
        # are intentionally not reused by a later request: without sending a
        # request UUID, an already-received frame is necessarily stale.
        self._retained_responses: deque[NarwalMessage] = deque(
            maxlen=_MAX_RETAINED_RESPONSES
        )
        # Lock to prevent concurrent send_command calls from racing on the queue
        self._command_lock = asyncio.Lock()
        # Keep config/set and its mandatory config/get readback atomic with
        # respect to other writes made through this client.
        self._config_write_lock = asyncio.Lock()
        # A schedule toggle is a read-modify-write operation.  Keep its
        # mandatory fresh read and full readback together so concurrent
        # callers cannot overwrite one another with stale schedule fields.
        self._schedule_write_lock = asyncio.Lock()
        # Serialize client-owned motion so cleanup cannot race another pulse or
        # point-navigation request.
        self._telecontrol_lock = asyncio.Lock()
        self._manual_control_abort = asyncio.Event()
        self._manual_control_active = False
        self._point_navigation_active = False
        self._point_navigation_frame_sent = False
        self._point_navigation_seen_active = False
        self._point_navigation_stop_confirmation_pending = False
        self._point_navigation_start_pending = False
        self._point_navigation_completed_before_ack = False
        self._manual_control_state = int(ManualControlMode.OFF)
        self._telecontrol_status = int(TelecontrolStatus.UNSPECIFIED)
        self._telecontrol_stop_generation = 0
        self._point_navigation_path: tuple[tuple[float, float], ...] = ()

    def _full_topic(self, short_topic: str) -> str:
        """Build the full topic path."""
        return f"{self.topic_prefix}/{self.device_id}/{short_topic}"

    @property
    def connected(self) -> bool:
        """Return True if the WebSocket is currently connected."""
        return self._ws is not None and self._connected.is_set()

    @property
    def robot_awake(self) -> bool:
        """Return True if the robot is actively broadcasting."""
        return self._robot_awake

    @property
    def manual_control_active(self) -> bool:
        """Return whether this client currently owns a joystick pulse."""
        return self._manual_control_active

    @property
    def point_navigation_active(self) -> bool:
        """Return whether this client owns an uncancelled point navigation."""
        return self._point_navigation_active

    @property
    def manual_control_state(self) -> int:
        """Return the last RobotBaseStatus.manualControlStatus value."""
        return self._manual_control_state

    @property
    def telecontrol_status(self) -> int:
        """Return the last explicit RobotTaskStatus.telecontrolStatus value."""
        return self._telecontrol_status

    @property
    def telecontrol_stop_generation(self) -> int:
        """Return the generation incremented synchronously by public stops."""
        return self._telecontrol_stop_generation

    @property
    def point_navigation_path(self) -> tuple[tuple[float, float], ...]:
        """Return the last schema-decoded point-navigation trajectory."""
        return self._point_navigation_path

    @property
    def last_broadcast_age(self) -> float:
        """Seconds since last broadcast (0.0 if none received yet)."""
        if self._last_broadcast_time <= 0:
            return 0.0
        return time.monotonic() - self._last_broadcast_time

    @property
    def last_display_map_age(self) -> float:
        """Seconds since last display_map broadcast (999.0 if none received)."""
        if self._last_display_map_time <= 0:
            return 999.0
        return time.monotonic() - self._last_display_map_time

    @property
    def last_status_age(self) -> float:
        """Seconds since last status/base broadcast (999.0 if none received)."""
        if self._last_status_time <= 0:
            return 999.0
        return time.monotonic() - self._last_status_time

    def _active_working_status_is_recent(self, now: float | None = None) -> bool:
        """Return true while fresh working_status telemetry is contradicting base_status."""
        if self._last_active_working_status_time <= 0:
            return False
        now = time.monotonic() if now is None else now
        return now - self._last_active_working_status_time <= _ACTIVE_WORKING_STATUS_TTL

    def _state_needs_keepalive(self) -> bool:
        """Return true when the app-style keepalive should keep the robot awake."""
        state = self.state
        if state.working_status == WorkingStatus.UNKNOWN:
            return True
        if state.working_status == WorkingStatus.ERROR:
            return True
        if state.is_cleaning or state.is_returning:
            return True
        if state.is_station_active:
            return True
        if (
            state.is_paused
            and state._working_status_is_cleaning_like()
            and not state.is_docked
        ):
            return True
        if state.working_status == WorkingStatus.CLEANING_ALT and state.is_docked:
            return True
        return not state.is_docked

    def _update_from_working_status_broadcast(
        self, decoded: dict[str, Any], now: float | None = None
    ) -> None:
        """Update state from a working_status broadcast."""
        self.state.update_from_working_status(decoded)
        if self.state.has_recent_active_working_status:
            self._last_active_working_status_time = (
                self.state.last_active_working_status_time
            )

    def _clear_point_navigation_ownership(self) -> None:
        """Clear every client-owned point-navigation overlay."""
        self._point_navigation_active = False
        self._point_navigation_frame_sent = False
        self._point_navigation_seen_active = False
        self._point_navigation_stop_confirmation_pending = False
        self._point_navigation_start_pending = False
        self._point_navigation_completed_before_ack = False
        self._point_navigation_path = ()
        self.state.point_navigation_path = []
        self.state.point_navigation_target = None

    def _update_observed_telecontrol_state(
        self,
        decoded: dict[str, Any],
        *,
        clear_missing: bool = False,
    ) -> None:
        """Synchronize explicit base-status telecontrol fields and lifecycle."""
        manual_control_state = decoded.get("31")
        if isinstance(manual_control_state, int) and not isinstance(
            manual_control_state, bool
        ):
            self._manual_control_state = manual_control_state
            self.state.manual_control_state = manual_control_state
        elif clear_missing:
            self._manual_control_state = int(ManualControlMode.OFF)
            self.state.manual_control_state = int(ManualControlMode.OFF)

        telecontrol_status = _base_status_telecontrol_status(decoded)
        if telecontrol_status is None:
            if not clear_missing:
                return
            telecontrol_status = int(TelecontrolStatus.UNSPECIFIED)
        self._telecontrol_status = telecontrol_status
        self.state.telecontrol_status = telecontrol_status
        if telecontrol_status == int(TelecontrolStatus.POINT_NAVI):
            if (
                self._point_navigation_active
                or self._point_navigation_start_pending
            ):
                self._point_navigation_seen_active = True
            return
        if self._point_navigation_stop_confirmation_pending:
            return
        if not self._point_navigation_seen_active:
            return
        if self._point_navigation_active:
            self._clear_point_navigation_ownership()
        elif self._point_navigation_start_pending:
            self._point_navigation_completed_before_ack = True

    def _update_from_base_status_broadcast(
        self, decoded: dict[str, Any], now: float | None = None
    ) -> None:
        """Update state from robot_base_status, ignoring stale dock overlays mid-task."""
        now = time.monotonic() if now is None else now
        base_status = _base_status_working_status(decoded)
        # AX15 omits both telecontrol fields after leaving manual control
        # instead of broadcasting explicit zero values. A fresh non-telecontrol
        # working state therefore confirms OFF/UNSPECIFIED.
        self._update_observed_telecontrol_state(
            decoded,
            clear_missing=(
                base_status is not None
                and base_status != WorkingStatus.TELECONTROL
            ),
        )
        signature = (decoded.get("3"), decoded.get("11"), decoded.get("47"))
        if signature != self._last_base_status_log:
            self._last_base_status_log = signature
            _LOGGER.debug(
                "%s robot_base_status field3=%r field11=%r field47=%r",
                self.host,
                decoded.get("3"),
                decoded.get("11"),
                decoded.get("47"),
            )
        if (
            base_status in _STALE_DOCK_BASE_STATUSES
            and self._active_working_status_is_recent(now)
            and not _base_status_confirms_docked(decoded, base_status)
        ):
            _LOGGER.debug(
                "Ignoring stale %s base_status while active working_status is fresh",
                base_status.name,
            )
            self.state.update_battery_from_base_status(decoded)
            return
        self.state.update_from_base_status(decoded)

    def _update_from_aux_status_broadcast(
        self, short_topic: str, decoded: dict[str, Any]
    ) -> None:
        self.state.update_from_aux_status(short_topic, decoded)
        now = time.monotonic()
        if now - self._last_aux_log_time.get(short_topic, 0.0) > 30.0:
            self._last_aux_log_time[short_topic] = now
            _LOGGER.debug("%s decoded status: %s", short_topic, _short_repr(decoded))

    def _update_point_navigation_trajectory(self, payload: bytes) -> None:
        """Decode and retain the schema-backed planned path."""
        try:
            trajectory = decode_point_navi_plan_traj(payload)
        except TelecontrolCodecError as err:
            _LOGGER.debug("Invalid point-navigation trajectory: %s", err)
            return
        self._point_navigation_path = tuple(
            (point.x, point.y) for point in trajectory.points
        )
        self.state.point_navigation_path = list(self._point_navigation_path)

    async def connect(self) -> None:
        """Establish WebSocket connection to the vacuum.

        Raises:
            NarwalConnectionError: If connection cannot be established.
        """
        try:
            self._ws = await websockets.connect(
                self.url, ping_interval=30, ping_timeout=10
            )
            self._connected.set()
            _LOGGER.info("Connected to Narwal vacuum at %s", self.url)
        except (OSError, websockets.exceptions.WebSocketException) as e:
            raise NarwalConnectionError(
                f"Failed to connect to {self.url}: {e}"
            ) from e

    async def discover_device_id(self, timeout: float = 15.0) -> str:
        """Discover the device_id by waking the robot and reading its response.

        The robot sleeps when idle and won't broadcast until woken. This method
        sends a get_device_info command (with empty device_id) as a wake signal.
        The robot's local WebSocket server processes commands regardless of the
        device_id in the topic. The response contains the real device_id.

        Falls back to extracting device_id from broadcast topics if the
        command response doesn't contain it.

        Args:
            timeout: Seconds to wait for discovery.

        Returns:
            The device_id string.

        Raises:
            NarwalConnectionError: If not connected.
            NarwalCommandError: If discovery fails within timeout.
        """
        if not self.connected:
            raise NarwalConnectionError("Not connected to vacuum")

        # Build wake frames using all known product key prefixes.
        # The robot only responds to commands with its correct product key
        # in the topic. Since we don't know the model yet, try all known
        # keys until one provokes a response.
        cmd = TOPIC_CMD_GET_DEVICE_INFO
        wake_frames = [
            build_frame(self._full_topic(cmd), b""),  # current prefix (default or user-set)
            build_frame(f"//{cmd}", b""),  # bare topic, no prefix
        ]
        # Add frames for all known product keys (skip default, already included)
        for key in KNOWN_PRODUCT_KEYS:
            if key != self.topic_prefix.lstrip("/"):
                wake_frames.append(
                    build_frame(f"/{key}/{self.device_id}/{cmd}", b"")
                )
        # Send first batch (default + bare + first few known keys)
        batch_size = min(5, len(wake_frames))
        for frame in wake_frames[:batch_size]:
            try:
                await self._ws.send(frame)
            except Exception as e:
                _LOGGER.warning("Failed to send wake command: %s", e)
        _LOGGER.debug(
            "Sent discovery wake commands (%d prefixes, device_id='%s')",
            batch_size, self.device_id,
        )

        wake_index = 0  # cycle through wake frames on retry
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            remaining = deadline - asyncio.get_event_loop().time()
            if remaining <= 0:
                break
            try:
                data = await asyncio.wait_for(
                    self._ws.recv(), timeout=min(remaining, 2.0)
                )
            except asyncio.TimeoutError:
                # Re-send wake commands, cycling through prefixes
                try:
                    await self._ws.send(wake_frames[wake_index % len(wake_frames)])
                    wake_index += 1
                    _LOGGER.debug("Re-sent wake-up command (variant %d)", wake_index)
                except Exception:
                    pass
                continue

            if not isinstance(data, bytes) or len(data) < 4:
                continue

            try:
                msg = parse_frame(data)
            except ProtocolError:
                continue

            # get_device_info responses return device_id in payload field 2.
            if _is_response_message(msg) and msg.payload:
                if not _response_matches_topic(
                    msg,
                    expected_full_topic=self._full_topic(cmd),
                    expected_short_topic=cmd,
                ):
                    self._retain_response(msg)
                    continue
                try:
                    decoded = self._decode_protobuf(msg.payload)
                    raw_id = decoded.get("2", b"")
                    if isinstance(raw_id, bytes):
                        raw_id = raw_id.decode("utf-8", errors="replace").strip()
                    else:
                        raw_id = str(raw_id).strip()
                    if raw_id:
                        parts = msg.topic.split("/") if msg.topic else []
                        if len(parts) >= 2 and parts[1]:
                            self.topic_prefix = f"/{parts[1]}"
                        self.device_id = raw_id
                        _LOGGER.info("Discovered device_id from response: %s", self.device_id)
                        return self.device_id
                except Exception:
                    _LOGGER.debug("Failed to decode response payload")
                if (
                    msg.header.response_url is not None
                    or msg.header.correlation_data is not None
                ):
                    self._retain_response(msg)

            # Fallback: broadcast messages have device_id in their URL topic.
            if not _is_response_message(msg) and msg.topic:
                parts = msg.topic.split("/")
                # Topic format: /{product_key}/{device_id}/{category}/{type}
                if len(parts) >= 4 and parts[2]:
                    # Extract product_key from topic to set correct prefix
                    if parts[1]:
                        self.topic_prefix = f"/{parts[1]}"
                        _LOGGER.info("Topic prefix from broadcast: %s", self.topic_prefix)
                    self.device_id = parts[2]
                    _LOGGER.info("Discovered device_id from broadcast: %s", self.device_id)
                    return self.device_id

        raise NarwalCommandError(
            f"No response or broadcast within {timeout}s — check vacuum IP and power"
        )

    async def drain_ws_buffer(self) -> None:
        """Drain any pending messages from the WebSocket receive buffer.

        Called between discover_device_id() and send_command() to clear
        stale field5 responses left by wake probe commands. Without this,
        _wait_for_field5_response may consume a stale response instead of
        the real one, which can have unexpected data or error codes.
        """
        if not self.connected:
            return
        drained = 0
        retained = 0
        while True:
            try:
                data = await asyncio.wait_for(self._ws.recv(), timeout=0.05)
                drained += 1
            except TimeoutError:
                break
            except Exception:
                break
            if not isinstance(data, bytes):
                continue
            try:
                message = parse_frame(data)
            except ProtocolError:
                continue
            if (
                _is_response_message(message)
                and (
                    message.header.response_url is not None
                    or message.header.correlation_data is not None
                )
            ):
                self._retain_response(message)
                retained += 1
        if drained:
            _LOGGER.debug(
                "Drained %d stale WebSocket messages; retained %d routed responses",
                drained,
                retained,
            )

    async def disconnect(self) -> None:
        """Disconnect from the vacuum and stop all tasks."""
        self._should_reconnect = False
        if self.connected and (
            self._manual_control_active
            or self._point_navigation_active
            or self._point_navigation_start_pending
            or self._telecontrol_lock.locked()
        ):
            try:
                await self.emergency_stop_telecontrol()
            except Exception:
                _LOGGER.exception(
                    "Telecontrol cleanup failed before WebSocket disconnect"
                )
        self._listener_active = False
        self._robot_awake = False
        self._connected.clear()

        for task in (self._heartbeat_task, self._keepalive_task, self._listen_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        if self._ws:
            await self._ws.close()
            self._ws = None

        _LOGGER.info("Disconnected from Narwal vacuum")

    async def start_listening(self) -> None:
        """Start the persistent message listener with auto-reconnect.

        This method runs indefinitely until disconnect() is called.
        """
        self._should_reconnect = True
        retry_delay = RECONNECT_INITIAL_DELAY

        while self._should_reconnect:
            try:
                if not self.connected:
                    await self.connect()
                    if self._state_needs_keepalive():
                        await self._send_wake_burst()
                    else:
                        await self.subscribe_to_topics()
                        _LOGGER.debug("Robot is docked/idle; not sending reconnect wake")

                retry_delay = RECONNECT_INITIAL_DELAY  # reset on success
                self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
                self._keepalive_task = asyncio.create_task(self._keepalive_loop())
                self._listener_active = True

                async for raw_message in self._ws:
                    if isinstance(raw_message, bytes):
                        await self._handle_message(raw_message)

            except NarwalConnectionError as e:
                _LOGGER.warning("Connection failed: %s", e)
            except websockets.exceptions.ConnectionClosed as e:
                _LOGGER.warning("Connection closed: %s", e)
            except asyncio.CancelledError:
                _LOGGER.debug("Listener cancelled")
                return
            except Exception:
                _LOGGER.exception("Unexpected error in listener")
            finally:
                self._listener_active = False
                self._robot_awake = False
                self._connected.clear()
                for task in (self._heartbeat_task, self._keepalive_task):
                    if task and not task.done():
                        task.cancel()

            if not self._should_reconnect:
                break

            # Exponential backoff with jitter
            jitter = random.uniform(0, 1)
            wait = retry_delay + jitter
            _LOGGER.info("Reconnecting in %.1fs...", wait)
            await asyncio.sleep(wait)
            retry_delay = min(
                retry_delay * RECONNECT_BACKOFF_FACTOR, RECONNECT_MAX_DELAY
            )

    async def _handle_message(self, data: bytes) -> None:
        """Parse a raw frame and update state or route response."""
        if len(data) < 4:
            return

        try:
            msg = parse_frame(data)
        except ProtocolError as e:
            _LOGGER.debug("Failed to parse frame: %s", e)
            return

        if _is_response_message(msg):
            _LOGGER.debug("Command response routed to queue: %s", msg.short_topic)
            await self._response_queue.put(msg)
            return

        # Any broadcast means the robot is awake
        self._last_broadcast_time = time.monotonic()
        if not self._robot_awake:
            self._robot_awake = True
            _LOGGER.info("Robot is awake (received broadcast)")

        if self.on_message:
            self.on_message(msg)

        # Decode protobuf and update state based on topic
        short_topic = msg.short_topic
        _LOGGER.debug("Broadcast topic: %s (tag=0x%02x)", short_topic, msg.field_tag)
        if short_topic == TOPIC_POINT_NAVI_PLAN_TRAJ:
            self._update_point_navigation_trajectory(msg.payload)
        try:
            decoded = self._decode_protobuf(msg.payload)
        except Exception:
            _LOGGER.debug("Failed to decode protobuf for topic %s", short_topic)
            return

        now = time.monotonic()
        if short_topic == "status/working_status":
            self._last_status_time = now
            self._update_from_working_status_broadcast(decoded, now)
        elif short_topic == "status/robot_base_status":
            self._last_status_time = now
            self._update_from_base_status_broadcast(decoded, now)
        elif short_topic == "upgrade/upgrade_status":
            self.state.update_from_upgrade_status(decoded)
        elif short_topic == "status/download_status":
            self.state.update_from_download_status(decoded)
        elif short_topic == "map/display_map":
            self.state.map_display_data = MapDisplayData.from_broadcast(decoded)
            self._last_display_map_time = time.monotonic()
            _LOGGER.debug(
                "display_map received: robot=(%.2f, %.2f) ts=%d",
                self.state.map_display_data.robot_x,
                self.state.map_display_data.robot_y,
                self.state.map_display_data.timestamp,
            )
        elif short_topic in _AUX_STATUS_TOPICS:
            self._update_from_aux_status_broadcast(short_topic, decoded)
        if self.on_state_update:
            self.on_state_update(self.state)

    def _decode_protobuf(self, payload: bytes) -> dict[str, Any]:
        """Decode a protobuf payload without a schema using blackboxprotobuf."""
        import blackboxprotobuf  # lazy import — heavy dependency

        decoded, _ = blackboxprotobuf.decode_message(payload)
        return decoded

    async def _heartbeat_loop(self) -> None:
        """Send periodic WebSocket pings to keep the connection alive."""
        try:
            while self.connected:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                if self._ws:
                    await self._ws.ping()
                    _LOGGER.debug("Heartbeat ping sent")
        except asyncio.CancelledError:
            return
        except Exception:
            _LOGGER.debug("Heartbeat failed, connection may be lost")

    # --- Wake / Keep-alive ---

    @staticmethod
    def _encode_varint(value: int) -> bytes:
        """Encode an integer as a protobuf varint."""
        result = []
        while value > 0x7F:
            result.append((value & 0x7F) | 0x80)
            value >>= 7
        result.append(value & 0x7F)
        return bytes(result)

    @classmethod
    def _encode_varint_field(cls, field_num: int, value: int) -> bytes:
        """Encode a protobuf varint field (tag + value)."""
        tag = (field_num << 3) | 0  # wire type 0 = varint
        return cls._encode_varint(tag) + cls._encode_varint(value)

    @classmethod
    def _encode_bytes_field(cls, field_num: int, data: bytes) -> bytes:
        """Encode a protobuf length-delimited field."""
        tag = (field_num << 3) | 2  # wire type 2 = length-delimited
        return cls._encode_varint(tag) + cls._encode_varint(len(data)) + data

    @classmethod
    def _encode_string_field(cls, field_num: int, text: str) -> bytes:
        """Encode a protobuf string field."""
        return cls._encode_bytes_field(field_num, text.encode("utf-8"))

    # All broadcast topics the robot can send — used for active_robot_publish
    _ALL_BROADCAST_TOPICS = [
        "status/robot_base_status",
        "status/working_status",
        "upgrade/upgrade_status",
        "status/download_status",
        "map/display_map",
        TOPIC_TIMELINE_STATUS,
        TOPIC_POINT_NAVI_PLAN_TRAJ,
        TOPIC_PLANNING_DEBUG,
        TOPIC_ROBOT_STATUS,
        TOPIC_ROBOT_CURRENT_STATUS,
        TOPIC_ROBOT_TASK_STATUS,
    ]

    def _build_topic_subscription(self, duration: int = 600) -> bytes:
        """Build active_robot_publish payload subscribing to ALL broadcast topics.

        The Narwal app sends this on open to tell the robot which topics to
        broadcast and for how long. Format: repeated field 1 = TopicDuration
        sub-messages with {1: topic_string, 2: duration_seconds}.
        """
        payload = b""
        for topic in self._ALL_BROADCAST_TOPICS:
            inner = (
                self._encode_string_field(1, topic)
                + self._encode_varint_field(2, duration)
            )
            payload += self._encode_bytes_field(1, inner)
        return payload

    async def subscribe_to_topics(self, duration: int = 600) -> None:
        """Send topic subscription to the robot.

        This tells the robot to broadcast display_map, working_status, etc.
        Must be called after connecting, especially if the robot is already
        awake (wake() skips the burst when robot_awake is True).
        """
        if not self.connected or not self._ws:
            return
        payload = self._build_topic_subscription(duration)
        frame = build_frame(
            self._full_topic(TOPIC_CMD_ACTIVE_ROBOT), payload
        )
        await self._ws.send(frame)
        _LOGGER.info("Topic subscription sent (duration=%ds)", duration)

    def _build_wake_commands(self) -> list[tuple[str, bytes]]:
        """Build the sequence of wake commands to try.

        Returns list of (short_topic, payload) tuples.  The first four
        commands are passive (subscription / heartbeat).  The final
        command is a query (get_device_base_status) that forces the
        robot's main processor to fully wake and enter command-ready
        mode.  Its field5 response ends up in _response_queue and is
        harmlessly drained by send_command() before real commands.
        """
        cmds: list[tuple[str, bytes]] = []

        # 1. notify_app_event — signal "app opened" (triggers robot wake)
        cmds.append((TOPIC_CMD_NOTIFY_APP_EVENT, self._encode_varint_field(1, 1)))

        # 2. active_robot_publish — subscribe to ALL topics for 10 minutes
        cmds.append((TOPIC_CMD_ACTIVE_ROBOT, self._build_topic_subscription(600)))

        # 3. active_robot_publish — simple duration (field 1 = 600)
        cmds.append((TOPIC_CMD_ACTIVE_ROBOT, self._encode_varint_field(1, 600)))

        # 4. app heartbeat — field 1 = 1
        cmds.append((TOPIC_CMD_APP_HEARTBEAT, self._encode_varint_field(1, 1)))

        # 5. get_device_base_status — forces robot CPU into command-ready
        #    state; passive commands alone only wake the WS server, not the
        #    application processor.  The field5 response is drained by
        #    send_command() before it processes real user commands.
        cmds.append((TOPIC_CMD_GET_BASE_STATUS, b""))

        return cmds

    async def _send_wake_burst(self) -> None:
        """Send all wake candidate commands in quick succession.

        Fire-and-forget: sends each command with a short delay between them.
        Does not wait for responses (the listener loop handles those).
        """
        if not self.connected or not self._ws:
            return

        commands = self._build_wake_commands()
        for short_topic, payload in commands:
            try:
                full_topic = self._full_topic(short_topic)
                frame = build_frame(full_topic, payload)
                await self._ws.send(frame)
                _LOGGER.debug("Wake burst: sent %s (%d bytes)", short_topic, len(payload))
            except Exception:
                _LOGGER.debug("Wake burst: failed to send %s", short_topic)
                return  # connection probably lost
            await asyncio.sleep(0.2)

    async def wake(self, timeout: float = WAKE_TIMEOUT, force: bool = False) -> bool:
        """Attempt to wake the robot from sleep.

        Sends repeated bursts of wake commands and waits for the robot to
        start broadcasting status messages.  Does NOT reconnect the
        WebSocket — the keepalive loop handles reconnect escalation
        independently (avoids race conditions with the listener loop).

        Args:
            timeout: Maximum seconds to wait for the robot to respond.
            force: If True, send wake burst even if robot_awake is True.
                Use when broadcasts have gone stale but the flag hasn't
                been reset yet.

        Returns:
            True if the robot is awake (received broadcasts), False otherwise.
        """
        if self._robot_awake and not force:
            return True

        if not self.connected:
            raise NarwalConnectionError("Not connected to vacuum")

        _LOGGER.info("Attempting to wake robot (timeout=%.0fs)...", timeout)

        deadline = asyncio.get_event_loop().time() + timeout
        attempt = 0

        while asyncio.get_event_loop().time() < deadline:
            attempt += 1

            if not self.connected:
                _LOGGER.debug("Connection lost during wake — aborting")
                break

            await self._send_wake_burst()

            # Wait up to 5 seconds for a broadcast to arrive
            wait_end = min(
                asyncio.get_event_loop().time() + 5.0,
                deadline,
            )
            while asyncio.get_event_loop().time() < wait_end:
                if self._robot_awake:
                    _LOGGER.info("Robot woke up after %d attempt(s)", attempt)
                    return True
                await asyncio.sleep(0.3)

        _LOGGER.warning("Robot did not wake up within %.0fs (%d attempts)", timeout, attempt)
        return False

    # Topic subscription duration (seconds) and renewal interval
    _TOPIC_SUB_DURATION = 600  # 10 minutes — matches what Narwal app sends
    _TOPIC_RESUB_INTERVAL = 480  # re-subscribe every 8 min (before 10min expiry)

    # After this many consecutive wake bursts without response (~60s),
    # force a WebSocket reconnect to try triggering the robot's deep sleep
    # wake handler via a fresh TCP connection.
    _WAKE_RECONNECT_THRESHOLD = 2

    async def _keepalive_loop(self) -> None:
        """Periodically send wake/heartbeat commands to prevent robot from sleeping.

        Runs alongside the listener loop. Sends a lightweight heartbeat
        command every KEEPALIVE_INTERVAL seconds. If the robot stops
        broadcasting for BROADCAST_STALE_TIMEOUT seconds (goes back to
        sleep), resets _robot_awake and escalates to a full wake burst.

        Also re-subscribes to broadcast topics before the subscription
        expires (every _TOPIC_RESUB_INTERVAL seconds) so that display_map,
        robot_base_status, etc. keep flowing during long cleaning sessions.

        If wake bursts fail repeatedly, forces a WebSocket reconnect by
        closing the connection (the listener loop handles reconnection).
        """
        # Start at 0 so the first keepalive tick sends the subscription
        # immediately. This handles the case where the robot is already
        # broadcasting (e.g. mid-cleaning) and wake() skips the burst.
        last_resub_time = 0.0
        consecutive_wake_failures = 0
        try:
            while self.connected:
                await asyncio.sleep(KEEPALIVE_INTERVAL)
                if not self.connected or not self._ws:
                    break

                # Check if broadcasts have gone stale (robot fell back asleep)
                if (
                    self._robot_awake
                    and self._last_broadcast_time > 0
                    and time.monotonic() - self._last_broadcast_time
                    > BROADCAST_STALE_TIMEOUT
                ):
                    _LOGGER.info(
                        "No broadcast for %.0fs — robot may have gone to sleep",
                        time.monotonic() - self._last_broadcast_time,
                    )
                    self._robot_awake = False
                    consecutive_wake_failures = 0

                if self._robot_awake:
                    consecutive_wake_failures = 0
                    # Re-subscribe to topics before the subscription expires
                    if time.monotonic() - last_resub_time > self._TOPIC_RESUB_INTERVAL:
                        try:
                            payload = self._build_topic_subscription(
                                self._TOPIC_SUB_DURATION
                            )
                            frame = build_frame(
                                self._full_topic(TOPIC_CMD_ACTIVE_ROBOT), payload
                            )
                            await self._ws.send(frame)
                            last_resub_time = time.monotonic()
                            _LOGGER.debug("Topic subscription renewed")
                        except Exception:
                            _LOGGER.debug("Topic re-subscribe failed")

                    if not self._state_needs_keepalive():
                        _LOGGER.debug("Robot is docked/idle; skipping app keepalive")
                        continue

                    # Send lightweight heartbeat to keep robot awake.
                    # This is only needed while an active task is in progress.
                    try:
                        payload = self._encode_varint_field(1, 1)
                        frame = build_frame(
                            self._full_topic(TOPIC_CMD_APP_HEARTBEAT), payload
                        )
                        await self._ws.send(frame)
                        _LOGGER.debug("Keepalive heartbeat sent")
                    except Exception:
                        _LOGGER.debug("Keepalive send failed")
                        break
                else:
                    if not self._state_needs_keepalive():
                        consecutive_wake_failures = 0
                        _LOGGER.debug("Robot is docked/idle; not waking")
                        continue

                    # Robot appears asleep — send full wake burst
                    # (wake burst includes topic subscription)
                    consecutive_wake_failures += 1
                    _LOGGER.debug(
                        "Robot not awake, sending wake burst "
                        "(attempt %d/%d before reconnect)",
                        consecutive_wake_failures,
                        self._WAKE_RECONNECT_THRESHOLD,
                    )
                    await self._send_wake_burst()
                    last_resub_time = time.monotonic()

                    # Escalation: after repeated failures, force a fresh
                    # WebSocket connection. Close the socket — the listener
                    # loop's reconnect logic will establish a new connection.
                    if consecutive_wake_failures >= self._WAKE_RECONNECT_THRESHOLD:
                        _LOGGER.warning(
                            "Wake burst failed %d times — forcing WebSocket "
                            "reconnect to trigger deep sleep wake",
                            consecutive_wake_failures,
                        )
                        consecutive_wake_failures = 0
                        if self._ws:
                            await self._ws.close()
                        break  # exit keepalive; listener reconnects

        except asyncio.CancelledError:
            return
        except Exception:
            _LOGGER.debug("Keepalive loop error, will restart with listener")

    # --- Command infrastructure ---

    def _retain_response(self, message: NarwalMessage) -> None:
        """Retain a routed response which cannot match the active request."""
        self._retained_responses.append(message)
        _LOGGER.debug(
            "Retained unmatched response: response_url=%r correlation_data=%r",
            message.header.response_url,
            message.header.correlation_data,
        )

    def _discard_pre_command_responses(self) -> None:
        """Establish a temporal boundary before sending a new request.

        Existing routed frames are retained for diagnostics. Unrouted legacy
        field-5 frames are dropped, matching the historical stale-wake cleanup.
        Neither kind can be a response to a command that has not been sent yet.
        """
        stale_legacy = 0
        while not self._response_queue.empty():
            try:
                message = self._response_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if (
                message.header.response_url is not None
                or message.header.correlation_data is not None
            ):
                self._retain_response(message)
            else:
                stale_legacy += 1
        if stale_legacy:
            _LOGGER.debug(
                "Discarded %d stale unrouted legacy responses", stale_legacy
            )

    async def _wait_for_queued_response(
        self,
        *,
        expected_full_topic: str,
        expected_short_topic: str,
        timeout: float,
    ) -> NarwalMessage:
        """Wait for the active command while retaining interleaved responses."""
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                message = await asyncio.wait_for(
                    self._response_queue.get(), timeout=remaining
                )
            except TimeoutError:
                break
            if _response_matches_topic(
                message,
                expected_full_topic=expected_full_topic,
                expected_short_topic=expected_short_topic,
            ):
                return message
            self._retain_response(message)

        raise NarwalCommandError(
            f"No matching response for command '{expected_short_topic}' "
            f"within {timeout}s"
        )

    async def send_command(
        self,
        short_topic: str,
        payload: bytes = b"",
        timeout: float = COMMAND_RESPONSE_TIMEOUT,
        *,
        before_send: Callable[[], None] | None = None,
    ) -> CommandResponse:
        """Send a command and wait for the field5 response.

        Uses a lock to prevent concurrent commands from racing on the
        response queue. Works both with and without start_listening().

        Args:
            short_topic: Command topic without prefix/device_id.
            payload: Protobuf-encoded payload (empty for most commands).
            timeout: Seconds to wait for response.
            before_send: Optional synchronous safety check run while holding
                the command lock, immediately before the frame is emitted.

        Returns:
            CommandResponse with result code and decoded data.

        Raises:
            NarwalConnectionError: If not connected.
            NarwalCommandError: If response times out.
        """
        if not self.connected:
            raise NarwalConnectionError("Not connected to vacuum")

        async with self._command_lock:
            self._discard_pre_command_responses()
            if before_send is not None:
                before_send()

            full_topic = self._full_topic(short_topic)
            frame = build_frame(full_topic, payload)
            await self._ws.send(frame)
            _LOGGER.debug("Sent command: %s (%d bytes)", short_topic, len(frame))

            # If listener is running, wait on the queue (avoid concurrent recv)
            if self._listener_active:
                msg = await self._wait_for_queued_response(
                    expected_full_topic=full_topic,
                    expected_short_topic=short_topic,
                    timeout=timeout,
                )
            else:
                # No listener — read directly from websocket
                msg = await self._wait_for_field5_response(
                    timeout,
                    expected_full_topic=full_topic,
                    expected_short_topic=short_topic,
                )

        # Decode response
        try:
            decoded = self._decode_protobuf(msg.payload)
        except Exception:
            decoded = {}

        # Field 1 is a result code for action commands (int),
        # but data for some query commands (string/bytes/dict).
        # Room-clean returns field 1 as a dict (config echo), not an int.
        raw_field1 = decoded.get("1")
        result_known = isinstance(raw_field1, int) and not isinstance(raw_field1, bool)
        result_code = raw_field1 if result_known else 0

        return CommandResponse(
            result_code=result_code,
            data=decoded,
            raw_payload=msg.payload,
            result_known=result_known,
        )

    async def _wait_for_field5_response(
        self,
        timeout: float,
        *,
        expected_full_topic: str | None = None,
        expected_short_topic: str | None = None,
    ) -> NarwalMessage:
        """Read until the matching response arrives, processing broadcasts."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                data = await asyncio.wait_for(
                    self._ws.recv(), timeout=min(remaining, 1.0)
                )
            except asyncio.TimeoutError:
                continue

            if not isinstance(data, bytes) or len(data) < 4:
                continue

            try:
                msg = parse_frame(data)
            except ProtocolError:
                continue

            if _is_response_message(msg):
                if (
                    expected_full_topic is None
                    or expected_short_topic is None
                    or _response_matches_topic(
                        msg,
                        expected_full_topic=expected_full_topic,
                        expected_short_topic=expected_short_topic,
                    )
                ):
                    return msg
                self._retain_response(msg)
                continue

            # Process broadcast messages while waiting
            short_topic = msg.short_topic
            if short_topic == TOPIC_POINT_NAVI_PLAN_TRAJ:
                self._update_point_navigation_trajectory(msg.payload)
            try:
                decoded = self._decode_protobuf(msg.payload)
            except Exception:
                continue

            now = time.monotonic()
            if short_topic == "status/working_status":
                self._update_from_working_status_broadcast(decoded, now)
            elif short_topic == "status/robot_base_status":
                self._update_from_base_status_broadcast(decoded, now)
            elif short_topic == "upgrade/upgrade_status":
                self.state.update_from_upgrade_status(decoded)
            elif short_topic == "status/download_status":
                self.state.update_from_download_status(decoded)
            elif short_topic == "map/display_map":
                self.state.map_display_data = MapDisplayData.from_broadcast(decoded)
            elif short_topic in _AUX_STATUS_TOPICS:
                self._update_from_aux_status_broadcast(short_topic, decoded)

        raise NarwalCommandError(f"No matching response within {timeout}s")

    async def send_raw(
        self, topic: str, payload: bytes, header_byte: int | None = None
    ) -> None:
        """Send a raw command frame to the vacuum.

        Args:
            topic: Full topic string.
            payload: Protobuf-encoded payload.
            header_byte: Header byte (auto-calculated if None).

        Raises:
            NarwalConnectionError: If not connected.
        """
        if not self.connected:
            raise NarwalConnectionError("Not connected to vacuum")

        frame = build_frame(topic, payload, header_byte)
        await self._ws.send(frame)
        _LOGGER.debug("Sent raw to topic: %s (%d bytes)", topic, len(frame))

    async def _publish_command(self, short_topic: str, payload: bytes) -> None:
        """Publish a command which intentionally has no response topic."""
        await self.send_raw(self._full_topic(short_topic), payload)

    @staticmethod
    def _command_performed(response: CommandResponse) -> bool:
        """Return whether an APK ServiceResult reports perform-success."""
        return (
            response.result_known
            and response.result_code == CommandResult.SUCCESS
        )

    async def _wait_for_manual_control_state(
        self,
        expected: int,
        *,
        timeout: float = 2.0,
    ) -> bool:
        """Wait for RobotBaseStatus.manualControlStatus (field 31)."""
        if self._manual_control_state == expected:
            return True

        deadline = time.monotonic() + timeout
        if self._listener_active:
            while time.monotonic() < deadline:
                if self._manual_control_state == expected:
                    return True
                await asyncio.sleep(0.05)
            return self._manual_control_state == expected

        if not self.connected:
            return False

        # Without the persistent listener, temporarily own recv() and process
        # broadcasts until the mode state arrives.
        async with self._command_lock:
            while time.monotonic() < deadline:
                if self._manual_control_state == expected:
                    return True
                remaining = deadline - time.monotonic()
                try:
                    data = await asyncio.wait_for(
                        self._ws.recv(),
                        timeout=min(remaining, 0.1),
                    )
                except TimeoutError:
                    continue
                if not isinstance(data, bytes) or len(data) < 4:
                    continue
                try:
                    message = parse_frame(data)
                except ProtocolError:
                    continue
                if _is_response_message(message):
                    self._retain_response(message)
                    continue
                await self._handle_message(data)
        return self._manual_control_state == expected

    # --- High-level commands ---

    async def locate(self) -> CommandResponse:
        """Trigger locate sound — robot says 'Robot is here'."""
        return await self.send_command(TOPIC_CMD_YELL)

    # Legacy clean task payload — works on Flow firmware < v01.07.22.
    # Structure: {1: {2: {}, 5: {1: {1: 3, 2: 2, 3: 1}, 5: {}}}}
    #   field 5.1.1 = suction level (3=max)
    #   field 5.1.2 = mop humidity (2=wet)
    #   field 5.1.3 = passes (1=single)
    # On firmware v01.07.22+ (Flow), this returns NOT_APPLICABLE and
    # start() falls back to the v2 room-list schema. See issue #36.
    _DEFAULT_CLEAN_PAYLOAD = bytes.fromhex("0a0e12002a0a0a060803100218012a00")

    async def start(self, **kwargs) -> CommandResponse:
        """Start whole-house cleaning.

        Tries the legacy minimal payload first (works on Flow firmware
        < v01.07.22). If the robot returns NOT_APPLICABLE — observed on
        firmware v01.07.22.00 in issue #36 — falls back to the v2 schema
        that includes an explicit room list, mirroring what the Narwal
        app sends on newer firmware.

        The v2 fallback requires the map to be loaded (get_map called)
        so we know which rooms to include.
        """
        resp = await self.send_command(
            TOPIC_CMD_PLAN_START,
            payload=self._DEFAULT_CLEAN_PAYLOAD,
            timeout=10.0,
        )
        if resp.result_code != CommandResult.NOT_APPLICABLE:
            return resp

        # Legacy payload rejected — likely newer firmware. Need the room
        # list from the cached map to build a v2 payload.
        if not (self.state.map_data and self.state.map_data.rooms):
            _LOGGER.warning(
                "start() got NOT_APPLICABLE and no map rooms cached; "
                "cannot build v2 payload. Call get_map() first."
            )
            return resp

        room_ids = [r.room_id for r in self.state.map_data.rooms if r.room_id]
        if not room_ids:
            _LOGGER.warning(
                "start() got NOT_APPLICABLE but cached map has 0 rooms with IDs"
            )
            return resp

        _LOGGER.info(
            "start(): legacy payload rejected, retrying with v2 schema (%d rooms)",
            len(room_ids),
        )
        payload = self._build_clean_payload_v2(room_ids)
        resp = await self.send_command(
            TOPIC_CMD_PLAN_START, payload=payload, timeout=10.0,
        )
        return resp

    def _build_clean_payload_v2(
        self,
        room_ids: list[int],
        suction: int = 3,
        mop_humidity: int = 2,
        passes: int = 1,
        clean_mode: int = 3,
    ) -> bytes:
        """Build clean task payload using the v2 schema (firmware v01.07.22+).

        Observed in issue #36 from a Flow on firmware v01.07.22.00.
        Each room entry uses a nested room_id:

            {
              1: {1: 1, 2: <room_id>},                # nested room ref
              2: {1: <suction>, 2: <clean_mode>,      # per-room params
                  3: <passes>, 7: <mop_humidity>},
              3: <sequence>,                          # 1-indexed
            }

        Outer envelope:
            {1: {1: 1, 2: [<rooms>], 3: {}, 5: 6}}

        Defaults match a normal whole-house clean: max Flow 1 suction (3),
        sweep+mop (3 in v2 schema), single pass, wet mop.

        Args:
            room_ids: List of room IDs from RoomInfo.room_id.
            suction: 1-3 (Flow 1) / 1-4 (Flow 2). Default 3 = max for Flow 1.
            mop_humidity: 1=dry, 2=wet, 3=very wet. Default 2.
            passes: Number of passes. Default 1.
            clean_mode: v2 schema cleanMode (3 observed for sweep+mop).

        Returns:
            Encoded protobuf bytes for clean/plan/start.
        """
        import blackboxprotobuf

        room_entries = [
            {
                "1": {"1": 1, "2": rid},
                "2": {
                    "1": suction,
                    "2": clean_mode,
                    "3": passes,
                    "7": mop_humidity,
                },
                "3": idx + 1,
            }
            for idx, rid in enumerate(room_ids)
        ]

        room_entry_typedef = {
            "type": "message",
            "seen_repeated": True,
            "message_typedef": {
                "1": {
                    "type": "message",
                    "message_typedef": {
                        "1": {"type": "int"},
                        "2": {"type": "uint"},
                    },
                },
                "2": {
                    "type": "message",
                    "message_typedef": {
                        "1": {"type": "int"},
                        "2": {"type": "int"},
                        "3": {"type": "int"},
                        "7": {"type": "int"},
                    },
                },
                "3": {"type": "int"},
            },
        }

        msg = {
            "1": {
                "1": 1,
                "2": room_entries if len(room_entries) > 1 else room_entries[0],
                "3": {},
                "5": 6,
            }
        }
        typedef = {
            "1": {
                "type": "message",
                "message_typedef": {
                    "1": {"type": "int"},
                    "2": room_entry_typedef,
                    "3": {"type": "message", "message_typedef": {}},
                    "5": {"type": "int"},
                },
            }
        }
        return blackboxprotobuf.encode_message(
            msg, _normalise_blackboxprotobuf_typedef(typedef)
        )

    # WorkMode -> (CleanParam.mode tag 1, pass-count tags to set from `passes`). The robot's
    # execution mode is CleanTask.taskType (= the WorkMode value); CleanParam.mode and the
    # pass tag are derived here so the two can't drift. Live-validated on a Flow 2; see
    # project_history.md "CleanParam — fully decoded".
    _WORK_MODE_PARAM: dict[WorkMode, tuple[int, tuple[str, ...]]] = {
        WorkMode.VACUUM: (2, ("5",)),               # sweepTime
        WorkMode.MOP: (3, ("6",)),                 # mopTime
        WorkMode.VACUUM_THEN_MOP: (5, ("5", "6")),  # sweep + mop pass counts
        WorkMode.VACUUM_AND_MOP: (4, ("7",)),      # sweepMopSyncTime
    }

    def _build_start_clean_payload(
        self,
        room_ids: list[int],
        map_id: int,
        *,
        work_mode: WorkMode = WorkMode.VACUUM_AND_MOP,
        fan: FanLevel = FanLevel.NORMAL,
        water: MopHumidity = MopHumidity.NORMAL,
        mop_strength: MopStrengthLevel = MopStrengthLevel.NORMAL,
        passes: int = 1,
        route: CleaningRoute | None = None,
    ) -> bytes:
        """Build a clean/start_clean request for the given rooms.

        StartClean_Request{1: CleanTask{1: map_id, 2: [CleanItem...], 3: {} (TaskOption),
        5: taskType}}; CleanItem{1: ZoneOption{1: 1 (room zone), 2: room_id}, 2: CleanParam,
        3: order}. taskType (the execution-mode carrier) and CleanParam.mode/pass-tag are
        derived from work_mode. overlapLevel is CleanParam tag 8 when supplied.

        Args:
            room_ids: Robot room IDs (RoomInfo.room_id).
            map_id: Active map id (MapData.map_id, get_map field 2.1).
            work_mode: Vacuum / mop / vacuum-then-mop / vacuum-and-mop.
            fan: Suction level (CleanParam tag 2).
            water: Mop water volume (tag 4).
            mop_strength: Mop scrub intensity (tag 3).
            passes: Clean count, routed to the pass tag(s) for the mode.
            route: Optional route overlap level (tag 8).
        """
        import blackboxprotobuf

        param_mode, pass_tags = self._WORK_MODE_PARAM[work_mode]
        param: dict[str, int] = {
            "1": int(param_mode),
            "2": int(fan),
            "3": int(mop_strength),
            "4": int(water),
        }
        if route is not None:
            param["8"] = int(route)
        for tag in pass_tags:
            param[tag] = int(passes)

        items = [
            {"1": {"1": 1, "2": rid}, "2": dict(param), "3": idx + 1}
            for idx, rid in enumerate(room_ids)
        ]
        task = {
            "1": map_id,
            "2": items if len(items) > 1 else items[0],
            "3": {},
            "5": int(work_mode),  # CleanTask.taskType
        }
        item_typedef = {
            "type": "message",
            "seen_repeated": True,
            "message_typedef": {
                "1": {"type": "message", "message_typedef": {
                    "1": {"type": "int"}, "2": {"type": "int"},
                }},
                # Derive the CleanParam typedef from the emitted dict — bbpb silently
                # drops any tag absent from the typedef.
                "2": {"type": "message", "message_typedef": {
                    k: {"type": "int"} for k in param
                }},
                "3": {"type": "int"},
            },
        }
        typedef = {"1": {"type": "message", "message_typedef": {
            "1": {"type": "int"},
            "2": item_typedef,
            "3": {"type": "message", "message_typedef": {}},
            "5": {"type": "int"},
        }}}
        return blackboxprotobuf.encode_message(
            {"1": task}, _normalise_blackboxprotobuf_typedef(typedef)
        )

    def _build_room_clean_payload(self, room_ids: list[int]) -> bytes:
        """Build the legacy flat room-clean payload for older firmware."""
        if not room_ids:
            return self._DEFAULT_CLEAN_PAYLOAD

        import blackboxprotobuf

        room_entries = [
            {"1": room_id, "2": 2, "3": 1, "6": 3, "7": 2}
            for room_id in room_ids
        ]
        room_typedef = {
            "type": "message",
            "seen_repeated": True,
            "message_typedef": {
                "1": {"type": "uint"},
                "2": {"type": "int"},
                "3": {"type": "int"},
                "6": {"type": "int"},
                "7": {"type": "int"},
            },
        }
        field_2_value = room_entries[0] if len(room_entries) == 1 else room_entries
        message = {
            "1": {
                "2": field_2_value,
                "5": {"1": {"1": 3, "2": 2, "3": 1}, "5": {}},
            }
        }
        typedef = {
            "1": {
                "type": "message",
                "message_typedef": {
                    "2": room_typedef,
                    "5": {
                        "type": "message",
                        "message_typedef": {
                            "1": {
                                "type": "message",
                                "message_typedef": {
                                    "1": {"type": "int"},
                                    "2": {"type": "int"},
                                    "3": {"type": "int"},
                                },
                            },
                            "5": {"type": "message", "message_typedef": {}},
                        },
                    },
                },
            }
        }
        return blackboxprotobuf.encode_message(message, typedef)

    async def start_rooms(
        self,
        room_ids: list[int],
        *,
        work_mode: WorkMode = WorkMode.VACUUM_AND_MOP,
        fan: FanLevel = FanLevel.DEEP,
        water: MopHumidity = MopHumidity.WET,
        mop_strength: MopStrengthLevel = MopStrengthLevel.NORMAL,
        passes: int = 1,
        route: CleaningRoute | None = None,
    ) -> CommandResponse:
        """Start cleaning the given rooms via clean/start_clean.

        Room cleaning must use clean/start_clean (StartClean → CleanTask), not
        clean/plan/start: on Flow firmware the latter is StartWithPlan{planId,
        mapId} and ignores any room payload — the root cause of #25/#37, where
        the robot undocks and wanders instead of cleaning the selected rooms.
        The CleanTask carries the active map id (get_map field 2.1).

        clean/start_clean only works while docked; from STANDBY the robot
        returns NOT_READY (4). Callers should start from the dock; this retries
        briefly to cover the dock settling transition.

        Args:
            room_ids: Robot room IDs (RoomInfo.room_id), mapped from HA areas.
            work_mode, fan, water, mop_strength, passes, route: CleanParam settings —
                see _build_start_clean_payload.
        """
        if not room_ids:
            return await self.start()

        product_key = (
            self.state.device_info.product_key
            if self.state.device_info is not None
            and self.state.device_info.product_key
            else self.topic_prefix.removeprefix("/")
        )
        supports_legacy_room_clean = product_key in LEGACY_ROOM_CLEAN_PRODUCT_KEYS
        map_data = self.state.map_data
        if not map_data or not map_data.map_id:
            try:
                map_data = await self.get_map()
            except NarwalCommandError:
                if not supports_legacy_room_clean:
                    raise
                _LOGGER.debug(
                    "start_rooms: map fetch failed; trying legacy room-clean commands"
                )
                map_data = None
        map_id = map_data.map_id if map_data else 0
        if not map_id and not supports_legacy_room_clean:
            return CommandResponse(result_code=CommandResult.NOT_APPLICABLE)
        resp = CommandResponse(result_code=CommandResult.NOT_APPLICABLE)
        if map_id:
            payload = self._build_start_clean_payload(
                room_ids,
                map_id,
                work_mode=work_mode,
                fan=fan,
                water=water,
                mop_strength=mop_strength,
                passes=passes,
                route=route,
            )
            resp = await self.send_command(
                TOPIC_CMD_CLEAN_TASK, payload=payload, timeout=10.0,
            )
            for _ in range(3):
                if resp.result_code != CommandResult.NOT_READY:
                    break
                if not self.state.is_docked:
                    _LOGGER.warning(
                        "start_rooms: robot not docked (status=%s); "
                        "clean/start_clean requires the robot on the dock",
                        self.state.working_status.name,
                    )
                    break
                _LOGGER.info(
                    "start_rooms: robot docking/settling, retrying "
                    "clean/start_clean"
                )
                await asyncio.sleep(3.0)
                resp = await self.send_command(
                    TOPIC_CMD_CLEAN_TASK, payload=payload, timeout=10.0,
                )
        else:
            _LOGGER.warning(
                "start_rooms: no active map id available; trying legacy room clean"
            )
        if resp.result_code != CommandResult.NOT_APPLICABLE:
            return resp
        if not supports_legacy_room_clean:
            return resp

        _LOGGER.info(
            "start_rooms: clean/start_clean rejected, trying clean/plan/start "
            "compatibility payloads"
        )
        legacy_suction = {
            FanLevel.UNSPECIFIED: 3,
            FanLevel.MUTE: 0,
            FanLevel.NORMAL: 1,
            FanLevel.STRONG: 2,
            FanLevel.DEEP: 3,
            FanLevel.SUPER: 3,
        }[FanLevel(fan)]
        legacy_water = {
            MopHumidity.UNSPECIFIED: 2,
            MopHumidity.DRY: 0,
            MopHumidity.NORMAL: 1,
            MopHumidity.WET: 2,
        }[MopHumidity(water)]
        legacy_v2 = self._build_clean_payload_v2(
            room_ids,
            suction=legacy_suction,
            mop_humidity=legacy_water,
            passes=passes,
        )
        resp = await self.send_command(
            TOPIC_CMD_PLAN_START, payload=legacy_v2, timeout=10.0,
        )
        if resp.result_code != CommandResult.NOT_APPLICABLE:
            return resp

        return await self.send_command(
            TOPIC_CMD_PLAN_START,
            payload=self._build_room_clean_payload(room_ids),
            timeout=10.0,
        )

    async def start_rooms_compat(
        self,
        room_ids: list[int],
    ) -> CommandResponse:
        """Use the pre-parity room-clean path retained for unvalidated models.

        This is the behavior shipped on master before the parameterized
        ``clean/start_clean`` implementation: try the observed nested-room
        ``clean/plan/start`` payload, then its legacy flat-room fallback.
        """
        if not room_ids:
            return await self.start()

        payload_v2 = self._build_clean_payload_v2(room_ids)
        response = await self.send_command(
            TOPIC_CMD_PLAN_START,
            payload=payload_v2,
            timeout=10.0,
        )
        if response.result_code != CommandResult.NOT_APPLICABLE:
            return response

        _LOGGER.info(
            "start_rooms_compat: nested payload rejected; retrying legacy schema"
        )
        return await self.send_command(
            TOPIC_CMD_PLAN_START,
            payload=self._build_room_clean_payload(room_ids),
            timeout=10.0,
        )

    async def start_easy_clean(self) -> CommandResponse:
        """Start quick/easy clean."""
        return await self.send_command(TOPIC_CMD_EASY_CLEAN)

    async def pause(self) -> CommandResponse:
        """Pause current task."""
        return await self.send_command(TOPIC_CMD_PAUSE)

    async def resume(self, timeout: float = COMMAND_RESPONSE_TIMEOUT) -> CommandResponse:
        """Resume paused task."""
        return await self.send_command(TOPIC_CMD_RESUME, timeout=timeout)

    async def stop(self, timeout: float = 15.0) -> CommandResponse:
        """Force-stop current task.

        Note: force_end is slow — robot physically stops before responding.
        Previous testing shows 10-15s response times from CLEANING state.
        """
        return await self.send_command(TOPIC_CMD_FORCE_END, timeout=timeout)

    async def cancel(self) -> CommandResponse:
        """Cancel current task."""
        return await self.send_command(TOPIC_CMD_CANCEL)

    async def return_to_base(self, timeout: float = COMMAND_RESPONSE_TIMEOUT) -> CommandResponse:
        """Return to charging dock."""
        return await self.send_command(TOPIC_CMD_RECALL, timeout=timeout)

    async def set_fan_speed(self, level: FanLevel | int) -> CommandResponse:
        """Set suction fan speed live (clean/set_fan_level, field 1 = SweepFanLevel).

        The live command's enum is SweepFanLevel, which has no SUPER. Use its
        highest available level, DEEP, when callers request SUPER. Bare integer
        values retain the original 0=quiet through 3=max API mapping.
        """
        if isinstance(level, FanLevel):
            live = min(int(level), int(FanLevel.DEEP))
        else:
            legacy_levels = {
                0: FanLevel.MUTE,
                1: FanLevel.NORMAL,
                2: FanLevel.STRONG,
                3: FanLevel.DEEP,
            }
            try:
                live = int(legacy_levels[level])
            except KeyError as err:
                raise ValueError(f"Invalid legacy fan level: {level}") from err
        payload = b"\x08" + bytes([live & 0x7F])
        return await self.send_command(TOPIC_CMD_SET_FAN_LEVEL, payload)

    async def set_mop_humidity(self, level: MopHumidity | int) -> CommandResponse:
        """Set mop water volume live (clean/set_mop_humidity, field 1 = MopHumidity).

        Args:
            level: MopHumidity enum, or the legacy int mapping
                (0=dry, 1=normal, 2=wet).
        """
        if isinstance(level, MopHumidity):
            live = int(level)
        else:
            legacy_levels = {
                0: MopHumidity.DRY,
                1: MopHumidity.NORMAL,
                2: MopHumidity.WET,
            }
            try:
                live = int(legacy_levels[level])
            except KeyError as err:
                raise ValueError(f"Invalid legacy mop humidity: {level}") from err
        payload = b"\x08" + bytes([live & 0x7F])
        return await self.send_command(TOPIC_CMD_SET_MOP_HUMIDITY, payload)

    async def wash_mop(self) -> CommandResponse:
        """Wash the mop pads at the station."""
        return await self.send_command(TOPIC_CMD_WASH_MOP)

    async def wash_mop_by_robot_status(self) -> CommandResponse:
        """Wash mop pads using the app's status-gated station command."""
        return await self.send_command(TOPIC_CMD_WASH_MOP_BY_ROBOT_STATUS)

    async def dry_mop(self) -> CommandResponse:
        """Dry the mop pads at the station."""
        return await self.send_command(TOPIC_CMD_DRY_MOP)

    async def empty_dustbin(self) -> CommandResponse:
        """Empty the dustbin at the station."""
        return await self.send_command(TOPIC_CMD_DUST_GATHERING)

    async def wash_and_dry_mop(self) -> CommandResponse:
        """Wash and dry the mop pads at the station."""
        return await self.send_command(TOPIC_CMD_WASH_AND_DRY_MOP)

    async def dry_dust_bag(self) -> CommandResponse:
        """Dry/disinfect the robot dust bin/canister."""
        return await self.send_command(TOPIC_CMD_DRY_DUST_BAG)

    async def dry_station_bag(self) -> CommandResponse:
        """Dry/disinfect the dock dust bag."""
        return await self.send_command(TOPIC_CMD_DRY_STATION_BAG)

    # --- Query commands ---

    async def get_device_info(self) -> DeviceInfo:
        """Query device identity (product key, device ID, firmware)."""
        resp = await self.send_command(TOPIC_CMD_GET_DEVICE_INFO)
        data = resp.data

        def _clean_bytes(val: Any) -> str:
            if isinstance(val, bytes):
                return val.decode("utf-8", errors="replace").rstrip("\n")
            s = str(val)
            if s.startswith("b'") and s.endswith("'"):
                s = s[2:-1]
            return s.rstrip("\n")

        info = DeviceInfo(
            product_key=_clean_bytes(data.get("1", "")),
            device_id=_clean_bytes(data.get("2", "")),
            firmware_version=_clean_bytes(data.get("3", "")),
        )
        self.state.device_info = info
        self.state.firmware_version = info.firmware_version

        # Update topic prefix to match this device's product key
        if info.product_key:
            self.topic_prefix = f"/{info.product_key}"
            _LOGGER.info("Topic prefix set to %s", self.topic_prefix)

        return info

    async def get_feature_list(self) -> CapabilityMap:
        """Query and cache the device-advertised capability fields."""
        resp = await self.send_command(TOPIC_CMD_GET_FEATURE_LIST)
        capabilities = normalize_feature_response(resp.data)
        self.state.capabilities = capabilities
        self.state.capabilities_fetched = True
        _LOGGER.info(
            "Device advertised %d Narwal capability fields",
            len(capabilities),
        )
        return capabilities

    async def get_config(self) -> ConfigSnapshot:
        """Query and cache a read-only configuration snapshot."""
        resp = await self.send_command(TOPIC_CMD_GET_CONFIG)
        snapshot = decode_get_config_response(resp.data)
        self.state.config_snapshot = snapshot
        _LOGGER.debug(
            "%s config/get returned %d typed and %d raw fields",
            self.host,
            len(snapshot.values),
            len(snapshot.raw_fields),
        )
        return snapshot

    async def set_config_patch(
        self,
        patch: SetConfigPatch,
    ) -> ConfigSnapshot:
        """Write one setting and require an exact immediate readback.

        A transport-level response is not sufficient evidence of persistence.
        The write fails closed unless ``config/set`` returns a known success
        and the following ``config/get`` contains the requested typed value.
        """
        payload = encode_set_config_patch(patch)
        async with self._config_write_lock:
            response = await self.send_command(
                TOPIC_CMD_SET_CONFIG,
                payload=payload,
            )
            if not self._command_performed(response):
                if response.result_known:
                    detail = f"result code {response.result_code}"
                else:
                    detail = "an unconfirmed response"
                raise NarwalCommandError(
                    f"config/set failed with {detail}"
                )

            snapshot = await self.get_config()
            if patch.field not in snapshot.values:
                raise NarwalCommandError(
                    "config/set readback omitted requested field "
                    f"{patch.field.name}"
                )

            readback = snapshot.values[patch.field]
            if (
                type(readback) is not type(patch.value)
                or readback != patch.value
            ):
                raise NarwalCommandError(
                    "config/set readback mismatch for "
                    f"{patch.field.name}: requested {patch.value!r}, "
                    f"received {readback!r}"
                )
            return snapshot

    async def get_status(
        self,
        full_update: bool = True,
        *,
        require_full: bool = False,
    ) -> CommandResponse:
        """Query current device base status.

        Args:
            full_update: If True, update all state fields (working_status,
                battery, etc). If False, only update hardware-sampled fields
                (battery, health) — used when robot is not broadcasting and
                working_status in the response may be stale.
            require_full: Reject an incomplete base-status response instead of
                allowing callers to make an action decision from cached state.
        """
        resp = await self.send_command(TOPIC_CMD_GET_BASE_STATUS)
        status_data = resp.data.get("2", {})
        if status_data and not isinstance(status_data, dict):
            _LOGGER.debug(
                "%s get_status response field 2 is %s, not a base-status object: %r",
                self.host,
                type(status_data).__name__,
                status_data,
            )
            if require_full:
                raise NarwalCommandError(
                    "Robot did not return a complete base status"
                )
            return resp
        if status_data:
            _LOGGER.debug(
                "%s get_status response (full=%s): field3=%r, field2=%r",
                self.host,
                full_update,
                status_data.get("3") if isinstance(status_data, dict) else None,
                status_data.get("2") if isinstance(status_data, dict) else None,
            )
            _LOGGER.debug(
                "%s get_status decoded base_status (full=%s): %r",
                self.host,
                full_update,
                status_data,
            )
            if full_update:
                if require_full and _full_base_status_task(status_data) is None:
                    raise NarwalCommandError(
                        "Robot did not return a complete base status"
                    )
                self._update_observed_telecontrol_state(
                    status_data,
                    clear_missing=True,
                )
                self.state.update_from_base_status(status_data)
            else:
                self.state.update_battery_from_base_status(status_data)
        else:
            _LOGGER.debug("get_status response has no field 2; keys: %s", list(resp.data.keys()))
            if require_full:
                raise NarwalCommandError("Robot did not return a complete base status")
        return resp

    async def get_current_task(self) -> CurrentCleanTask:
        """Query and cache the current clean task without inferring activity."""
        resp = await self.send_command(TOPIC_CMD_GET_CURRENT_TASK)
        task = decode_current_task_response(resp.data)
        self.state.current_clean_task = task
        _LOGGER.debug(
            "%s current clean task: map=%r type=%r items=%d",
            self.host,
            task.map_id,
            task.task_type,
            len(task.items),
        )
        return task

    async def get_current_clean_plan(self) -> CurrentPlanResponse:
        """Query and cache the current official-app cleaning plan."""
        resp = await self.send_command(TOPIC_CMD_GET_CURRENT_CLEAN_PLAN)
        result = decode_current_plan_response(resp.data)
        self.state.current_clean_plan = result.plan
        return result

    async def get_clean_plans(self) -> CleanPlansResponse:
        """Query and cache every saved official-app cleaning plan."""
        resp = await self.send_command(TOPIC_CMD_GET_CLEAN_PLANS)
        result = decode_clean_plans_response(resp.data)
        self.state.clean_plans = result.plans
        return result

    async def get_clean_schedules(self) -> GetCleanSchedulesResponse:
        """Query and cache all cleaning schedules without changing them."""
        resp = await self.send_command(TOPIC_CMD_GET_CLEAN_SCHEDULES)
        result = decode_get_clean_schedules_response(resp.raw_payload)
        self.state.clean_schedules = result.clean_schedules
        return result

    async def set_clean_schedule_enabled(
        self,
        task_id: int,
        enabled: bool,
    ) -> GetCleanSchedulesResponse:
        """Toggle one existing schedule with a fresh, verified transaction."""
        if type(task_id) is not int or not 0 <= task_id <= (1 << 32) - 1:
            raise ValueError("task_id must be a uint32")
        if type(enabled) is not bool:
            raise TypeError("enabled must be bool")

        async with self._schedule_write_lock:
            # Never use the cached inventory as a mutation source.  The
            # official app can update any schedule field while Home Assistant
            # is connected, and encoding stale fields would silently undo it.
            inventory = await self.get_clean_schedules()
            schedule = next(
                (
                    candidate
                    for candidate in inventory.clean_schedules
                    if candidate.task_id == task_id
                ),
                None,
            )
            if (
                schedule is None
                or schedule.clean_schedule_param is None
                or schedule.clean_schedule_param.crontab is None
            ):
                raise NarwalCommandError(
                    f"Schedule {task_id} is missing or has no editable crontab"
                )

            updated_crontab = replace(
                schedule.clean_schedule_param.crontab,
                enabled=enabled,
            )
            updated_parameter = replace(
                schedule.clean_schedule_param,
                crontab=updated_crontab,
            )
            updated_schedule = replace(
                schedule,
                clean_schedule_param=updated_parameter,
            )
            payload = encode_update_clean_schedule_request(
                UpdateCleanScheduleRequest(clean_schedule=updated_schedule)
            )
            response = await self.send_command(
                TOPIC_CMD_UPDATE_CLEAN_SCHEDULE,
                payload=payload,
            )
            update_result = decode_update_clean_schedule_response(
                response.raw_payload
            )
            if (
                update_result.error_code is None
                or update_result.error_code.code is not ScheduleError.SUCCESS
            ):
                raise NarwalCommandError(
                    f"Schedule {task_id} update was not confirmed"
                )

            readback_inventory = await self.get_clean_schedules()
            readback = next(
                (
                    candidate
                    for candidate in readback_inventory.clean_schedules
                    if candidate.task_id == task_id
                ),
                None,
            )
            # Dataclass equality deliberately compares every decoded known and
            # unknown field.  The only permitted difference from the freshly
            # fetched schedule was already captured in ``updated_schedule``.
            if readback != updated_schedule:
                raise NarwalCommandError(
                    f"Schedule {task_id} readback did not match the full update"
                )
            return readback_inventory

    async def get_consumable_info(self) -> GetConsumableInfoResponse:
        """Query and cache locally advertised maintenance/replacement categories."""
        resp = await self.send_command(TOPIC_CMD_GET_CONSUMABLE_INFO)
        result = decode_get_consumable_info_response(resp.raw_payload)
        self.state.consumable_info = result.consumable_info
        return result

    async def get_firmware_metadata(self) -> FirmwareVersionResponse:
        """Query and cache the full read-only firmware component inventory."""
        resp = await self.send_command(TOPIC_CMD_GET_FIRMWARE_VERSION)
        result = decode_get_firmware_version_response(resp.raw_payload)
        self.state.firmware_metadata = result
        return result

    async def get_language_metadata(self) -> GetLanguageResponse:
        """Query and cache the robot's configured spoken language."""
        resp = await self.send_command(TOPIC_CMD_GET_LANGUAGE)
        result = decode_get_language_response(resp.raw_payload)
        self.state.configured_language = result
        return result

    async def get_supported_languages(self) -> GetSupportedLanguagesResponse:
        """Query and cache every language advertised by the robot."""
        resp = await self.send_command(TOPIC_CMD_GET_SUPPORTED_LANGUAGES)
        result = decode_get_supported_languages_response(resp.raw_payload)
        self.state.supported_languages = result
        return result

    async def get_current_voice_info(self) -> GetCurrentVoiceInfoResponse:
        """Query and cache current official-app voice-package metadata."""
        resp = await self.send_command(TOPIC_CMD_GET_CURRENT_VOICE_INFO)
        result = decode_get_current_voice_info_response(resp.raw_payload)
        self.state.current_voice_info = result
        return result

    async def get_clean_timeline(self) -> GetCleanTimeLineResponse:
        """Query and cache the official app's complete local task timeline."""
        resp = await self.send_command(
            TOPIC_CMD_GET_CLEAN_TIMELINE,
            payload=encode_get_clean_time_line_request(),
        )
        result = decode_get_clean_time_line_response(resp.data)
        self.state.clean_timeline = result
        return result

    async def get_clean_progress_info(self) -> CommandResponse:
        """Query active clean progress information."""
        resp = await self.send_command(TOPIC_CMD_GET_CLEAN_PROGRESS_INFO)
        self.state.update_from_aux_status(TOPIC_CMD_GET_CLEAN_PROGRESS_INFO, resp.data)
        _LOGGER.debug("%s clean_progress_info response: %r", self.host, resp.data)
        return resp

    async def get_dry_mop_remain_time(self) -> CommandResponse:
        """Query remaining mop drying time."""
        resp = await self.send_command(TOPIC_CMD_GET_DRY_MOP_REMAIN_TIME)
        self.state.update_from_aux_status(TOPIC_CMD_GET_DRY_MOP_REMAIN_TIME, resp.data)
        _LOGGER.debug("%s dry_mop_remain_time response: %r", self.host, resp.data)
        return resp

    async def get_robot_task_status(self) -> CommandResponse:
        """Query the robot task status model."""
        resp = await self.send_command(TOPIC_CMD_GET_ROBOT_TASK_STATUS)
        self.state.update_from_aux_status(TOPIC_CMD_GET_ROBOT_TASK_STATUS, resp.data)
        _LOGGER.debug("%s robot_task_status response: %r", self.host, resp.data)
        return resp

    async def get_map(self) -> MapData:
        """Download the full map data."""
        resp = await self.send_command(TOPIC_CMD_GET_MAP, timeout=15.0)
        product_key = ""
        if self.state.device_info and self.state.device_info.product_key:
            product_key = self.state.device_info.product_key
        map_data = MapData.from_response(resp.data, product_key=product_key)
        self.state.map_data = map_data
        return map_data

    async def get_all_maps(self) -> CommandResponse:
        """Download all saved/reduced maps."""
        return await self.send_command(TOPIC_CMD_GET_ALL_MAPS, timeout=15.0)

    async def get_saved_maps(self) -> GetAllReducedMapsResponse:
        """Query and cache the strict saved/reduced map inventory."""
        resp = await self.get_all_maps()
        product_key = (
            self.state.device_info.product_key
            if self.state.device_info is not None
            else ""
        )
        result = decode_get_all_reduced_maps_response(
            resp.data,
            product_key=product_key,
        )
        self.state.saved_maps = result.maps
        self.state.saved_maps_fetched = True
        return result

    async def get_editable_map(
        self,
        map_id: int | None = None,
        *,
        include_carpet: bool = True,
        include_floor_plan: bool = True,
        request_format: MapRequestFormat = MapRequestFormat.COMPRESSED_GRID,
    ) -> GetEditableMapResponse:
        """Query and cache editable geometry for one map without changing it."""
        if map_id is None and self.state.map_data is not None:
            map_id = self.state.map_data.map_id
        request = GetEditableMapRequest(
            map_id=map_id,
            include_carpet=include_carpet,
            include_floor_plan=include_floor_plan,
            request_format=request_format,
        )
        resp = await self.send_command(
            TOPIC_CMD_GET_EDITABLE_MAP,
            payload=encode_get_editable_map_request(request),
            timeout=15.0,
        )
        product_key = (
            self.state.device_info.product_key
            if self.state.device_info is not None
            else ""
        )
        result = decode_get_editable_map_response(
            resp.data,
            product_key=product_key,
        )
        self.state.editable_map = result
        self.state.editable_map_fetched = True
        return result

    async def check_map_update_info(self) -> CheckMapUpdateInfoResponse:
        """Check and cache whether the official app reports map updates."""
        resp = await self.send_command(
            TOPIC_CMD_CHECK_MAP_UPDATE_INFO,
            timeout=15.0,
        )
        product_key = (
            self.state.device_info.product_key
            if self.state.device_info is not None
            else ""
        )
        result = decode_check_map_update_info_response(
            resp.data,
            product_key=product_key,
        )
        self.state.map_update_info = result
        self.state.map_update_info_fetched = True
        return result

    async def set_manual_control_mode(
        self,
        mode: ManualControlMode | int,
    ) -> CommandResponse:
        """Send the low-level manual-control mode command.

        Motion callers should normally use :meth:`manual_control_pulse`, which
        confirms JOYSTICK state and guarantees the dead-man cleanup sequence.
        """
        mode = ManualControlMode(mode)
        return await self.send_command(
            TOPIC_CMD_SET_MANUAL_CONTROL_MODE,
            payload=encode_set_manual_control_mode(int(mode)),
            timeout=10.0,
        )

    def _require_telecontrol_generation(
        self, expected_generation: int
    ) -> None:
        """Reject motion invalidated by a public stop during preflight."""
        if expected_generation != self._telecontrol_stop_generation:
            raise NarwalCommandError(
                "Telecontrol request was invalidated by a stop command"
            )

    def _raise_if_telecontrol_lock_held(self) -> None:
        """Reject rather than queue a second motion operation."""
        if self._telecontrol_lock.locked():
            raise NarwalCommandError(
                "Another telecontrol operation is already in progress"
            )

    def _raise_if_command_lock_held(self) -> None:
        """Reject motion which would queue behind an unrelated command."""
        if self._command_lock.locked():
            raise NarwalCommandError(
                "Another robot command is already in progress"
            )

    async def start_point_navigation(
        self,
        x: float,
        y: float,
        *,
        theta: float = 0.0,
        expected_generation: int | None = None,
    ) -> CommandResponse:
        """Start the production app's one-point navigation request.

        Coordinates must already be in the robot's raw map/world coordinate
        space. Map revision and traversability checks belong to the caller.
        """
        generation = (
            self._telecontrol_stop_generation
            if expected_generation is None
            else expected_generation
        )
        payload = encode_point_navi_request(
            avoid_carpet_mask=0,
            explore_mode=_POINT_NAVI_PRODUCTION_EXPLORE_MODE,
            points=(
                PoseData(
                    location=Point(x=x, y=y),
                    theta=theta,
                ),
            ),
        )
        if (
            self._manual_control_active
            or self._manual_control_state != int(ManualControlMode.OFF)
        ):
            raise NarwalCommandError(
                "Manual control is already active; stop it before navigation"
            )
        if (
            self._point_navigation_active
            or self._telecontrol_status
            == int(TelecontrolStatus.POINT_NAVI)
            or self.state.working_status == WorkingStatus.TELECONTROL
        ):
            raise NarwalCommandError(
                "Point navigation is already active; cancel it first"
            )
        self._require_telecontrol_generation(generation)
        self._raise_if_command_lock_held()
        self._raise_if_telecontrol_lock_held()
        async with self._telecontrol_lock:
            self._require_telecontrol_generation(generation)
            self._raise_if_command_lock_held()
            self._point_navigation_seen_active = False
            self._point_navigation_frame_sent = False
            self._point_navigation_start_pending = True
            self._point_navigation_completed_before_ack = False

            def _mark_point_navigation_frame_sent() -> None:
                self._require_telecontrol_generation(generation)
                self._point_navigation_frame_sent = True
                # Once the frame is on the socket, fail closed until a known
                # rejection, observed completion, or confirmed stop clears it.
                self._point_navigation_active = True

            try:
                response = await self.send_command(
                    TOPIC_CMD_POINT_NAVI,
                    payload=payload,
                    timeout=10.0,
                    before_send=_mark_point_navigation_frame_sent,
                )
            except BaseException:
                if not self._point_navigation_frame_sent:
                    self._clear_point_navigation_ownership()
                raise
            finally:
                self._point_navigation_start_pending = False
            try:
                self._require_telecontrol_generation(generation)
            except BaseException:
                if not self._point_navigation_frame_sent:
                    self._clear_point_navigation_ownership()
                raise
            if (
                self._command_performed(response)
                and not self._point_navigation_completed_before_ack
            ):
                self._point_navigation_active = True
                self._point_navigation_path = ()
                self.state.point_navigation_path = []
                self.state.point_navigation_target = (x, y)
            elif response.result_known or self._point_navigation_completed_before_ack:
                self._clear_point_navigation_ownership()
            return response

    async def point_navigate(
        self,
        x: float,
        y: float,
        *,
        theta: float = 0.0,
    ) -> CommandResponse:
        """Compatibility alias for :meth:`start_point_navigation`."""
        return await self.start_point_navigation(x, y, theta=theta)

    def _point_navigation_force_end_required(
        self,
        *,
        allow_manual_recovery: bool,
        allow_working_status_recovery: bool,
    ) -> bool:
        """Return whether an observed/owned navigation task warrants force-end.

        ``task/force_end`` is global, so it must never be used merely because a
        visible Stop button was clicked.  The manual-state recovery exception
        is limited to the navigation stop action: AX15 can leave a failed
        point-navigation request reporting JOYSTICK even after generic NAVI
        cancel, as observed live on the target robot.
        """
        if (
            self._point_navigation_active
            or self._point_navigation_frame_sent
            or self._point_navigation_seen_active
            or self._telecontrol_status
            == int(TelecontrolStatus.POINT_NAVI)
            or (
                allow_working_status_recovery
                and self.state.working_status == WorkingStatus.TELECONTROL
            )
        ):
            return True
        return (
            allow_manual_recovery
            and self._manual_control_state != int(ManualControlMode.OFF)
            and not self.state.is_cleaning
            and not self.state.is_returning
            and not self.state.is_station_active
        )

    async def _cancel_point_navigation_locked(self) -> CommandResponse:
        """Send the scoped generic NAVI cancellation under the motion lock."""
        response = await self.send_command(
            TOPIC_CMD_CANCEL,
            payload=encode_cancel_navigation_request(),
            timeout=10.0,
        )
        if self._command_performed(response):
            self._clear_point_navigation_ownership()
        return response

    async def _force_end_point_navigation_locked(self) -> CommandResponse:
        """Use the app's point-navigation recovery route under the lock.

        The extracted Narwal app's point-navigation laboratory tool sends an
        empty ``ForceEndTask_Request`` to ``task/force_end`` when its Stop
        button is pressed.  AX15 does not reliably leave telecontrol after the
        generic ``task/cancel`` / ``CancelTaskType.NAVI`` request, so that
        request remains an immediate best-effort safety frame only.
        """
        return await self.stop(timeout=15.0)

    async def _confirm_point_navigation_stopped_locked(self) -> None:
        """Require a fresh full status snapshot after acknowledged force-end."""
        response = await self.get_status(full_update=True)
        status_data = response.data.get("2")
        if not isinstance(status_data, dict) or not status_data:
            raise NarwalCommandError(
                "Robot did not return a full status after point-navigation stop"
            )
        field3 = status_data.get("3")
        if isinstance(field3, list):
            field3 = field3[0] if field3 else None
        if not isinstance(field3, dict):
            raise NarwalCommandError(
                "Robot status omitted task state after point-navigation stop"
            )
        working_status = field3.get("1")
        if isinstance(working_status, bool) or not isinstance(
            working_status, int
        ):
            raise NarwalCommandError(
                "Robot status omitted working state after point-navigation stop"
            )
        telecontrol_status = field3.get(
            "19", int(TelecontrolStatus.UNSPECIFIED)
        )
        if isinstance(telecontrol_status, bool) or not isinstance(
            telecontrol_status, int
        ):
            raise NarwalCommandError(
                "Robot status contained an invalid telecontrol state"
            )
        manual_control_state = status_data.get(
            "31", int(ManualControlMode.OFF)
        )
        if isinstance(manual_control_state, bool) or not isinstance(
            manual_control_state, int
        ):
            raise NarwalCommandError(
                "Robot status contained an invalid manual-control state"
            )
        if manual_control_state != int(ManualControlMode.OFF):
            raise NarwalCommandError(
                "Robot still reports manual control after force-end"
            )
        if telecontrol_status == int(TelecontrolStatus.POINT_NAVI):
            raise NarwalCommandError(
                "Robot still reports point navigation after force-end"
            )
        if working_status == int(WorkingStatus.TELECONTROL):
            raise NarwalCommandError(
                "Robot still reports telecontrol after force-end"
            )

    async def _complete_telecontrol_stop_locked(self) -> CommandResponse:
        """Confirm a force-end and restore manual control to OFF.

        Do not silently clear the robot-reported manual state: motion remains
        blocked unless the force-end and the dead-man cleanup both complete.
        """
        response: CommandResponse | None = None
        force_end_confirmed = False
        failures: list[Exception] = []
        self._point_navigation_stop_confirmation_pending = True
        try:
            response = await self._force_end_point_navigation_locked()
            if not self._command_performed(response):
                failures.append(
                    NarwalCommandError(
                        "Robot did not acknowledge point-navigation force-end"
                    )
                )
            else:
                force_end_confirmed = True
        except Exception as err:
            failures.append(err)
        try:
            await self._stop_manual_control_locked()
        except Exception as err:
            failures.append(err)
        if force_end_confirmed:
            try:
                await self._confirm_point_navigation_stopped_locked()
            except Exception as err:
                failures.append(err)

        if failures:
            detail = "; ".join(
                f"{type(err).__name__}: {err}" for err in failures
            )
            raise NarwalCommandError(
                "Point-navigation stop was not fully confirmed: "
                f"{detail}"
            )
        if response is None:
            raise NarwalCommandError("Point-navigation stop produced no response")
        self._clear_point_navigation_ownership()
        return response

    async def stop_point_navigation(self) -> CommandResponse:
        """Stop point navigation without force-ending unrelated robot tasks.

        The immediate zero-velocity, generic-NAVI-cancel, and OFF frames are
        deliberately sent before waiting on either command lock.  They bound a
        concurrent joystick/start request.  The typed NAVI cancel is the
        default scoped request; the app's global force-end is reserved for
        confirmed point navigation or the AX15's failed-navigation recovery
        state.
        """
        self._telecontrol_stop_generation += 1
        self._manual_control_abort.set()
        raw_failures = await self._publish_emergency_stop_frames()
        if raw_failures:
            _LOGGER.debug(
                "Immediate point-navigation safety publish had %d failure(s); "
                "continuing with acknowledged navigation cleanup",
                len(raw_failures),
            )
        async with self._telecontrol_lock:
            if self._point_navigation_force_end_required(
                allow_manual_recovery=True,
                allow_working_status_recovery=True,
            ):
                return await self._complete_telecontrol_stop_locked()
            return await self._cancel_point_navigation_locked()

    async def cancel_point_navigation(self) -> CommandResponse:
        """Backward-compatible name for :meth:`stop_point_navigation`."""
        return await self.stop_point_navigation()

    async def _publish_zero_velocity_locked(
        self,
        repeats: int = 3,
    ) -> list[Exception]:
        """Publish repeated zero velocity while holding the motion lock."""
        failures: list[Exception] = []
        payload = encode_telecontrol_velocity(0, 0)
        for index in range(repeats):
            try:
                await self._publish_command(
                    TOPIC_CMD_VELOCITY_CONTROL,
                    payload,
                )
            except Exception as err:
                failures.append(err)
            if index + 1 < repeats:
                await asyncio.sleep(_MANUAL_CONTROL_HEARTBEAT_INTERVAL)
        return failures

    async def _publish_emergency_stop_frames(self) -> list[Exception]:
        """Publish unacknowledged safety frames without waiting on command locks."""
        zero_velocity = encode_telecontrol_velocity(0, 0)
        frames = [
            (TOPIC_CMD_CANCEL, encode_cancel_navigation_request()),
            *[
                (TOPIC_CMD_VELOCITY_CONTROL, zero_velocity)
                for _ in range(3)
            ],
            (
                TOPIC_CMD_SET_MANUAL_CONTROL_MODE,
                encode_set_manual_control_mode(int(ManualControlMode.OFF)),
            ),
        ]
        failures: list[Exception] = []
        for topic, payload in frames:
            try:
                await self._publish_command(topic, payload)
            except Exception as err:
                failures.append(err)
        return failures

    async def _stop_manual_control_locked(self) -> None:
        """Best-effort triple-zero and OFF sequence under the motion lock."""
        failures = await self._publish_zero_velocity_locked()
        try:
            response = await self.send_command(
                TOPIC_CMD_SET_MANUAL_CONTROL_MODE,
                payload=encode_set_manual_control_mode(
                    int(ManualControlMode.OFF)
                ),
                timeout=10.0,
            )
            if not self._command_performed(response):
                failures.append(
                    NarwalCommandError(
                        "Robot did not acknowledge manual-control OFF"
                    )
                )
            elif not await self._wait_for_manual_control_state(
                int(ManualControlMode.OFF)
            ):
                # AX15 can acknowledge OFF before its final standby broadcast
                # reaches this listener. Confirm with an immediate fresh base
                # status rather than treating a missed broadcast as failure.
                await self.get_status(full_update=True, require_full=True)
                if (
                    self._manual_control_state
                    != int(ManualControlMode.OFF)
                    or self.state.working_status
                    == WorkingStatus.TELECONTROL
                ):
                    failures.append(
                        NarwalCommandError(
                            "Robot did not report manual-control OFF"
                        )
                    )
        except Exception as err:
            failures.append(err)
        finally:
            self._manual_control_active = False

        if failures:
            detail = "; ".join(
                f"{type(err).__name__}: {err}" for err in failures
            )
            raise NarwalCommandError(
                "Manual-control cleanup was not fully confirmed: "
                f"{detail}"
            )

    async def manual_control_pulse(
        self,
        linear_velocity: int,
        angular_velocity: int,
        *,
        duration: float = 0.25,
        expected_generation: int | None = None,
    ) -> CommandResponse:
        """Send a bounded dead-man joystick pulse, then triple-zero and OFF."""
        generation = (
            self._telecontrol_stop_generation
            if expected_generation is None
            else expected_generation
        )
        if isinstance(linear_velocity, bool) or not isinstance(
            linear_velocity, int
        ):
            raise TypeError("linear_velocity must be an integer")
        if isinstance(angular_velocity, bool) or not isinstance(
            angular_velocity, int
        ):
            raise TypeError("angular_velocity must be an integer")
        if not -_MAX_MANUAL_CONTROL_COMMAND <= linear_velocity <= (
            _MAX_MANUAL_CONTROL_COMMAND
        ):
            raise ValueError(
                "linear_velocity must be between -10 and 10"
            )
        if not -_MAX_MANUAL_CONTROL_COMMAND <= angular_velocity <= (
            _MAX_MANUAL_CONTROL_COMMAND
        ):
            raise ValueError(
                "angular_velocity must be between -10 and 10"
            )
        if linear_velocity == 0 and angular_velocity == 0:
            raise ValueError(
                "At least one velocity component must be non-zero"
            )
        if isinstance(duration, bool) or not isinstance(
            duration, (int, float)
        ):
            raise TypeError("duration must be a real number")
        duration = float(duration)
        if not 0 < duration <= _MAX_MANUAL_CONTROL_PULSE_SECONDS:
            raise ValueError(
                "duration must be greater than 0 and at most 0.5 seconds"
            )

        if (
            self._manual_control_active
            or self._manual_control_state != int(ManualControlMode.OFF)
        ):
            raise NarwalCommandError(
                "Manual control is already active; stop it before another pulse"
            )
        if (
            self._point_navigation_active
            or self._telecontrol_status
            == int(TelecontrolStatus.POINT_NAVI)
            or self.state.working_status == WorkingStatus.TELECONTROL
        ):
            raise NarwalCommandError(
                "Point navigation is already active; cancel it before driving"
            )
        self._require_telecontrol_generation(generation)
        self._raise_if_command_lock_held()
        self._raise_if_telecontrol_lock_held()
        async with self._telecontrol_lock:
            self._require_telecontrol_generation(generation)
            self._raise_if_command_lock_held()
            self._manual_control_abort.clear()
            primary_error: BaseException | None = None
            try:
                response = await self.send_command(
                    TOPIC_CMD_SET_MANUAL_CONTROL_MODE,
                    payload=encode_set_manual_control_mode(
                        int(ManualControlMode.JOYSTICK)
                    ),
                    timeout=10.0,
                    before_send=lambda: self._require_telecontrol_generation(
                        generation
                    ),
                )
                self._require_telecontrol_generation(generation)
                if not self._command_performed(response):
                    return response
                if not await self._wait_for_manual_control_state(
                    int(ManualControlMode.JOYSTICK)
                ):
                    raise NarwalCommandError(
                        "Robot acknowledged joystick mode but did not report it"
                    )

                self._manual_control_active = True
                velocity_payload = encode_telecontrol_velocity(
                    linear_velocity,
                    angular_velocity,
                )
                deadline = time.monotonic() + duration
                while (
                    time.monotonic() < deadline
                    and not self._manual_control_abort.is_set()
                ):
                    await self._publish_command(
                        TOPIC_CMD_VELOCITY_CONTROL,
                        velocity_payload,
                    )
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    try:
                        await asyncio.wait_for(
                            self._manual_control_abort.wait(),
                            timeout=min(
                                _MANUAL_CONTROL_HEARTBEAT_INTERVAL,
                                remaining,
                            ),
                        )
                    except TimeoutError:
                        continue
                return response
            except BaseException as err:
                primary_error = err
                raise
            finally:
                try:
                    await self._stop_manual_control_locked()
                except Exception:
                    if primary_error is None:
                        raise
                    _LOGGER.exception(
                        "Manual-control cleanup failed after pulse error"
                    )

    async def send_velocity(
        self,
        linear: int,
        angular: int,
        *,
        duration: float = 0.25,
    ) -> CommandResponse:
        """Compatibility alias for the bounded dead-man pulse."""
        return await self.manual_control_pulse(
            linear,
            angular,
            duration=duration,
        )

    async def emergency_stop_telecontrol(self) -> None:
        """Abort telecontrol with an immediate dead-man stop.

        A joystick release never force-ends an unrelated cleaning task.  The
        point-navigation recovery force-end is only used when navigation is
        client-owned or robot-observed.
        """
        self._telecontrol_stop_generation += 1
        self._manual_control_abort.set()
        raw_failures = await self._publish_emergency_stop_frames()
        if raw_failures:
            _LOGGER.debug(
                "Immediate telecontrol safety publish had %d failure(s); "
                "continuing with acknowledged cleanup",
                len(raw_failures),
            )
        async with self._telecontrol_lock:
            try:
                if self._point_navigation_force_end_required(
                    allow_manual_recovery=False,
                    allow_working_status_recovery=False,
                ):
                    await self._complete_telecontrol_stop_locked()
                else:
                    await self._stop_manual_control_locked()
            except Exception as err:
                raise NarwalCommandError(
                    "Telecontrol emergency stop was not fully confirmed: "
                    f"{type(err).__name__}: {err}"
                ) from err

    async def take_picture(self) -> bytes | None:
        """Capture a photo from the robot's camera.

        Returns raw image bytes from field 2 of the response, or None on failure.
        Note: the image is AES-encrypted; decoding requires the APK-derived key
        which is not yet known. Callers receive raw bytes as-is.
        """
        try:
            resp = await self.send_command(TOPIC_CMD_TAKE_PICTURE, timeout=15.0)
        except Exception:
            _LOGGER.warning("take_picture command failed")
            return None
        if resp.result_code == CommandResult.SUCCESS:
            return resp.data.get("2")
        _LOGGER.warning("take_picture returned result_code=%d", resp.result_code)
        return None

    async def set_led(self, on: bool) -> None:
        """Turn the camera LED fill light on or off.

        Payload: 0x08 0x01 = on, 0x08 0x00 = off (protobuf field 1, varint).
        """
        payload = b"\x08\x01" if on else b"\x08\x00"
        try:
            resp = await self.send_command(TOPIC_CMD_SET_LED, payload=payload)
        except Exception:
            _LOGGER.warning("set_led(%s) command failed", on)
            return
        if resp.result_code not in (CommandResult.SUCCESS, CommandResult.NOT_APPLICABLE):
            _LOGGER.warning(
                "set_led(%s) unexpected result_code=%d", on, resp.result_code
            )
