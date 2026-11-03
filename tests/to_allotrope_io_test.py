from io import BytesIO
from pathlib import Path
from typing import Any

from allotropy.constants import CHARDET_ENCODING
from allotropy.parser_factory import Vendor
from allotropy.parsers.utils.uuids import (
    content_derived_ids,
    random_uuid_str,
)
from allotropy.to_allotrope import allotrope_from_io, vendor_from_io

VI_CELL_BLU = Path("tests/parsers/beckman_vi_cell_blu/testdata")
UTF16_FILE = VI_CELL_BLU / "Beckman_Vi-Cell-BLU_example01_utf16.csv"
UTF8_FILE = VI_CELL_BLU / "Beckman_Vi-Cell-BLU_example01.csv"


def _convert(path: Path, **kwargs: Any) -> dict[str, Any]:
    return allotrope_from_io(
        BytesIO(path.read_bytes()), path.name, Vendor.BECKMAN_VI_CELL_BLU, **kwargs
    )


def test_a_file_that_is_not_utf8_converts_without_naming_its_encoding() -> None:
    assert _convert(UTF16_FILE, deterministic_ids=True) == _convert(
        UTF16_FILE, encoding=CHARDET_ENCODING, deterministic_ids=True
    )


def test_a_file_that_is_not_utf8_is_detected_without_naming_its_encoding() -> None:
    contents = BytesIO(UTF16_FILE.read_bytes())
    assert vendor_from_io(contents, UTF16_FILE.name) == Vendor.BECKMAN_VI_CELL_BLU


def test_content_derived_ids_repeat_for_the_same_file_and_differ_between_files() -> None:
    first = _convert(UTF8_FILE, deterministic_ids=True)
    assert _convert(UTF8_FILE, deterministic_ids=True) == first
    assert _convert(UTF16_FILE, deterministic_ids=True) != first
    assert _convert(UTF8_FILE) != _convert(UTF8_FILE)


def test_content_derived_ids_apply_only_inside_their_block() -> None:
    with content_derived_ids(b"\x00" * 32):
        inside = [random_uuid_str(), random_uuid_str()]
    with content_derived_ids(b"\x00" * 32):
        again = [random_uuid_str(), random_uuid_str()]
    assert inside == again
    assert inside[0] != inside[1]
    assert random_uuid_str() not in inside
