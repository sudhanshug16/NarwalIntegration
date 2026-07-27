"""Tests for the complete Narwal WebSocket envelope codec."""

from __future__ import annotations

import pytest

from narwal_client.protocol import (
    PROTOBUF_FIELD5_TAG,
    NarwalHeader,
    NarwalMessage,
    NarwalProperties,
    ProtocolError,
    build_frame,
    parse_frame,
)


def _varint(value: int) -> bytes:
    """Encode a protobuf varint independently of the implementation."""
    encoded = bytearray()
    while value >= 0x80:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _string_field(field_number: int, value: str) -> bytes:
    encoded = value.encode()
    return _varint((field_number << 3) | 2) + _varint(len(encoded)) + encoded


def _frame(header: bytes, payload: bytes = b"") -> bytes:
    return b"\x01" + _varint(len(header)) + header + payload


class TestParseFrame:
    """Tests for parse_frame()."""

    def test_parse_valid_legacy_shape(
        self,
        sample_frame: bytes,
        sample_topic: str,
    ) -> None:
        msg = parse_frame(sample_frame)

        assert isinstance(msg, NarwalMessage)
        assert msg.topic == sample_topic
        assert msg.payload == b"\x18\x01"
        assert msg.header == NarwalHeader(url=sample_topic)
        assert msg.header_byte == len(sample_topic.encode()) + 2
        assert msg.field_tag == 0x22
        assert msg.header_length == len(sample_topic.encode()) + 2
        assert msg.header_length_size == 1

    def test_parse_preserves_raw_and_short_topic(self, sample_frame: bytes) -> None:
        msg = parse_frame(memoryview(sample_frame))

        assert msg.raw == sample_frame
        assert msg.short_topic == "status/working_status"

    def test_parse_short_topic_and_empty_payload(self) -> None:
        msg = parse_frame(build_frame("a/b", b""))

        assert msg.topic == "a/b"
        assert msg.short_topic == "a/b"
        assert msg.payload == b""

    @pytest.mark.parametrize("header_byte", [0x00, 0x03, 0xAB, 0xFF])
    def test_parse_legacy_custom_header_byte(self, header_byte: int) -> None:
        frame = build_frame("test/topic", b"\x08\x01", header_byte=header_byte)
        msg = parse_frame(frame)

        assert msg.topic == "test/topic"
        assert msg.payload == b"\x08\x01"
        assert msg.header_byte == header_byte
        assert msg.field_tag == 0x22

    @pytest.mark.parametrize("topic_length", [126, 127, 128, 253, 254, 255])
    def test_parse_historical_one_byte_long_header(self, topic_length: int) -> None:
        topic = "x" * topic_length
        # The old builder truncated its secondary header to one byte and used a
        # one-byte topic length even when either value had the varint high bit.
        frame = (
            bytes((1, (topic_length + 2) & 0xFF, 0x22, topic_length))
            + topic.encode()
            + b"\x08"
        )
        msg = parse_frame(frame)

        assert msg.topic == topic
        assert msg.payload == b"\x08"
        assert msg.header_length_size == 1

    def test_parse_historical_direct_field_five_response(self) -> None:
        topic = "/product/device/common/get_device_info"
        frame = (
            bytes((1, len(topic) + 2, PROTOBUF_FIELD5_TAG, len(topic)))
            + topic.encode()
            + b"\x08\x01"
        )
        msg = parse_frame(frame)

        assert msg.topic == topic
        assert msg.payload == b"\x08\x01"
        assert msg.field_tag == PROTOBUF_FIELD5_TAG
        assert msg.header == NarwalHeader(
            properties=NarwalProperties(response_url=topic)
        )

    def test_parse_all_recovered_header_fields(self) -> None:
        header = NarwalHeader(
            extended_string="metadata",
            uuid="f1e2d3c4",
            source=1,
            url="/product/device/clean/start_clean",
            properties=NarwalProperties(
                response_url="/product/device/clean/start_clean/response",
                correlation_data="request-123",
            ),
            url_id=359,
        )
        frame = build_frame(header.url or "", b"\x10\x02", header=header)
        msg = parse_frame(frame)

        assert msg.header == header
        assert msg.topic == header.url
        assert msg.payload == b"\x10\x02"
        assert msg.field_tag == 0x0A

    def test_parse_properties_only_uses_response_url_as_topic(self) -> None:
        header = NarwalHeader(
            properties=NarwalProperties(
                response_url="/response/topic",
                correlation_data="2c5e",
            )
        )
        msg = parse_frame(build_frame("", b"body", header=header))

        assert msg.header == header
        assert msg.topic == "/response/topic"
        assert msg.payload == b"body"

    def test_parse_url_id_only_has_no_text_topic(self) -> None:
        header = NarwalHeader(source=3, url_id=260)
        msg = parse_frame(build_frame("", b"\x00", header=header))

        assert msg.header == header
        assert msg.topic == ""
        assert msg.payload == b"\x00"

    def test_parse_multi_byte_header_and_string_lengths(self) -> None:
        topic = "/" + ("界" * 100)
        msg = parse_frame(build_frame(topic, b"\x01"))

        assert msg.topic == topic
        assert msg.payload == b"\x01"
        assert msg.header_length > 255
        assert msg.header_length_size == 2
        assert msg.header_byte & 0x80

    def test_parse_skips_unknown_standard_wire_types(self) -> None:
        header = bytearray(_string_field(4, "/known"))
        header.extend(b"\x38\x96\x01")  # field 7, varint
        header.extend(b"\x41abcdefgh")  # field 8, fixed64
        header.extend(b"\x4a\x03xyz")  # field 9, length-delimited
        header.extend(b"\x55abcd")  # field 10, fixed32

        msg = parse_frame(_frame(bytes(header), b"payload"))

        assert msg.header == NarwalHeader(url="/known")
        assert msg.payload == b"payload"

    def test_parse_skips_unknown_properties_field(self) -> None:
        properties = _string_field(1, "/response") + b"\x18\x7f"
        header = b"\x2a" + _varint(len(properties)) + properties

        msg = parse_frame(_frame(header))

        assert msg.header.properties == NarwalProperties(response_url="/response")
        assert msg.topic == "/response"

    def test_duplicate_known_fields_use_last_value(self) -> None:
        header = _string_field(4, "/first") + _string_field(4, "/last")

        assert parse_frame(_frame(header)).topic == "/last"

    @pytest.mark.parametrize("value", [b"text", bytearray(b"text"), memoryview(b"text")])
    def test_parse_rejects_non_frame_bytes(self, value: object) -> None:
        with pytest.raises(ProtocolError, match="frame type"):
            parse_frame(value)  # type: ignore[arg-type]

    def test_parse_rejects_non_bytes_like_input(self) -> None:
        with pytest.raises(TypeError, match="bytes-like"):
            parse_frame("not bytes")  # type: ignore[arg-type]

    @pytest.mark.parametrize("frame", [b"", b"\x01"])
    def test_parse_too_short_raises(self, frame: bytes) -> None:
        with pytest.raises(ProtocolError, match="too short"):
            parse_frame(frame)

    def test_parse_wrong_frame_type_raises(self) -> None:
        with pytest.raises(ProtocolError, match="frame type"):
            parse_frame(b"\x02\x00")

    def test_parse_truncated_header_length_varint_raises(self) -> None:
        with pytest.raises(ProtocolError, match="Truncated Header length varint"):
            parse_frame(b"\x01\x80")

    def test_parse_oversized_header_length_varint_raises(self) -> None:
        with pytest.raises(ProtocolError, match="exceeds 64 bits"):
            parse_frame(b"\x01" + (b"\xff" * 9) + b"\x02")

    def test_parse_declared_header_length_beyond_frame_raises(self) -> None:
        with pytest.raises(ProtocolError, match="Header declares 5 bytes"):
            parse_frame(b"\x01\x05\x0a\x01x")

    def test_parse_empty_header_raises(self) -> None:
        with pytest.raises(ProtocolError, match="Header cannot be empty"):
            parse_frame(b"\x01\x00")

    def test_parse_wrong_legacy_protobuf_tag_raises(self) -> None:
        with pytest.raises(ProtocolError, match="protobuf field tag"):
            parse_frame(b"\x01\x00\x33\x01X")

    def test_parse_truncated_legacy_topic_raises(self) -> None:
        with pytest.raises(ProtocolError, match="truncated"):
            parse_frame(b"\x01\x00\x22\x0aX")

    @pytest.mark.parametrize(
        ("header", "error"),
        [
            (b"\x20\x00", "Header field 4 has wire type 0"),
            (b"\x22\x03x", "(?i)truncated"),
            (b"\x22\x01\xff", "Invalid UTF-8 in Header.url"),
            (b"\x00", "field number 0"),
            (b"\x3b", "Unsupported protobuf wire type 3"),
        ],
    )
    def test_parse_rejects_malformed_header(self, header: bytes, error: str) -> None:
        with pytest.raises(ProtocolError, match=error):
            parse_frame(_frame(header))

    @pytest.mark.parametrize(
        ("properties", "error"),
        [
            (b"\x08\x01", "Properties field 1 has wire type 0"),
            (b"\x0a\x02x", "Truncated Properties field 1"),
            (b"\x0a\x01\xff", "Invalid UTF-8 in Properties.responseUrl"),
            (b"\x00", "field number 0"),
        ],
    )
    def test_parse_rejects_malformed_properties(
        self,
        properties: bytes,
        error: str,
    ) -> None:
        header = b"\x2a" + _varint(len(properties)) + properties
        with pytest.raises(ProtocolError, match=error):
            parse_frame(_frame(header))

    def test_parse_rejects_uint32_overflow(self) -> None:
        header = b"\x18" + _varint(1 << 32)

        with pytest.raises(ProtocolError, match="exceeds uint32"):
            parse_frame(_frame(header))


