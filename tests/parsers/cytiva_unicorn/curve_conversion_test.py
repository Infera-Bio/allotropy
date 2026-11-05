"""Curve arrays, axes and logbook settings, on hand-built UNICORN members."""

from __future__ import annotations

import io
import struct
from typing import Any
import zipfile

import pytest

from allotropy.allotrope.models.shared.definitions.definitions import (
    FieldComponentDatatype,
)
from allotropy.allotrope.schema_mappers.data_cube import DataCubeComponent
from allotropy.exceptions import AllotropeConversionError
from allotropy.parsers.cytiva_unicorn.reader.unicorn_zip_handler import (
    UnicornZipHandler,
)
from allotropy.parsers.cytiva_unicorn.structure.data_cube.converters import (
    FloatConverter,
)
from allotropy.parsers.cytiva_unicorn.structure.data_cube.creator import (
    create_data_cube,
    UnconvertibleCurveError,
)
from allotropy.parsers.cytiva_unicorn.structure.measurement_group import (
    instruction_setting,
)
from allotropy.parsers.utils.strict_xml_element import StrictXmlElement

HEADER = b"\x00\x01\x00\x00\x00\xff\xff\xff\xff\x01\x00\x00\x00\x00\x00\x00\x00"
UV = DataCubeComponent(type_=FieldComponentDatatype.float, concept="x", unit="mAU")


def array(values: list[float], count: int | None = None, *, end: bool = True) -> bytes:
    """An ArraySinglePrimitive stream as UNICORN writes it."""
    stated = len(values) if count is None else count
    body = struct.pack(f"<{len(values)}f", *values)
    return (
        HEADER
        + b"\x0f"
        + struct.pack("<i", 1)
        + struct.pack("<i", stated)
        + b"\x0b"
        + body
        + (b"\x0b" if end else b"")
    )


def handler(members: dict[str, bytes]) -> UnicornZipHandler:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)
            z.writestr(name + "DataType", b"System.Single[]\r\n")
    buf.seek(0)
    return UnicornZipHandler(buf)


def curve(xml: str) -> StrictXmlElement:
    return StrictXmlElement.create_from_bytes(
        f"<Curve><Name>X</Name>{xml}</Curve>".encode()
    )


SPACED = "<DistanceToStartPoint>1</DistanceToStartPoint><DistanceBetweenPoints>0.5</DistanceBetweenPoints>"


def test_a_complete_array_is_read_by_its_count() -> None:
    values = [float(i) for i in range(20)]
    assert FloatConverter().convert(array(values)) == tuple(values)


def test_an_array_cut_short_keeps_every_whole_value_it_holds() -> None:
    cut = array([1.0, 2.0, 3.0], count=10, end=False) + b"\x00\x00"
    assert FloatConverter().convert(cut) == (1.0, 2.0, 3.0)


@pytest.mark.parametrize("count", [-1, 2])
def test_an_impossible_count_is_an_error(count: int) -> None:
    with pytest.raises(AllotropeConversionError):
        FloatConverter().convert(array([1.0, 2.0, 3.0], count=count))


def test_an_amplitude_only_curve_takes_its_stated_volume_axis() -> None:
    cube = create_data_cube(
        handler({"CoordinateData.Amplitudes": array([10, 20, 30])}),
        "X",
        UV,
        None,
        curve(
            f"<IsoChroneType>Volume</IsoChroneType><VolumeUnit>ml</VolumeUnit>{SPACED}"
        ),
    )
    assert cube.structure_dimensions[0].unit == "mL"
    assert cube.dimensions == [[1.0, 1.5, 2.0]]


def test_a_time_axis_is_stated_in_seconds() -> None:
    cube = create_data_cube(
        handler({"CoordinateData.Amplitudes": array([10, 20, 30])}),
        "X",
        UV,
        None,
        curve(f"<IsoChroneType>Time</IsoChroneType><TimeUnit>min</TimeUnit>{SPACED}"),
    )
    assert cube.structure_dimensions[0].concept == "retention time"
    assert cube.structure_dimensions[0].unit == "s"
    assert cube.dimensions == [[60.0, 90.0, 120.0]]


@pytest.mark.parametrize(
    "xml",
    [
        f"<TimeUnit>s</TimeUnit><VolumeUnit>ml</VolumeUnit>{SPACED}",  # no isochrone
        f"<IsoChroneType>Volume</IsoChroneType>{SPACED}",  # no unit
        f"<IsoChroneType>Volume</IsoChroneType><VolumeUnit>l</VolumeUnit>{SPACED}",
        "<IsoChroneType>Volume</IsoChroneType><VolumeUnit>ml</VolumeUnit>",  # no spacing
    ],
)
def test_amplitudes_with_no_stated_axis_are_not_converted(xml: str) -> None:
    with pytest.raises(UnconvertibleCurveError):
        create_data_cube(
            handler({"CoordinateData.Amplitudes": array([10, 20, 30])}),
            "X",
            UV,
            None,
            curve(xml),
        )


