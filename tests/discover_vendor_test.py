import codecs
import io
from pathlib import Path

import pytest

from allotropy.exceptions import AllotropeVendorNotFoundError
from allotropy.named_file_contents import NamedFileContents
from allotropy.parser_factory import _VENDOR_TO_PARSER, discover_vendor, Vendor
from allotropy.parsers.vendor_parser import VendorParser
from allotropy.to_allotrope import vendor_from_file, vendor_from_io

TESTS_DIR = Path(__file__).parent / "parsers"

DIR_TO_VENDOR: dict[str, Vendor] = {
    "biorad_bioplex_manager": Vendor.BIORAD_BIOPLEX,
    "unchained_labs_lunatic_stunner": Vendor.UNCHAINED_LABS_LUNATIC,
}

INDISTINGUISHABLE: dict[Vendor, set[Vendor]] = {
    Vendor.AGILENT_GEN5: {Vendor.AGILENT_GEN5, Vendor.AGILENT_GEN5_IMAGE},
    Vendor.AGILENT_GEN5_IMAGE: {Vendor.AGILENT_GEN5, Vendor.AGILENT_GEN5_IMAGE},
    Vendor.APPBIO_QUANTSTUDIO: {
        Vendor.APPBIO_QUANTSTUDIO,
        Vendor.APPBIO_QUANTSTUDIO_DESIGNANDANALYSIS,
    },
    Vendor.APPBIO_QUANTSTUDIO_DESIGNANDANALYSIS: {
        Vendor.APPBIO_QUANTSTUDIO,
        Vendor.APPBIO_QUANTSTUDIO_DESIGNANDANALYSIS,
    },
    Vendor.LUMINEX_XPONENT: {Vendor.LUMINEX_XPONENT, Vendor.LUMINEX_INTELLIFLEX},
    Vendor.LUMINEX_INTELLIFLEX: {Vendor.LUMINEX_XPONENT, Vendor.LUMINEX_INTELLIFLEX},
    Vendor.THERMO_FISHER_VISIONLITE: {
        Vendor.THERMO_FISHER_VISIONLITE,
        Vendor.THERMO_FISHER_GENESYS_ON_BOARD,
    },
    Vendor.THERMO_FISHER_GENESYS_ON_BOARD: {
        Vendor.THERMO_FISHER_VISIONLITE,
        Vendor.THERMO_FISHER_GENESYS_ON_BOARD,
    },
    Vendor.BECKMAN_ECHO_CHERRY_PICK: {
        Vendor.BECKMAN_ECHO_CHERRY_PICK,
        Vendor.BECKMAN_ECHO_PLATE_REFORMAT,
    },
    Vendor.BECKMAN_ECHO_PLATE_REFORMAT: {
        Vendor.BECKMAN_ECHO_CHERRY_PICK,
        Vendor.BECKMAN_ECHO_PLATE_REFORMAT,
    },
    Vendor.MSD_WORKBENCH: {
        Vendor.MSD_WORKBENCH,
        Vendor.METHODICAL_MIND,
    },
    Vendor.METHODICAL_MIND: {
        Vendor.MSD_WORKBENCH,
        Vendor.METHODICAL_MIND,
    },
}

EXCLUDE_KEYWORDS = {"error", "exclude", "invalid"}

SKIP_DIRS = {"utils", "example_weyland_yutani"}


def _expected_vendor(dir_name: str) -> Vendor:
    if dir_name in DIR_TO_VENDOR:
        return DIR_TO_VENDOR[dir_name]
    return Vendor[dir_name.upper()]


def _is_valid_testcase(path: Path) -> bool:
    if not path.is_file():
        return False
    if str(path.stem).startswith("."):
        return False
    if "__pycache__" in str(path):
        return False
    if path.suffix.lower() in (".pyc", ".py", ".json", ".parquet"):
        return False
    if path.parts[-2] == "input":
        return True
    return all(keyword not in str(path).lower() for keyword in EXCLUDE_KEYWORDS)


