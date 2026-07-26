"""Tests for fail-closed model and firmware operation profiles."""

from __future__ import annotations

from types import SimpleNamespace

import tests.ha_stubs

tests.ha_stubs.install()

from custom_components.narwal.profile import profile_for_client  # noqa: E402
from narwal_client.capabilities import Capability  # noqa: E402
from narwal_client.models import DeviceInfo, NarwalState  # noqa: E402


def _client(
    product_key: str,
    firmware: str,
    capabilities: dict[int, int] | None = None,
) -> SimpleNamespace:
    state = NarwalState(
        device_info=DeviceInfo(
            product_key=product_key,
            firmware_version=firmware,
        ),
        capabilities=capabilities or {},
    )
    return SimpleNamespace(state=state, topic_prefix=f"/{product_key}")


def test_x10_parameterized_clean_fails_closed_by_default() -> None:
    client = _client(
        "CNbforyZWI",
        "v01.03.10.03",
        {int(Capability.MULTI_ZONE_CLEAN): 1},
    )

    profile = profile_for_client(client)

    assert profile.display_model == "Narwal Freo X10 Pro"
    assert profile.hardware_model == "AX15"
    assert not profile.parameterized_clean_enabled


def test_x10_exact_probe_firmware_can_be_explicitly_opted_in() -> None:
    client = _client(
        "CNbforyZWI",
        "v01.03.10.03",
        {int(Capability.MULTI_ZONE_CLEAN): 1},
    )

    profile = profile_for_client(client, experimental_cleaning=True)

    assert profile.parameterized_clean_experimental
    assert not profile.parameterized_clean_enabled
    assert profile.parameterized_clean_validation_enabled


def test_x10_unknown_firmware_stays_closed_even_with_opt_in() -> None:
    client = _client(
        "CNbforyZWI",
        "v99.99.99.99",
        {int(Capability.MULTI_ZONE_CLEAN): 1},
    )

    assert not profile_for_client(
        client,
        experimental_cleaning=True,
    ).parameterized_clean_validation_enabled


def test_capability_is_required_but_not_sufficient() -> None:
    client = _client("CNbforyZWI", "v01.03.10.03")

    assert not profile_for_client(
        client,
        experimental_cleaning=True,
    ).parameterized_clean_validation_enabled


def test_flow2_without_an_exact_validation_record_stays_closed() -> None:
    client = _client(
        "QxMSPG6VSO",
        "v01.07.23.00",
        {int(Capability.MULTI_ZONE_CLEAN): 1},
    )

    profile = profile_for_client(client)

    assert not profile.parameterized_clean_validated
    assert not profile.parameterized_clean_enabled


def test_station_and_config_writes_are_not_in_the_first_profile() -> None:
    client = _client(
        "CNbforyZWI",
        "v01.03.10.03",
        {
            int(Capability.WASH_MOP_BY_ROBOT_STATUS): 1,
            int(Capability.AVOID_MODE_CONFIG): 1,
        },
    )

    profile = profile_for_client(client, experimental_cleaning=True)

    assert profile.station_actions == frozenset()
    assert not profile.config_writes_enabled