def test_an_axis_with_no_amplitudes_is_not_converted() -> None:
    members = {
        "CoordinateData.Volumes": array([0, 1, 2]),
        "CoordinateData.Amplitudes": array([], count=3, end=False),
    }
    with pytest.raises(UnconvertibleCurveError):
        create_data_cube(handler(members), "X", UV, None, curve(""))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "System flow 5.000 {ml/min} Pre column pressure (Completed)",
            ("System flow", 5.0, "ml/min"),
        ),
        ("Gradient 100.0 {%B} 5.00 {CV}", ("Gradient", 100.0, "%B")),
        ("Gradient 1e-3 {%B} 5.00 {CV}", ("Gradient", 0.001, "%B")),
        ("System flow .5 {ml/min}", ("System flow", 0.5, "ml/min")),
        (
            "Alarm 2 pressure Enabled 0.50 {MPa}",
            ("Alarm 2 pressure Enabled", 0.5, "MPa"),
        ),
        ("System flow 1,5 {ml/min}", None),
        ("Batch ID: ", None),
    ],
)
def test_a_logbook_instruction_states_its_setting(
    text: str, expected: tuple[str, float, str] | None
) -> None:
    got = instruction_setting(text, {})
    if expected is None:
        assert got == {}
    else:
        instruction, value, unit = expected
        assert got == {
            "instruction": instruction,
            "setting": {"value": value, "unit": unit},
        }


def test_a_parsed_setting_never_replaces_an_element_of_the_same_name() -> None:
    got = instruction_setting("System flow 5 {ml/min}", {"setting": "x"})
    assert got == {
        "instruction": "System flow",
        "logbook setting": {"value": 5.0, "unit": "ml/min"},
    }


MULTIPLE = "tests/parsers/cytiva_unicorn/testdata/unicorn_multiple_chromatograms.zip"


def damaged(prefixes: tuple[str, ...]) -> bytes:
    """The two-chromatogram fixture with every curve of the named chromatograms holding
    an axis but no amplitudes."""
    out = io.BytesIO()
    with zipfile.ZipFile(MULTIPLE) as src, zipfile.ZipFile(out, "w") as dst:
        for info in src.infolist():
            data = src.read(info)
            if info.filename.startswith(prefixes) and info.filename.endswith("_True"):
                inner_out = io.BytesIO()
                with (
                    zipfile.ZipFile(io.BytesIO(data)) as inner,
                    zipfile.ZipFile(inner_out, "w") as rebuilt,
                ):
                    for member in inner.infolist():
                        body = inner.read(member)
                        if member.filename == "CoordinateData.Amplitudes":
                            body = array([])
                        rebuilt.writestr(member.filename, body)
                data = inner_out.getvalue()
            dst.writestr(info.filename, data)
    return out.getvalue()


def _documents(content: bytes) -> list[dict[str, Any]]:
    from allotropy.parser_factory import Vendor
    from allotropy.to_allotrope import allotrope_from_io

    asm = allotrope_from_io(io.BytesIO(content), "export.zip", Vendor.CYTIVA_UNICORN)
    documents: list[dict[str, Any]] = asm["liquid chromatography aggregate document"][
        "liquid chromatography document"
    ]
    return documents


def _reasons(document: dict[str, Any]) -> list[str]:
    return [
        control["custom information document"]["curves not converted"]
        for measurement in document["measurement aggregate document"][
            "measurement document"
        ]
        for control in measurement["device control aggregate document"][
            "device control document"
        ]
        if "curves not converted" in control.get("custom information document", {})
    ]


def test_a_chromatogram_with_no_convertible_curve_keeps_its_events() -> None:
    before = _documents(open(MULTIPLE, "rb").read())
    after = _documents(damaged(("Chrom.1_",)))
    assert len(after) == len(before) == 2
    damaged_doc, intact = after
    [reason] = _reasons(damaged_doc)
    assert "with no amplitudes" in reason
    assert _reasons(intact) == []
    for key in ("fraction aggregate document", "log aggregate document"):
        assert damaged_doc["measurement aggregate document"].get(key) == before[0][
            "measurement aggregate document"
        ].get(key)


def test_a_result_with_no_convertible_curve_still_converts_and_says_why() -> None:
    documents = _documents(damaged(("Chrom.1_", "Column Performance Test_")))
    assert len(documents) == 2
    assert all(len(_reasons(document)) == 1 for document in documents)