def _get_discovery_test_cases() -> list[tuple[str, Path, Vendor]]:
    cases = []
    for vendor_dir in sorted(TESTS_DIR.iterdir()):
        if not vendor_dir.is_dir() or vendor_dir.name in SKIP_DIRS:
            continue
        testdata_dir = vendor_dir / "testdata"
        if not testdata_dir.exists():
            continue
        expected = _expected_vendor(vendor_dir.name)
        for path in sorted(testdata_dir.rglob("*")):
            if _is_valid_testcase(path):
                test_id = f"{vendor_dir.name}/{path.relative_to(testdata_dir)}"
                cases.append((test_id, path, expected))
    return cases


@pytest.mark.parametrize(
    ("test_id", "test_file", "expected_vendor"),
    _get_discovery_test_cases(),
    ids=lambda x: x if isinstance(x, str) else "",
)
def test_discover_vendor(
    test_id: str, test_file: Path, expected_vendor: Vendor
) -> None:
    result = vendor_from_file(str(test_file))
    if expected_vendor in INDISTINGUISHABLE:
        assert (
            result in INDISTINGUISHABLE[expected_vendor]
        ), f"For {test_id}: expected one of {INDISTINGUISHABLE[expected_vendor]}, got {result}"
    else:
        assert (
            result == expected_vendor
        ), f"For {test_id}: expected {expected_vendor}, got {result}"


# Plain tables no sniffer accepts. Before the try-parse excluded vendors whose own
# sniffer said no, lenient parsers claimed each one (Qiacuity dPCR, CFX Maestro).
PLAIN_TABLES = {
    "two_columns": b"a,b\n1,2\n",
    "well_plate_od": b"Well,Plate,OD 450\nA1,P1,0.5\nA2,P1,0.7\n",
    "well_metric_value": b"well,metric,value\nA1,signal,5\n",
    "sample_concentration": b"sample,conc\nS1,12.5\n",
}


@pytest.mark.parametrize("content", PLAIN_TABLES.values(), ids=PLAIN_TABLES.keys())
def test_a_plain_table_is_not_claimed_by_a_try_parse(content: bytes) -> None:
    with pytest.raises(AllotropeVendorNotFoundError):
        vendor_from_io(io.BytesIO(content), "table.csv")


def test_a_vendor_with_no_sniffer_is_still_tried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Nothing proved the file is not its export, so the try-parse still reaches it.
    no_sniffer = [
        vendor
        for vendor, parser in _VENDOR_TO_PARSER.items()
        if parser.sniff.__func__ is VendorParser.sniff.__func__  # type: ignore[attr-defined]
    ]
    assert no_sniffer, "every parser has a sniffer; this test has nothing to check"
    vendor = no_sniffer[0]
    monkeypatch.setattr(
        type(vendor.get_parser()), "create_data", lambda _self, _contents: object()
    )
    extension = vendor.supported_extensions[0]
    contents = NamedFileContents(
        io.BytesIO(b"no sniffer matches this"), f"x.{extension}"
    )
    # Every other candidate's own sniffer rejects this content, so only the vendor
    # with no sniffer is left to try, and its (patched) parse succeeds.
    assert discover_vendor(contents) == vendor


# Exports in an encoding their parser supports. A sniffer that rejected them for the
# byte-order mark alone would now keep the vendor out of discovery entirely.
REENCODED = [
    (
        "agilent_gen5/testdata/Synergy instrument datafile (Fibrillation data) - TXT format.txt",
        "utf-16",
        Vendor.AGILENT_GEN5,
    ),
    (
        "thermo_fisher_genesys30/testdata/thermo_fisher_genesys30_example_02.csv",
        "utf-8-sig",
        Vendor.THERMO_FISHER_GENESYS30,
    ),
    (
        "moldev_softmax_pro/testdata/ACSINS_absorbance_timeformat_spectrum.txt",
        "utf-8-sig",
        Vendor.MOLDEV_SOFTMAX_PRO,
    ),
]


@pytest.mark.parametrize(("relative", "codec", "expected"), REENCODED)
def test_an_export_with_a_byte_order_mark_is_still_detected(
    relative: str, codec: str, expected: Vendor
) -> None:
    path = TESTS_DIR / relative
    raw = path.read_bytes()
    # The fixtures are in their own encodings: UTF-16 with a mark, or Windows-1252.
    text = (
        raw.decode("utf-16")
        if raw.startswith(codecs.BOM_UTF16_LE)
        else raw.decode("cp1252")
    )
    result = vendor_from_io(io.BytesIO(text.encode(codec)), path.name)
    assert result in INDISTINGUISHABLE.get(expected, {expected})


