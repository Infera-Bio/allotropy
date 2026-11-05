from abc import abstractmethod
from collections.abc import Iterator
import struct

from allotropy.exceptions import AllotropeConversionError

# UNICORN stores each curve array as a .NET BinaryFormatter stream: a 17-byte
# SerializationHeaderRecord, then an ArraySinglePrimitive record (type 0x0F, object id,
# element count, primitive type 0x0B = Single), the little-endian floats, and a
# MessageEnd record (0x0B).
_ARRAY_SINGLE_PRIMITIVE = 0x0F
_PRIMITIVE_SINGLE = 0x0B
_MESSAGE_END = 0x0B
_RECORD_AT = 17
_COUNT_AT = 22
_TYPE_AT = 26
_DATA_AT = 27


class Converter:
    @abstractmethod
    def get_format(self) -> str:
        pass

    @abstractmethod
    def iter_data(self, data: bytes) -> Iterator[bytes]:
        pass

    def convert(self, data: bytes) -> tuple[float, ...]:
        binary_format = self.get_format()
        return tuple(
            struct.unpack(binary_format, binary_data)[0]
            for binary_data in self.iter_data(data)
        )


def single_array_count(data: bytes) -> int | None:
    """How many floats to read from an ArraySinglePrimitive stream: its stated count when
    the stream is complete, or the whole floats it holds when it ends early (a file cut
    short keeps the values it has). None when the bytes are not framed as one.

    Raises when the framing is recognised but impossible: a negative count, or more bytes
    than the count accounts for."""
    if len(data) < _DATA_AT:
        return None
    if (
        data[_RECORD_AT] != _ARRAY_SINGLE_PRIMITIVE
        or data[_TYPE_AT] != _PRIMITIVE_SINGLE
    ):
        return None
    count = int(struct.unpack_from("<i", data, _COUNT_AT)[0])
    complete = _DATA_AT + 4 * count + 1
    if count < 0 or len(data) > complete:
        msg = (
            f"A curve array states {count} values but holds {len(data)} bytes; "
            "the result file is damaged."
        )
        raise AllotropeConversionError(msg)
    if len(data) == complete:
        if data[-1] != _MESSAGE_END:
            msg = "A curve array does not end where its stated length says it does."
            raise AllotropeConversionError(msg)
        return count
    return (len(data) - _DATA_AT) // 4


class FloatConverter(Converter):
    def get_format(self) -> str:
        return "<f"  # little endian float (4 bytes)

    def convert(self, data: bytes) -> tuple[float, ...]:
        count = single_array_count(data)
        if count is None:
            return super().convert(data)
        return struct.unpack_from(f"<{count}f", data, _DATA_AT)

    def iter_data(self, data: bytes) -> Iterator[bytes]:
        # Fixed offsets, only for bytes not framed as an ArraySinglePrimitive record
        # (no such file is known outside hand-made test data).
        for i in range(47, len(data) - 48, 4):
            yield data[i : i + 4]
