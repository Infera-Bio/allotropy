import codecs
from contextlib import nullcontext
from datetime import tzinfo
import hashlib
from io import BytesIO, StringIO
import os
from typing import Any

from allotropy.allotrope.allotrope import serialize_and_validate_allotrope
from allotropy.constants import CHARDET_ENCODING, DEFAULT_ENCODING
from allotropy.exceptions import AllotropeConversionError
from allotropy.named_file_contents import NamedFileContents
from allotropy.parser_factory import discover_vendor, Vendor
from allotropy.parsers.utils.locale_context import set_locale_context
from allotropy.parsers.utils.uuids import content_derived_ids
from allotropy.types import IOType

VendorType = Vendor | str

_CHUNK_SIZE = 1 << 20


def _seekable(contents: IOType) -> IOType:
    """The contents, read into memory once when they cannot be read twice in place."""
    if contents.seekable():
        return contents
    data = contents.read()
    return StringIO(data) if isinstance(data, str) else BytesIO(data)


def _default_encoding(contents: IOType, encoding: str | None) -> str | None:
    """An unspecified encoding means UTF-8, unless the bytes are not UTF-8: then the
    encoding is detected, so an export written in UTF-16 or a Windows code page is
    read too."""
    if encoding is not None:
        return encoding
    decoder = codecs.getincrementaldecoder(DEFAULT_ENCODING)()
    contents.seek(0)
    try:
        while chunk := contents.read(_CHUNK_SIZE):
            if isinstance(chunk, str):
                return None
            decoder.decode(chunk)
        decoder.decode(b"", final=True)
    except UnicodeDecodeError:
        return CHARDET_ENCODING
    finally:
        contents.seek(0)
    return None


def _sha256(contents: IOType) -> bytes:
    digest = hashlib.sha256()
    contents.seek(0)
    while chunk := contents.read(_CHUNK_SIZE):
        digest.update(
            chunk.encode(DEFAULT_ENCODING) if isinstance(chunk, str) else chunk
        )
    contents.seek(0)
    return digest.digest()


def allotrope_from_io(
    contents: IOType,
    filepath: str,
    vendor_type: VendorType | None = None,
    default_timezone: tzinfo | None = None,
    encoding: str | None = None,
    locale: str | None = None,
    *,
    deterministic_ids: bool = False,
) -> dict[str, Any]:
    model = allotrope_model_from_io(
        contents,
        filepath,
        vendor_type,
        default_timezone,
        encoding,
        locale,
        deterministic_ids=deterministic_ids,
    )
    return serialize_and_validate_allotrope(model)


def allotrope_model_from_io(
    contents: IOType,
    filepath: str,
    vendor_type: VendorType | None = None,
    default_timezone: tzinfo | None = None,
    encoding: str | None = None,
    locale: str | None = None,
    *,
    deterministic_ids: bool = False,
) -> Any:
    """With deterministic_ids, every identifier in the document derives from the file's
    bytes, so one file always converts to the same document."""
    contents = _seekable(contents)
    ids = content_derived_ids(_sha256(contents)) if deterministic_ids else nullcontext()
    named_file_contents = NamedFileContents(
        contents, filepath, _default_encoding(contents, encoding)
    )

    if vendor_type is None:
        vendor = discover_vendor(named_file_contents)
        named_file_contents.contents.seek(0)
    else:
        try:
            vendor = Vendor(vendor_type)
        except ValueError as e:
            msg = f"Failed to create parser, unregistered vendor: {vendor_type}."
            raise AllotropeConversionError(msg) from e
        if named_file_contents.extension not in vendor.supported_extensions:
            msg = f"Unsupported file extension '{named_file_contents.extension}' for parser '{vendor.display_name}', expected one of '{vendor.supported_extensions}'."
            raise AllotropeConversionError(msg)

    parser = vendor.get_parser(default_timezone=default_timezone)
    with ids:
        if locale:
            with set_locale_context(locale):
                return parser.to_allotrope(named_file_contents)
        else:
            return parser.to_allotrope(named_file_contents)


def allotrope_from_file(
    filepath: str,
    vendor_type: VendorType | None = None,
    default_timezone: tzinfo | None = None,
    encoding: str | None = None,
    locale: str | None = None,
) -> dict[str, Any]:
    model = allotrope_model_from_file(
        filepath, vendor_type, default_timezone, encoding, locale
    )
    return serialize_and_validate_allotrope(model)


def allotrope_model_from_file(
    filepath: str,
    vendor_type: VendorType | None = None,
    default_timezone: tzinfo | None = None,
    encoding: str | None = None,
    locale: str | None = None,
) -> Any:
    try:
        if not os.path.isdir(filepath):
            with open(filepath, "rb") as f:
                return allotrope_model_from_io(
                    f,
                    filepath,
                    vendor_type,
                    default_timezone=default_timezone,
                    encoding=encoding,
                    locale=locale,
                )
        else:
            return allotrope_model_from_io(
                BytesIO(b"Parsing Folder"),
                filepath,
                vendor_type,
                default_timezone=default_timezone,
                encoding=encoding,
                locale=locale,
            )
    except FileNotFoundError as e:

        msg = f"File not found: {filepath}."
        raise AllotropeConversionError(msg) from e


def vendor_from_file(filepath: str, encoding: str | None = None) -> Vendor:
    with open(filepath, "rb") as f:
        return vendor_from_io(f, filepath, encoding)


def vendor_from_io(
    contents: IOType, filepath: str, encoding: str | None = None
) -> Vendor:
    contents = _seekable(contents)
    named_file_contents = NamedFileContents(
        contents, filepath, _default_encoding(contents, encoding)
    )
    return discover_vendor(named_file_contents)
