"""Frame parsing and building for the Narwal WebSocket protocol.

Current envelope:
    0x01
    protobuf-varint length of the serialized Header
    serialized Header protobuf
    command-specific protobuf body

For the common URL-only Header and a short topic, this is byte-for-byte
compatible with the historical four-byte prefix:
    0x01, header_length, 0x22, topic_length, topic, body
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from .const import FRAME_TYPE_BYTE, PROTOBUF_FIELD_TAG

# Header field 5, wire type 2. Older robots/clients also used this byte as a
# response-topic field directly, before field 5 became the nested Properties message.
PROTOBUF_FIELD5_TAG = 0x2A

_WIRE_VARINT = 0
_WIRE_FIXED64 = 1
_WIRE_LENGTH_DELIMITED = 2
_WIRE_FIXED32 = 5
_MAX_UINT32 = (1 << 32) - 1
_MAX_UINT64 = (1 << 64) - 1


class ProtocolError(Exception):
    """Raised when a frame cannot be parsed."""


@dataclass(frozen=True, slots=True)
class NarwalProperties:
    """Header field 5: response routing and request correlation properties."""

    response_url: str | None = None
    correlation_data: str | None = None


@dataclass(frozen=True, slots=True)
class NarwalHeader:
    """The protobuf Header carried by a Narwal WebSocket envelope."""

    extended_string: str | None = None
    uuid: str | None = None
    source: int | None = None
    url: str | None = None
    properties: NarwalProperties | None = None
    url_id: int | None = None

    @property
    def response_url(self) -> str | None:
        """Return the nested response URL, when present."""
        return self.properties.response_url if self.properties is not None else None

    @property
    def correlation_data(self) -> str | None:
        """Return the nested correlation data, when present."""
        return self.properties.correlation_data if self.properties is not None else None


@dataclass(frozen=True)
class NarwalMessage:
    """A parsed Narwal WebSocket message.

    ``header_byte`` and ``field_tag`` retain their legacy meanings: the first
    encoded Header-length byte and first serialized Header tag byte. They remain
    identical to bytes 1 and 2 for historical short URL-only frames.
    """

    topic: str
    payload: bytes
    header_byte: int
    field_tag: int
    raw: bytes
    header: NarwalHeader = field(default_factory=NarwalHeader)
    header_length: int = 0
    header_length_size: int = 1

    @property
    def short_topic(self) -> str:
        """Return the topic without the product-key and device-ID prefix.

        '/{product_key}/{device_id}/status/working_status' -> 'status/working_status'
        """
        parts = self.topic.split("/")
        if len(parts) >= 4:
            return "/".join(parts[3:])
        return self.topic


def _encode_varint(
    value: int,
    *,
    context: str,
    maximum: int = _MAX_UINT64,
) -> bytes:
    """Encode a non-negative protobuf varint."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{context} must be an integer")
    if value < 0 or value > maximum:
        raise ValueError(f"{context} out of range: {value} (expected 0..{maximum})")

    encoded = bytearray()
    while value >= 0x80:
        encoded.append((value & 0x7F) | 0x80)
        value >>= 7
    encoded.append(value)
    return bytes(encoded)


def _decode_varint(data: bytes, offset: int, *, context: str) -> tuple[int, int]:
    """Decode one bounded protobuf uint64 varint."""
    value = 0
    for index in range(10):
        if offset >= len(data):
            raise ProtocolError(f"Truncated {context} varint at offset {offset}")
        byte = data[offset]
        offset += 1
        if index == 9 and byte > 1:
            raise ProtocolError(f"{context} varint exceeds 64 bits")
        value |= (byte & 0x7F) << (index * 7)
        if not byte & 0x80:
            return value, offset
    raise ProtocolError(f"{context} varint exceeds 10 bytes")


def _encode_string_field(field_number: int, value: str, *, context: str) -> bytes:
    """Encode one protobuf string field."""
    if not isinstance(value, str):
        raise TypeError(f"{context} must be a string")
    value_bytes = value.encode("utf-8")
    tag = _encode_varint(
        (field_number << 3) | _WIRE_LENGTH_DELIMITED,
        context=f"{context} tag",
    )
    return tag + _encode_varint(len(value_bytes), context=f"{context} length") + value_bytes


def _encode_properties(properties: NarwalProperties) -> bytes:
    """Serialize Header.Properties."""
    if not isinstance(properties, NarwalProperties):
        raise TypeError("header.properties must be NarwalProperties or None")

    encoded = bytearray()
    if properties.response_url is not None:
        encoded.extend(
            _encode_string_field(
                1,
                properties.response_url,
                context="header.properties.response_url",
            )
        )
    if properties.correlation_data is not None:
        encoded.extend(
            _encode_string_field(
                2,
                properties.correlation_data,
                context="header.properties.correlation_data",
            )
        )
    return bytes(encoded)


