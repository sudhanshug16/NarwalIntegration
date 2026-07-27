"""DataUpdateCoordinator for Narwal vacuum."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import timedelta
from enum import IntEnum

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN
from .narwal_client import (
    ConfigSnapshot,
    GetCleanSchedulesResponse,
    ManualControlMode,
    NarwalClient,
    NarwalCommandError,
    NarwalConnectionError,
    NarwalState,
    SetConfigField,
    SetConfigPatch,
    TelecontrolStatus,
)
from .narwal_client.const import ACTIVE_CLEANING_STATUSES, WorkingStatus
from .profile import DeviceProfile, profile_for_client

_LOGGER = logging.getLogger(__name__)

POLL_INTERVAL = timedelta(seconds=60)

# Fast re-poll when state is incomplete (robot asleep at startup)
FAST_POLL_INTERVAL = timedelta(seconds=10)
FAST_POLL_MAX = 6  # up to 60s of fast polling before falling back to normal


def active_telecontrol_reason(client: NarwalClient) -> str | None:
    """Return a fail-closed reason when movement is owned by telecontrol.

    A point-navigation request can remain active after its short startup
    transaction releases the coordinator action lock. Every subsequent
    physical action must consult both client ownership and explicit robot
    telemetry before it assumes the dock/robot is safe to repurpose.
    """
    manual_active = getattr(client, "manual_control_active", False)
    if manual_active is True:
        return "Manual control is active; call stop_telecontrol first"

    manual_state = getattr(client, "manual_control_state", int(ManualControlMode.OFF))
    if (
        isinstance(manual_state, int)
        and not isinstance(manual_state, bool)
        and manual_state != int(ManualControlMode.OFF)
    ):
        return "Manual control is active; call stop_telecontrol first"

    point_navigation_active = getattr(client, "point_navigation_active", False)
    if point_navigation_active is True:
        return "Point navigation is active; call stop_navigation first"

    telecontrol_status = getattr(
        client,
        "telecontrol_status",
        int(TelecontrolStatus.UNSPECIFIED),
    )
    if (
        isinstance(telecontrol_status, int)
        and not isinstance(telecontrol_status, bool)
        and telecontrol_status == int(TelecontrolStatus.POINT_NAVI)
    ):
        return "Point navigation is active; call stop_navigation first"
    return None


class NarwalCoordinator(DataUpdateCoordinator[NarwalState]):
    """Push-mode coordinator for Narwal vacuum.

    Primary data source is WebSocket broadcasts (every ~1.5s when awake).
    Fallback polling every 60s via get_status() in case broadcasts stop.

    Setup is kept fast: connect, try a few commands (which may time out if
    the robot is asleep), then start the listener. The listener's keepalive
    loop handles waking the robot — no blocking wake call during setup.
    """

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=POLL_INTERVAL,
        )
        product_key = entry.data.get("product_key")
        topic_prefix = f"/{product_key}" if product_key else None
        self.client = NarwalClient(
            host=entry.data["host"],
            port=entry.data["port"],
            device_id=entry.data.get("device_id", ""),
            topic_prefix=topic_prefix,
        )
        self._listen_task: asyncio.Task[None] | None = None
        self._fast_poll_remaining = 0
        self._prev_working_status = WorkingStatus.UNKNOWN
        self._map_fetch_pending = False
        self._last_display_map_resub: float = 0.0
        self._inventory_fetch_pending = False
        self._last_inventory_attempt: float = 0.0
        self._consecutive_failures = 0
        self._max_failures = 5  # 5 * 60s = 5 minutes before entities go unavailable
        self.select_options: dict[str, str] = {}
        # Every state-changing robot/station action shares one fail-fast lock.
        # The lock spans refresh + guard + command so a station task cannot
        # start between a navigation/config/schedule preflight and its write.
        self.action_lock = asyncio.Lock()
        # Kept as an alias for integrations/tests that referred to the earlier
        # station-only name. It deliberately points at the shared lock.
        self.station_action_lock = self.action_lock

    @property
    def device_profile(self) -> DeviceProfile:
        """Return the current model/firmware profile."""
        return profile_for_client(self.client)

    @property
    def parameterized_clean_enabled(self) -> bool:
        """Return whether full clean controls are available."""
        return self.device_profile.parameterized_clean_enabled

    @property
    def telecontrol_enabled(self) -> bool:
        """Return whether this device exposes bounded telecontrol actions."""
        return self.device_profile.telecontrol_enabled

    @property
    def config_writes_enabled(self) -> bool:
        """Return whether this device exposes verified config writes."""
        return self.device_profile.config_writes_enabled

    def exclusive_action_lock(self, action: str) -> asyncio.Lock:
        """Return the shared physical-action lock or fail instead of queueing."""
        if self.action_lock.locked():
            raise NarwalCommandError(
                f"Another Narwal action is already in progress; cannot {action}"
            )
        return self.action_lock

    def assert_no_active_telecontrol(self) -> None:
        """Reject a competing physical action while telecontrol owns motion."""
        if reason := active_telecontrol_reason(self.client):
            raise NarwalCommandError(reason)

    async def async_set_config(
        self,
        field: SetConfigField,
        value: bool | int | IntEnum,
    ) -> ConfigSnapshot:
        """Write one AX15 setting after capability and live-state checks."""
        patch = SetConfigPatch(field=field, value=value)
        if not self.config_writes_enabled:
            raise NarwalCommandError(
                "Configuration writes require an AX15 robot advertising "
                "UPLOAD_CONFIGURATION"
            )

        async with self.exclusive_action_lock("change configuration"):
            return await self._async_set_config_locked(patch)

    async def _async_set_config_locked(
        self,
        patch: SetConfigPatch,
    ) -> ConfigSnapshot:
        """Run one configuration transaction while the action lock is held."""

        client = self.client
        try:
            if not client.robot_awake:
                woke = await client.wake(timeout=10.0)
                if not woke:
                    raise NarwalCommandError(
                        "Could not wake the robot for a configuration write"
                    )
            await client.get_status(full_update=True)
        except NarwalCommandError:
            raise
        except Exception as err:
            raise NarwalCommandError(
                "Could not confirm the robot state for a configuration write"
            ) from err

        state = client.state
        if (
            state.is_cleaning
            or state.is_paused_during_active_task
            or state.is_returning
        ):
            raise NarwalCommandError(
                "Configuration writes are blocked during cleaning, pause, "
                "or return-to-dock tasks"
            )
        if state.is_station_active:
            raise NarwalCommandError(
                "Configuration writes are blocked during base-station tasks"
            )
        self.assert_no_active_telecontrol()

        snapshot = await client.set_config_patch(patch)
        self.async_set_updated_data(client.state)
        return snapshot

    async def async_set_schedule_enabled(
        self,
        task_id: int,
        enabled: bool,
    ) -> GetCleanSchedulesResponse:
        """Enable or disable one existing schedule with exact read-back."""
        if not self.device_profile.schedule_inventory_enabled:
            raise NarwalCommandError(
                "Schedule control is not available for this model and capability set"
            )

        async with self.exclusive_action_lock("change a schedule"):
            return await self._async_set_schedule_enabled_locked(task_id, enabled)

    async def _async_set_schedule_enabled_locked(
        self,
        task_id: int,
        enabled: bool,
    ) -> GetCleanSchedulesResponse:
        """Run one schedule transaction while the action lock is held."""
        client = self.client
        if not client.robot_awake:
            woke = await client.wake(timeout=10.0)
            if not woke:
                raise NarwalCommandError("Could not wake the robot for schedule control")
        await client.get_status(full_update=True)
        state = client.state
        if (
            state.is_cleaning
            or state.is_paused_during_active_task
            or state.is_returning
        ):
            raise NarwalCommandError(
                "Schedule changes are blocked during cleaning or navigation"
            )
        if state.is_station_active:
            raise NarwalCommandError(
                "Schedule changes are blocked during base-station tasks"
            )
        self.assert_no_active_telecontrol()
        result = await client.set_clean_schedule_enabled(task_id, enabled)
        self.async_set_updated_data(client.state)
        return result

    async def async_setup(self) -> None:
        """Connect to the vacuum and start the WebSocket listener.

        Queries initial state BEFORE starting the listener to avoid
        concurrent recv issues (see 446be16). Each command is wrapped in
        try/except so setup never crashes if the robot is asleep.
        The listener's keepalive loop handles waking independently.
        """
        await self.client.connect()

        # Fetch initial state BEFORE starting listener (no concurrent recv)
        try:
            await self.client.get_device_info()
        except Exception:
            _LOGGER.debug("Could not fetch device info at startup")

        try:
            await self.client.get_feature_list()
        except Exception:
            _LOGGER.debug("Could not fetch device capabilities at startup")

        try:
            await self.client.get_status(full_update=True)
        except Exception:
            _LOGGER.debug("Could not fetch initial status")

        try:
            await self.client.get_config()
        except Exception:
            _LOGGER.debug("Could not fetch read-only configuration snapshot")

        try:
            await self.client.get_current_task()
        except Exception:
            _LOGGER.debug("Could not fetch current clean-task diagnostics")

        try:
            await self.client.get_map()
        except Exception:
            _LOGGER.debug("Could not fetch initial map")

        # Subscribe to broadcast topics (display_map, working_status, etc.)
        # Must be sent before listener starts so display_map flows during cleaning.
        try:
            await self.client.subscribe_to_topics()
        except Exception:
            _LOGGER.debug("Could not send topic subscription at startup")

        self.async_set_updated_data(self.client.state)

        # Set up push callback and start persistent listener
        self.client.on_state_update = self._on_state_update
        self._listen_task = self.config_entry.async_create_background_task(
            self.hass,
            self.client.start_listening(),
            f"{DOMAIN}_ws_listener",
        )
        if self.client.robot_awake:
            self._schedule_read_only_inventory_refresh()

        state = self.client.state
        _LOGGER.info(
            "Narwal startup: status=%s, battery=%d, docked=%s, awake=%s",
            state.working_status.name, state.battery_level,
            state.is_docked, self.client.robot_awake,
        )

        # If robot didn't respond, use fast polling to catch it when it wakes
        if state.working_status == WorkingStatus.UNKNOWN:
            self._fast_poll_remaining = FAST_POLL_MAX
            self.update_interval = FAST_POLL_INTERVAL
            _LOGGER.info(
                "Robot asleep — fast polling every %ds until it responds",
                int(FAST_POLL_INTERVAL.total_seconds()),
            )

    def _on_state_update(self, state: NarwalState) -> None:
        """Handle a push state update from the WebSocket listener."""
        # Push data arriving means robot is reachable — reset failure counter
        self._consecutive_failures = 0

        # Fetch static map if missing (get_map failed at startup)
        if state.map_data is None and not self._map_fetch_pending:
            self._map_fetch_pending = True
            self.config_entry.async_create_background_task(
                self.hass,
                self._fetch_missing_map(),
                f"{DOMAIN}_map_fetch",
            )

        # Detect return-to-dock transition: CLEANING/CLEANING_ALT → docked state.
        # Broadcast dock fields are stale after docking — immediate poll
        # refreshes them so UI shows DOCKED instead of IDLE.
        # On older FW the transition is → STANDBY; on v01.07.23+ it may
        # go directly to DOCKED_V2(2).
        if (
            state.working_status in (
                WorkingStatus.STANDBY, WorkingStatus.DOCKED_V2,
            )
            and self._prev_working_status in ACTIVE_CLEANING_STATUSES
        ):
            _LOGGER.info("Return-to-dock detected, refreshing dock status")
            self.hass.async_create_task(self._refresh_dock_status())
        self._prev_working_status = state.working_status

        # display_map dropout recovery: if cleaning but no display_map for
        # 30s, re-send topic subscription. Only subscription — no wake burst
        # (wake bursts during cleaning cause pause bouncing).
        is_cleaning = state.working_status in ACTIVE_CLEANING_STATUSES
        if is_cleaning:
            display_age = self.client.last_display_map_age
            now = time.monotonic()
            if (
                display_age > 30.0
                and now - self._last_display_map_resub > 45.0
            ):
                _LOGGER.info(
                    "display_map dropout (%.0fs) — re-subscribing to topics",
                    display_age,
                )
                self._last_display_map_resub = now
                self.config_entry.async_create_background_task(
                    self.hass,
                    self._resub_topics(),
                    f"{DOMAIN}_resub",
                )

        self.async_set_updated_data(state)

        if (
            not getattr(self, "_inventory_fetch_pending", False)
            and time.monotonic()
            - getattr(self, "_last_inventory_attempt", 0.0)
            >= 300
        ):
            self._schedule_read_only_inventory_refresh()

        # Broadcast arrived — switch back to normal polling if in fast mode
        if self._fast_poll_remaining > 0:
            self._fast_poll_remaining = 0
            self.update_interval = POLL_INTERVAL
            _LOGGER.info(
                "Broadcast received (status=%s) — normal polling restored",
                state.working_status.name,
            )

    async def _fetch_missing_map(self) -> None:
        """Fetch static map when it's missing (get_map failed at startup)."""
        try:
            await self.client.get_map()
            _LOGGER.info("Static map loaded (was missing at startup)")
        except Exception:
            _LOGGER.debug("Map fetch failed — will retry on next broadcast")
            self._map_fetch_pending = False
            return
        try:
            await self.client.subscribe_to_topics()
        except Exception:
            _LOGGER.debug("Topic subscription failed after map load")
        self.async_set_updated_data(self.client.state)

    async def _resub_topics(self) -> None:
        """Re-send topic subscription to recover display_map during cleaning."""
        try:
            await self.client.subscribe_to_topics()
        except Exception:
            _LOGGER.debug("Topic re-subscription failed")

    def _schedule_read_only_inventory_refresh(self) -> None:
        """Schedule low-frequency plan/schedule/map/maintenance metadata reads."""
        profile = self.device_profile
        if not (
            profile.clean_plan_inventory_enabled
            or profile.schedule_inventory_enabled
            or profile.saved_map_inventory_enabled
            or profile.editable_map_inventory_enabled
            or profile.map_update_inventory_enabled
            or profile.consumable_inventory_enabled
            or profile.firmware_inventory_enabled
            or profile.language_inventory_enabled
            or profile.voice_inventory_enabled
            or profile.history_inventory_enabled
        ):
            return
        if getattr(self, "_inventory_fetch_pending", False):
            return
        self._inventory_fetch_pending = True
        self._last_inventory_attempt = time.monotonic()
        self.config_entry.async_create_background_task(
            self.hass,
            self._refresh_read_only_inventory(),
            f"{DOMAIN}_inventory_refresh",
        )

    async def _refresh_read_only_inventory(self) -> None:
        """Refresh capability-backed official-app inventories without writes."""
        try:
            profile = self.device_profile
            if profile.clean_plan_inventory_enabled:
                try:
                    await self.client.get_current_clean_plan()
                    await self.client.get_clean_plans()
                except Exception:
                    _LOGGER.debug("Could not refresh clean-plan inventory")
            if profile.schedule_inventory_enabled:
                try:
                    await self.client.get_clean_schedules()
                except Exception:
                    _LOGGER.debug("Could not refresh cleaning schedules")
            if profile.consumable_inventory_enabled:
                try:
                    await self.client.get_consumable_info()
                except Exception:
                    _LOGGER.debug("Could not refresh consumable categories")
            if profile.saved_map_inventory_enabled:
                try:
                    await self.client.get_saved_maps()
                except Exception:
                    _LOGGER.debug("Could not refresh saved-map inventory")
            if profile.editable_map_inventory_enabled:
                try:
                    await self.client.get_editable_map()
                except Exception:
                    _LOGGER.debug("Could not refresh editable-map metadata")
            if profile.map_update_inventory_enabled:
                try:
                    await self.client.check_map_update_info()
                except Exception:
                    _LOGGER.debug("Could not refresh supplementary map-update info")
            if profile.firmware_inventory_enabled:
                try:
                    await self.client.get_firmware_metadata()
                except Exception:
                    _LOGGER.debug("Could not refresh component firmware metadata")
            if profile.language_inventory_enabled:
                try:
                    await self.client.get_language_metadata()
                    await self.client.get_supported_languages()
                except Exception:
                    _LOGGER.debug("Could not refresh language metadata")
            if profile.voice_inventory_enabled:
                try:
                    await self.client.get_current_voice_info()
                except Exception:
                    _LOGGER.debug("Could not refresh voice-package metadata")
            if profile.history_inventory_enabled:
                try:
                    await self.client.get_clean_timeline()
                except Exception:
                    _LOGGER.debug("Could not refresh local cleaning timeline")
            self.async_set_updated_data(self.client.state)
        finally:
            self._inventory_fetch_pending = False

    async def _refresh_dock_status(self) -> None:
        """Immediate get_status() after return-to-dock to refresh dock fields."""
        try:
            await self.client.get_status(full_update=True)
            self.async_set_updated_data(self.client.state)
        except Exception:
            _LOGGER.debug("Failed to refresh dock status after transition")

    async def _async_update_data(self) -> NarwalState:
        """Polling fallback — fetch status if no push updates arrived.

        Reconnection is handled by the listener loop's exponential backoff.
        We do NOT call client.connect() here to avoid racing with the listener
        and violating the single-WS-connection-per-IP constraint.

        On poll failure, returns stale data for up to _max_failures consecutive
        failures (~5 minutes) before raising UpdateFailed.
        """
        try:
            if not self.client.connected:
                raise NarwalConnectionError("Not connected")
            await self.client.get_status(full_update=True)
        except Exception as err:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._max_failures:
                raise UpdateFailed(
                    f"Vacuum unreachable for {self._consecutive_failures} consecutive polls"
                ) from err
            _LOGGER.debug(
                "Poll %d/%d failed (robot may be asleep): %s",
                self._consecutive_failures, self._max_failures, err,
            )
            return self.client.state  # stale data keeps entities available
        else:
            self._consecutive_failures = 0

        # Retry map fetch if it failed during setup
        if self.client.state.map_data is None:
            try:
                await self.client.get_map()
            except Exception:
                pass

        # These queries are read-only. Retry missing discovery snapshots once
        # the robot is awake, and refresh the current task while work is active.
        if not self.client.state.capabilities_fetched:
            try:
                await self.client.get_feature_list()
            except Exception:
                pass
        if self.client.state.config_snapshot is None:
            try:
                await self.client.get_config()
            except Exception:
                pass
        if self.client.state.working_status in ACTIVE_CLEANING_STATUSES:
            try:
                await self.client.get_current_task()
            except Exception:
                pass

        # Manage fast poll countdown
        if self._fast_poll_remaining > 0:
            if self.client.state.working_status != WorkingStatus.UNKNOWN:
                self._fast_poll_remaining = 0
                self.update_interval = POLL_INTERVAL
            else:
                self._fast_poll_remaining -= 1
                if self._fast_poll_remaining <= 0:
                    self.update_interval = POLL_INTERVAL

        return self.client.state

    async def async_shutdown(self) -> None:
        """Disconnect from the vacuum."""
        await self.client.disconnect()
        if self._listen_task and not self._listen_task.done():
            self._listen_task.cancel()
        await super().async_shutdown()