class TestBuildFrame:
    """Tests for build_frame()."""

    def test_build_short_frame_is_byte_for_byte_compatible(self) -> None:
        frame = build_frame("abc", b"\x08\x01")

        assert frame == b"\x01\x05\x22\x03abc\x08\x01"

    def test_build_roundtrip(self, sample_topic: str, sample_payload: bytes) -> None:
        msg = parse_frame(build_frame(sample_topic, sample_payload))

        assert msg.topic == sample_topic
        assert msg.payload == sample_payload

    @pytest.mark.parametrize(
        "payload",
        [b"\x08\x01", bytearray(b"\x08\x01"), memoryview(b"\x08\x01")],
    )
    def test_build_accepts_bytes_like_payload(self, payload: object) -> None:
        assert parse_frame(build_frame("topic", payload)).payload == b"\x08\x01"  # type: ignore[arg-type]

    def test_build_topic_over_255_bytes_uses_varints(self) -> None:
        topic = "x" * 300
        frame = build_frame(topic, b"\x08")
        msg = parse_frame(frame)

        assert frame[:3] == b"\x01\xaf\x02"
        assert msg.topic == topic
        assert msg.payload == b"\x08"
        assert msg.header_length == 303
        assert msg.header_length_size == 2

    def test_build_uses_utf8_byte_length(self) -> None:
        topic = "/房间"
        frame = build_frame(topic, b"")
        msg = parse_frame(frame)

        assert frame[3] == len(topic.encode())
        assert msg.topic == topic

    def test_build_full_header_has_expected_protobuf_encoding(self) -> None:
        header = NarwalHeader(
            extended_string="e",
            uuid="u",
            source=1,
            url="/t",
            properties=NarwalProperties(response_url="/r", correlation_data="c"),
            url_id=300,
        )
        encoded_header = (
            b"\x0a\x01e"
            b"\x12\x01u"
            b"\x18\x01"
            b"\x22\x02/t"
            b"\x2a\x07\x0a\x02/r\x12\x01c"
            b"\x30\xac\x02"
        )

        assert build_frame("/t", b"P", header=header) == _frame(encoded_header, b"P")

    def test_build_fills_missing_header_url_from_topic(self) -> None:
        header = NarwalHeader(uuid="request-id", source=1)
        msg = parse_frame(build_frame("/topic", b"", header=header))

        assert msg.header == NarwalHeader(
            uuid="request-id",
            source=1,
            url="/topic",
        )

    def test_build_empty_topic_with_rich_header(self) -> None:
        header = NarwalHeader(url_id=12)

        assert parse_frame(build_frame("", b"", header=header)).header == header

    def test_build_empty_topic_without_header_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            build_frame("", b"\x08\x01")

    def test_build_mismatched_topic_and_header_url_raises(self) -> None:
        with pytest.raises(ValueError, match="does not match"):
            build_frame("/one", b"", header=NarwalHeader(url="/two"))

    @pytest.mark.parametrize(
        ("kwargs", "error_type", "error"),
        [
            ({"topic": 1, "payload": b""}, TypeError, "Topic must be a string"),
            ({"topic": "t", "payload": "x"}, TypeError, "Payload must be bytes-like"),
            (
                {"topic": "t", "payload": b"", "header": object()},
                TypeError,
                "header must be NarwalHeader",
            ),
            (
                {
                    "topic": "",
                    "payload": b"",
                    "header": NarwalHeader(extended_string=1),  # type: ignore[arg-type]
                },
                TypeError,
                "header.extended_string must be a string",
            ),
            (
                {
                    "topic": "",
                    "payload": b"",
                    "header": NarwalHeader(properties="bad"),  # type: ignore[arg-type]
                },
                TypeError,
                "header.properties must be NarwalProperties",
            ),
        ],
    )
    def test_build_rejects_invalid_argument_types(
        self,
        kwargs: dict[str, object],
        error_type: type[Exception],
        error: str,
    ) -> None:
        with pytest.raises(error_type, match=error):
            build_frame(**kwargs)  # type: ignore[arg-type]

    @pytest.mark.parametrize(
        ("header", "error_type", "error"),
        [
            (NarwalHeader(source=True), TypeError, "header.source must be an integer"),
            (NarwalHeader(source=-1), ValueError, "header.source out of range"),
            (
                NarwalHeader(source=1 << 32),
                ValueError,
                "header.source out of range",
            ),
            (NarwalHeader(url_id=False), TypeError, "header.url_id must be an integer"),
            (NarwalHeader(url_id=-1), ValueError, "header.url_id out of range"),
            (
                NarwalHeader(url_id=1 << 32),
                ValueError,
                "header.url_id out of range",
            ),
        ],
    )
    def test_build_rejects_invalid_uint32_header_fields(
        self,
        header: NarwalHeader,
        error_type: type[Exception],
        error: str,
    ) -> None:
        with pytest.raises(error_type, match=error):
            build_frame("", b"", header=header)

    @pytest.mark.parametrize(
        ("header_byte", "error_type", "error"),
        [
            (True, TypeError, "header_byte must be an integer"),
            ("1", TypeError, "header_byte must be an integer"),
            (-1, ValueError, "header_byte out of range"),
            (256, ValueError, "header_byte out of range"),
        ],
    )
    def test_build_rejects_invalid_header_byte(
        self,
        header_byte: object,
        error_type: type[Exception],
        error: str,
    ) -> None:
        with pytest.raises(error_type, match=error):
            build_frame("t", b"", header_byte=header_byte)  # type: ignore[arg-type]

    def test_build_preserves_noncanonical_legacy_header_byte(self) -> None:
        frame = build_frame("t", b"", header_byte=0xFF)

        assert frame == b"\x01\xff\x22\x01t"
        assert parse_frame(frame).header_byte == 0xFF

    def test_build_rejects_noncanonical_override_for_rich_header(self) -> None:
        header = NarwalHeader(uuid="id", url="/topic")

        with pytest.raises(ValueError, match="URL-only Header"):
            build_frame("/topic", b"", header_byte=0, header=header)

    def test_build_rejects_noncanonical_override_for_long_url(self) -> None:
        with pytest.raises(ValueError, match="shorter than 128 bytes"):
            build_frame("x" * 128, b"", header_byte=0)