def _encode_header(header: NarwalHeader) -> bytes:
    """Serialize the recovered Header schema in field-number order."""
    if not isinstance(header, NarwalHeader):
        raise TypeError("header must be NarwalHeader or None")

    encoded = bytearray()
    if header.extended_string is not None:
        encoded.extend(
            _encode_string_field(
                1,
                header.extended_string,
                context="header.extended_string",
            )
        )
    if header.uuid is not None:
        encoded.extend(_encode_string_field(2, header.uuid, context="header.uuid"))
    if header.source is not None:
        encoded.extend(_encode_varint(3 << 3, context="header.source tag"))
        encoded.extend(
            _encode_varint(
                header.source,
                context="header.source",
                maximum=_MAX_UINT32,
            )
        )
    if header.url is not None:
        encoded.extend(_encode_string_field(4, header.url, context="header.url"))
    if header.properties is not None:
        properties = _encode_properties(header.properties)
        encoded.extend(_encode_varint(5 << 3 | 2, context="header.properties tag"))
        encoded.extend(
            _encode_varint(
                len(properties),
                context="header.properties length",
            )
        )
        encoded.extend(properties)
    if header.url_id is not None:
        encoded.extend(_encode_varint(6 << 3, context="header.url_id tag"))
        encoded.extend(
            _encode_varint(
                header.url_id,
                context="header.url_id",
                maximum=_MAX_UINT32,
            )
        )
    return bytes(encoded)


def _read_length_delimited(
    data: bytes,
    offset: int,
    *,
    context: str,
) -> tuple[bytes, int]:
    """Read one protobuf length-delimited value with exact bounds checking."""
    length, value_start = _decode_varint(data, offset, context=f"{context} length")
    available = len(data) - value_start
    if length > available:
        raise ProtocolError(
            f"Truncated {context}: declared {length} bytes, only {available} available"
        )
    value_end = value_start + length
    return data[value_start:value_end], value_end


def _decode_utf8(value: bytes, *, context: str) -> str:
    """Decode a protobuf string with a protocol-specific error."""
    try:
        return value.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProtocolError(f"Invalid UTF-8 in {context}: {exc}") from exc


def _skip_unknown_field(
    data: bytes,
    offset: int,
    wire_type: int,
    *,
    context: str,
) -> int:
    """Skip an unknown protobuf field while preserving strict bounds."""
    if wire_type == _WIRE_VARINT:
        _, offset = _decode_varint(data, offset, context=context)
        return offset
    if wire_type == _WIRE_FIXED64:
        if len(data) - offset < 8:
            raise ProtocolError(f"Truncated {context}: expected 8 fixed64 bytes")
        return offset + 8
    if wire_type == _WIRE_LENGTH_DELIMITED:
        _, offset = _read_length_delimited(data, offset, context=context)
        return offset
    if wire_type == _WIRE_FIXED32:
        if len(data) - offset < 4:
            raise ProtocolError(f"Truncated {context}: expected 4 fixed32 bytes")
        return offset + 4
    raise ProtocolError(f"Unsupported protobuf wire type {wire_type} in {context}")


def _decode_properties(data: bytes) -> NarwalProperties:
    """Parse Header.Properties while safely skipping future fields."""
    response_url: str | None = None
    correlation_data: str | None = None
    offset = 0

    while offset < len(data):
        key, offset = _decode_varint(data, offset, context="Properties field key")
        field_number = key >> 3
        wire_type = key & 0x07
        if field_number == 0:
            raise ProtocolError("Invalid protobuf field number 0 in Properties")

        if field_number in (1, 2):
            if wire_type != _WIRE_LENGTH_DELIMITED:
                raise ProtocolError(
                    f"Properties field {field_number} has wire type {wire_type}; "
                    "expected length-delimited"
                )
            raw_value, offset = _read_length_delimited(
                data,
                offset,
                context=f"Properties field {field_number}",
            )
            decoded = _decode_utf8(
                raw_value,
                context=(
                    "Properties.responseUrl"
                    if field_number == 1
                    else "Properties.correlationData"
                ),
            )
            if field_number == 1:
                response_url = decoded
            else:
                correlation_data = decoded
            continue

        offset = _skip_unknown_field(
            data,
            offset,
            wire_type,
            context=f"Properties field {field_number}",
        )

    return NarwalProperties(
        response_url=response_url,
        correlation_data=correlation_data,
    )


