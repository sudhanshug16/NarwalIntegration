"""Tests for command response classification and request routing."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

from narwal_client.client import NarwalClient
from narwal_client.const import CommandResult
from narwal_client.protocol import (
    NarwalHeader,
    NarwalProperties,
    build_frame,
    parse_frame,
)


def _rich_response(
    response_url: str | None,
    payload: bytes = b"\x08\x01",
    *,
    correlation_data: str | None = "request-id",
) -> bytes:
    """Build a response whose first Header field is deliberately not field 5."""
    return build_frame(
        "",
        payload,
        header=NarwalHeader(
            uuid="robot-message-id",
            properties=NarwalProperties(
                response_url=response_url,
                correlation_data=correlation_data,
            ),
        ),
    )


def _connected_listener_client() -> NarwalClient:
    client = NarwalClient("127.0.0.1", device_id="device-123")
    client._ws = AsyncMock()
    client._connected.set()
    client._listener_active = True
    return client


class TestResponseRouting:
    """A command only consumes responses routed to its topic."""

    def test_rich_header_is_classified_even_when_uuid_is_first(self) -> None:
        client = _connected_listener_client()
        response = _rich_response(
            "/QoEsI5qYXO/device-123/clean/start_clean/response"
        )

        asyncio.run(client._handle_message(response))

        assert client._response_queue.qsize() == 1
        assert not client.robot_awake

    def test_interleaved_response_is_retained_until_expected_response(self) -> None:
        client = _connected_listener_client()
        stale = _rich_response(
            "/QoEsI5qYXO/device-123/info/get_device_info/response",
            b"\x08\x06",
            correlation_data="stale-request",
        )
        expected = _rich_response(
            "/QoEsI5qYXO/device-123/clean/start_clean/response",
            b"\x08\x01",
            correlation_data="active-request",
        )

        async def send_and_deliver(_request: bytes) -> None:
            await client._handle_message(stale)
            await client._handle_message(expected)

        client._ws.send.side_effect = send_and_deliver
        response = asyncio.run(client.send_command("clean/start_clean"))

        assert response.result_known
        assert response.result_code == CommandResult.SUCCESS
        assert len(client._retained_responses) == 1
        assert (
            client._retained_responses[0].header.response_url
            == "/QoEsI5qYXO/device-123/info/get_device_info/response"
        )

    def test_preexisting_same_topic_response_is_not_reused(self) -> None:
        client = _connected_listener_client()
        topic = "/QoEsI5qYXO/device-123/clean/start_clean/response"
        stale = parse_frame(_rich_response(topic, b"\x08\x06"))
        client._response_queue.put_nowait(stale)

        async def deliver_fresh(_request: bytes) -> None:
            await client._handle_message(_rich_response(topic, b"\x08\x01"))

        client._ws.send.side_effect = deliver_fresh
        response = asyncio.run(client.send_command("clean/start_clean"))

        assert response.result_code == CommandResult.SUCCESS
        assert list(client._retained_responses) == [stale]

    def test_direct_receive_skips_wrong_routed_response(self) -> None:
        client = _connected_listener_client()
        client._listener_active = False
        stale = _rich_response(
            "/QoEsI5qYXO/device-123/common/get_feature_list/response"
        )
        expected = _rich_response(
            "clean/start_clean/response",
            b"\x08\x01",
        )
        client._ws.recv.side_effect = [stale, expected]

        response = asyncio.run(client.send_command("clean/start_clean"))

        assert response.success
        assert len(client._retained_responses) == 1

    def test_discovery_ignores_field_two_from_an_unrelated_response(self) -> None:
        client = _connected_listener_client()
        client._listener_active = False
        wrong_device_id = b"\x12\x08wrong-id"
        expected_device_id = b"\x12\x0adevice-456"
        client._ws.recv.side_effect = [
            _rich_response(
                "/QoEsI5qYXO/device-123/unrelated/query/response",
                wrong_device_id,
            ),
            _rich_response(
                "/QoEsI5qYXO/device-123/common/get_device_info/response",
                expected_device_id,
            ),
        ]

        device_id = asyncio.run(client.discover_device_id())

        assert device_id == "device-456"
        assert len(client._retained_responses) == 1

    def test_correlation_only_response_is_retained_not_guessed(self) -> None:
        client = _connected_listener_client()
        correlation_only = _rich_response(None, correlation_data="unknown-request")
        expected = _rich_response(
            "/QoEsI5qYXO/device-123/clean/start_clean/response"
        )

        async def send_and_deliver(_request: bytes) -> None:
            await client._handle_message(correlation_only)
            await client._handle_message(expected)

        client._ws.send.side_effect = send_and_deliver
        response = asyncio.run(client.send_command("clean/start_clean"))

        assert response.success
        assert len(client._retained_responses) == 1
        assert (
            client._retained_responses[0].header.correlation_data
            == "unknown-request"
        )

    def test_unrouted_field5_remains_legacy_fifo_fallback(self) -> None:
        client = _connected_listener_client()
        legacy = build_frame(
            "",
            b"\x08\x01",
            header=NarwalHeader(properties=NarwalProperties()),
        )

        async def send_and_deliver(_request: bytes) -> None:
            await client._handle_message(legacy)

        client._ws.send.side_effect = send_and_deliver
        response = asyncio.run(client.send_command("clean/start_clean"))

        assert response.success
        assert not client._retained_responses

    def test_request_header_stays_url_only(self) -> None:
        client = _connected_listener_client()

        async def send_and_deliver(request: bytes) -> None:
            await client._handle_message(
                _rich_response(
                    "/QoEsI5qYXO/device-123/clean/start_clean/response"
                )
            )
            parsed_request = parse_frame(request)
            assert parsed_request.header == NarwalHeader(
                url="/QoEsI5qYXO/device-123/clean/start_clean"
            )

        client._ws.send.side_effect = send_and_deliver

        asyncio.run(client.send_command("clean/start_clean"))


class TestCommandResultInference:
    """Structured query data is not universally promoted to action success."""

    def test_nested_field_one_has_unknown_result(self) -> None:
        client = _connected_listener_client()
        nested_field_one = b"\x0a\x02\x08\x01"

        async def send_and_deliver(_request: bytes) -> None:
            await client._handle_message(
                _rich_response(
                    "/QoEsI5qYXO/device-123/config/get/response",
                    nested_field_one,
                )
            )

        client._ws.send.side_effect = send_and_deliver
        response = asyncio.run(client.send_command("config/get"))

        assert response.data == {"1": {"1": 1}}
        assert response.result_code == 0
        assert not response.result_known
        assert not response.success

    def test_explicit_integer_result_remains_known(self) -> None:
        client = _connected_listener_client()

        async def send_and_deliver(_request: bytes) -> None:
            await client._handle_message(
                _rich_response(
                    "/QoEsI5qYXO/device-123/clean/start_clean/response",
                    b"\x08\x01",
                )
            )

        client._ws.send.side_effect = send_and_deliver
        response = asyncio.run(client.send_command("clean/start_clean"))

        assert response.result_known
        assert response.success
