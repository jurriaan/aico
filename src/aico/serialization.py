# pyright: standard

from typing import Any, TypeVar

import msgspec

T = TypeVar("T")


def to_json(obj: object) -> bytes:
    """Encode an object to JSON bytes using msgspec."""
    return msgspec.json.encode(obj)


def from_json[T](type_spec: type[T], data: bytes | str) -> T:
    """Decode JSON data (bytes or str) into the specified type."""
    return msgspec.json.decode(data, type=type_spec)


def to_dict(obj: object) -> dict[str, Any]:
    """Convert an object to a plain dictionary using msgspec."""
    # msgspec.to_builtins converts dataclasses/structs/etc to base python types
    match res := msgspec.to_builtins(obj):
        case dict():
            return res
        case _:
            raise TypeError(f"Expected dict from to_builtins, got {type(res)!r}")


def convert[T](obj: object, type_spec: type[T]) -> T:
    """Convert an object to the specified type using msgspec."""
    return msgspec.convert(obj, type_spec)