def _decode_header(data: bytes) -> NarwalHeader:
    """Parse the recovered Header protobuf while skipping future fields."""
    extended_string: str | None = None
    uuid: str | None = None
    source: int | None = None
    url: str | None = None
    properties: NarwalProperties | None = None
    url_id: int | None = None
    offset = 0

    while offset < len(data):
        key, offset = _decode_varint(data, offset, context="Header field key")
        field_number = key >> 3
        wire_type = key & 0x07
        if field_number == 0:
            raise ProtocolError("Invalid protobuf field number 0 in Header")

        if field_number in (1, 2, 4, 5):
            if wire_type != _WIRE_LENGTH_DELIMITED:
                raise ProtocolError(
                    f"Header field {field_number} has wire type {wire_type}; "
                    "expected length-delimited"
                )
            raw_value, offset = _read_length_delimited(
                data,
                offset,
                context=f"Header field {field_number}",
            )
            if field_number == 1:
                extended_string = _decode_utf8(
                    raw_value,
                    context="Header.extendedString",
                )
            elif field_number == 2:
                uuid = _decode_utf8(raw_value, context="Header.uuid")
            elif field_number == 4:
                url = _decode_utf8(raw_value, context="Header.url")
            else:
                properties = _decode_properties(raw_value)
            continue

        if field_number in (3, 6):
            if wire_type != _WIRE_VARINT:
                raise ProtocolError(
                    f"Header field {field_number} has wire type {wire_type}; expected varint"
                )
            value, offset = _decode_varint(
                data,
                offset,
                context=f"Header field {field_number}",
            )
            if value > _MAX_UINT32:
                raise ProtocolError(
                    f"Header field {field_number} exceeds uint32: {value}"
                )
            if field_number == 3:
                source = value
            else:
                url_id = value
            continue

        offset = _skip_unknown_field(
            data,
            offset,
            wire_type,
            context=f"Header field {field_number}",
        )

    return NarwalHeader(
        extended_string=extended_string,
        uuid=uuid,
        source=source,
        url=url,
        properties=properties,
        url_id=url_id,
    )


def _topic_from_header(header: NarwalHeader) -> str:
    """Choose the textual routing topic exposed through the legacy API."""
    if header.url is not None:
        return header.url
    if header.response_url is not None:
        return header.response_url
    return ""


def _legacy_override_candidate(data: bytes) -> bool:
    """Return whether a failed full parse may be an old four-byte-prefix frame."""
    if len(data) < 3 or data[2] not in (PROTOBUF_FIELD_TAG, PROTOBUF_FIELD5_TAG):
        return False
    if len(data) < 4:
        return True
    if data[2] == PROTOBUF_FIELD5_TAG:
        # A real Properties value starts with nested protobuf bytes. Historical
        # direct response-topic frames carry an MQTT-style absolute topic.
        return len(data) >= 5 and data[3] > 0 and data[4] == ord("/")
    # Historical frames always treated byte 1 as a standalone byte, even when
    # its continuation bit was set. That happened for URL lengths 126..253 and
    # for arbitrary caller-supplied header-byte overrides.
    if data[1] & 0x80 or data[3] & 0x80:
        return True
    topic_length = data[3]
    expected_header_length = (topic_length + 2) & 0xFF
    return data[1] != expected_header_length


def _parse_legacy_short_frame(data: bytes) -> NarwalMessage:
    """Parse the historical one-byte-length URL/response-URL frame."""
    if len(data) < 4:
        raise ProtocolError(f"Legacy frame too short: {len(data)} bytes (minimum 4)")

    field_tag = data[2]
    if field_tag not in (PROTOBUF_FIELD_TAG, PROTOBUF_FIELD5_TAG):
        raise ProtocolError(
            f"Invalid legacy protobuf field tag: 0x{field_tag:02x} "
            "(expected 0x22 or 0x2a)"
        )

    topic_length = data[3]
    topic_end = 4 + topic_length
    if topic_end > len(data):
        raise ProtocolError(
            f"Legacy frame truncated: expected {topic_end} bytes for topic, got {len(data)}"
        )

    topic = _decode_utf8(data[4:topic_end], context="legacy topic")
    if field_tag == PROTOBUF_FIELD_TAG:
        header = NarwalHeader(url=topic)
    else:
        header = NarwalHeader(properties=NarwalProperties(response_url=topic))

    return NarwalMessage(
        topic=topic,
        payload=data[topic_end:],
        header_byte=data[1],
        field_tag=field_tag,
        raw=data,
        header=header,
        header_length=data[1],
        header_length_size=1,
    )