def test_a_unicorn_archive_with_trailing_bytes_is_still_detected() -> None:
    # The reader repairs this (fix_zip); the sniffer must apply the same repair.
    path = TESTS_DIR / "cytiva_unicorn" / "testdata" / "unicorn_1.zip"
    content = path.read_bytes() + b"\x00" * 65536
    assert vendor_from_io(io.BytesIO(content), path.name) == Vendor.CYTIVA_UNICORN


UTF16_XML = [
    (
        "agilent_tapestation_analysis/testdata/agilent_tapestation_analysis_example_01.xml",
        Vendor.AGILENT_TAPESTATION_ANALYSIS,
    ),
    (
        "bd_biosciences_facsdiva/testdata/facsdiva_example_1.xml",
        Vendor.BD_BIOSCIENCES_FACSDIVA,
    ),
    (
        "biorad_bioplex_manager/testdata/bio-rad_bio-plex_manager_example_01.xml",
        Vendor.BIORAD_BIOPLEX,
    ),
]


@pytest.mark.parametrize(("relative", "expected"), UTF16_XML)
def test_a_utf16_xml_export_is_still_detected(relative: str, expected: Vendor) -> None:
    # An XML sniffer honours the declared encoding, so it must see the original bytes,
    # not a UTF-8 copy that still declares UTF-16.
    path = TESTS_DIR / relative
    text = path.read_bytes().decode("utf-8-sig")
    text = text.replace('encoding="utf-8"', 'encoding="UTF-16"', 1)
    text = text.replace('encoding="UTF-8"', 'encoding="UTF-16"', 1)
    text = text.replace("encoding='UTF-8'", "encoding='UTF-16'", 1)
    assert "UTF-16" in text.splitlines()[0]
    result = vendor_from_io(io.BytesIO(text.encode("utf-16")), path.name)
    assert result == expected


# Text shaped like another instrument's export. Each once passed a sniffer that keyed
# on one generic trait (a "[Section]" line, a "Plate ID" column) and then failed the
# parse with a message asking for a re-export from the wrong software.
FOREIGN_TEXT = [
    (
        Vendor.APPBIO_QUANTSTUDIO,
        b"[Header]\r\nApplication Name\tLabSolutions\r\nVersion\t5.54\r\n\r\n"
        b"[File Information]\r\nType\tData File\r\n",
    ),
    (
        Vendor.APPBIO_QUANTSTUDIO,
        b"* Block Type = 96-Well Block\r\n\r\n[Results]\r\nWell\tCT\r\n1\t20.1\r\n",
    ),
    (
        Vendor.THERMO_FISHER_NANODROP_8000,
        b"Type\tSample Name\tSizes[1] (d.nm)\tPlate ID\r\nSize\tS 1\t0.4\t\r\n",
    ),
    (
        Vendor.THERMO_FISHER_NANODROP_8000,
        b"Plate ID\tSample ID\tConc.\r\nP1\tS1\t12.5\r\n",
    ),
]


@pytest.mark.parametrize(("vendor", "content"), FOREIGN_TEXT)
def test_a_sniffer_rejects_text_missing_its_required_header(
    vendor: Vendor, content: bytes
) -> None:
    contents = NamedFileContents(io.BytesIO(content), "export.txt")
    assert not vendor.get_parser().sniff(contents)


@pytest.mark.parametrize(
    ("vendor", "directory"),
    [
        (Vendor.APPBIO_QUANTSTUDIO, "appbio_quantstudio"),
        (Vendor.THERMO_FISHER_NANODROP_8000, "thermo_fisher_nanodrop_8000"),
    ],
)
def test_a_sniffer_accepts_every_export_of_its_own(
    vendor: Vendor, directory: str
) -> None:
    exports = sorted((TESTS_DIR / directory / "testdata").glob("*.txt"))
    assert exports
    for path in exports:
        contents = NamedFileContents(io.BytesIO(path.read_bytes()), path.name)
        assert vendor.get_parser().sniff(contents), path.name