def parse_frame(data: bytes | bytearray | memoryview) -> NarwalMessage:
    """Parse a raw WebSocket binary frame into a :class:`NarwalMessage`.

    Unknown protobuf Header/Properties fields with standard wire types are
    skipped. Malformed lengths, varints, strings, field types, and bounds raise
    :class:`ProtocolError`. Historical URL-only and field-5 response frames are
    accepted when their legacy layout is unambiguous.
    """
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("Frame data must be bytes-like")
    raw = bytes(data)
    if len(raw) < 2:
        raise ProtocolError(f"Frame too short: {len(raw)} bytes (minimum 2)")
    if raw[0] != FRAME_TYPE_BYTE:
        raise ProtocolError(
            f"Invalid frame type byte: 0x{raw[0]:02x} "
            f"(expected 0x{FRAME_TYPE_BYTE:02x})"
        )

    try:
        header_length, header_start = _decode_varint(
            raw,
            1,
            context="Header length",
        )
    except ProtocolError:
        if _legacy_override_candidate(raw):
            return _parse_legacy_short_frame(raw)
        raise

    header_end = header_start + header_length
    if header_length > len(raw) - header_start:
        if _legacy_override_candidate(raw):
            return _parse_legacy_short_frame(raw)
        raise ProtocolError(
            f"Frame truncated: Header declares {header_length} bytes, "
            f"only {len(raw) - header_start} available"
        )

    if header_length == 0:
        if len(raw) >= 3:
            return _parse_legacy_short_frame(raw)
        raise ProtocolError("Header cannot be empty")

    header_bytes = raw[header_start:header_end]
    try:
        header = _decode_header(header_bytes)
    except ProtocolError:
        if _legacy_override_candidate(raw):
            return _parse_legacy_short_frame(raw)
        raise

    return NarwalMessage(
        topic=_topic_from_header(header),
        payload=raw[header_end:],
        header_byte=raw[1],
        field_tag=header_bytes[0],
        raw=raw,
        header=header,
        header_length=header_length,
        header_length_size=header_start - 1,
    )


def _is_url_only_header(header: NarwalHeader) -> bool:
    """Return whether Header uses only field 4 and can use the legacy override."""
    return (
        header.extended_string is None
        and header.uuid is None
        and header.source is None
        and header.url is not None
        and header.properties is None
        and header.url_id is None
    )


def build_frame(
    topic: str,
    payload: bytes | bytearray | memoryview,
    header_byte: int | None = None,
    *,
    header: NarwalHeader | None = None,
) -> bytes:
    """Build a complete Narwal WebSocket envelope.

    Args:
        topic: Legacy textual route. With ``header=None`` it becomes Header.url.
            With a rich Header it fills a missing Header.url or must match it.
            It may be empty when the supplied Header routes through responseUrl
            or urlId.
        payload: Command-specific protobuf body.
        header_byte: Legacy one-byte Header-length override. Normal callers
            should leave this as ``None``. A non-canonical override is supported
            only for short URL-only headers so historical callers remain usable.
        header: Optional rich Header. Every recovered Header and Properties
            field is serialized when present.

    Raises:
        TypeError: If arguments have the wrong types.
        ValueError: If a value is empty, inconsistent, out of range, or cannot
            be represented by the legacy override.
    """
    if not isinstance(topic, str):
        raise TypeError("Topic must be a string")
    if not isinstance(payload, (bytes, bytearray, memoryview)):
        raise TypeError("Payload must be bytes-like")

    if header is None:
        if not topic:
            raise ValueError("Topic cannot be empty without a rich Header")
        effective_header = NarwalHeader(url=topic)
    else:
        if not isinstance(header, NarwalHeader):
            raise TypeError("header must be NarwalHeader or None")
        if topic:
            if header.url is None:
                effective_header = replace(header, url=topic)
            elif header.url != topic:
                raise ValueError(
                    f"Topic {topic!r} does not match header.url {header.url!r}"
                )
            else:
                effective_header = header
        else:
            effective_header = header

    serialized_header = _encode_header(effective_header)
    if not serialized_header:
        raise ValueError("Header cannot be empty")

    encoded_header_length = _encode_varint(
        len(serialized_header),
        context="Header length",
    )

    if header_byte is None:
        length_prefix = encoded_header_length
    else:
        if isinstance(header_byte, bool) or not isinstance(header_byte, int):
            raise TypeError("header_byte must be an integer or None")
        if not 0 <= header_byte <= 0xFF:
            raise ValueError("header_byte out of range: expected 0..255")

        if len(encoded_header_length) == 1 and header_byte == encoded_header_length[0]:
            length_prefix = bytes((header_byte,))
        elif _is_url_only_header(effective_header):
            legacy_url = effective_header.url
            assert legacy_url is not None
            topic_bytes = legacy_url.encode("utf-8")
            if len(topic_bytes) >= 0x80:
                raise ValueError(
                    "Non-canonical header_byte is supported only for URL topics "
                    "shorter than 128 bytes"
                )
            length_prefix = bytes((header_byte,))
        else:
            raise ValueError(
                "Non-canonical header_byte is supported only for a URL-only Header"
            )

    return (
        bytes((FRAME_TYPE_BYTE,))
        + length_prefix
        + serialized_header
        + bytes(payload)
    )
