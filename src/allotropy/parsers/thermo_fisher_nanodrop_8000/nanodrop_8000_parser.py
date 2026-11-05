import csv

from allotropy.allotrope.models.adm.spectrophotometry.benchling._2023._12.spectrophotometry import (
    Model,
)
from allotropy.allotrope.schema_mappers.adm.spectrophotometry.benchling._2023._12.spectrophotometry import (
    Data,
    Mapper,
)
from allotropy.named_file_contents import NamedFileContents
from allotropy.parsers.release_state import ReleaseState
from allotropy.parsers.thermo_fisher_nanodrop_8000.nanodrop_8000_reader import (
    Nanodrop8000Reader,
)
from allotropy.parsers.thermo_fisher_nanodrop_8000.nanodrop_8000_structure import (
    create_measurement_group,
    create_metadata,
    SpectroscopyRow,
)
from allotropy.parsers.utils.pandas import map_rows
from allotropy.parsers.vendor_parser import VendorParser


class Nanodrop8000Parser(VendorParser[Data, Model]):
    DISPLAY_NAME = "Thermo Fisher Scientific NanoDrop 8000"
    RELEASE_STATE = ReleaseState.RECOMMENDED
    SUPPORTED_EXTENSIONS = Nanodrop8000Reader.SUPPORTED_EXTENSIONS
    SUPPORTED_DETECTION_MODES = "Absorbance"
    SCHEMA_MAPPER = Mapper
    _REQUIRED_COLUMNS = frozenset({"plate id", "well", "date"})

    @classmethod
    def sniff(cls, named_file_contents: NamedFileContents) -> bool:
        try:
            raw = named_file_contents.contents.read()
            text = (
                raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else raw
            )
            # Every row reads "well" and "date" unconditionally, and the export
            # always names its plate, so the header must carry all three. Fields
            # are split with the quoting the reader's tab-separated parse honours.
            for row in csv.reader(text.splitlines()[:5], delimiter="\t"):
                if cls._REQUIRED_COLUMNS <= {f.strip().lower() for f in row}:
                    return True
            return False
        except Exception:
            return False

    def create_data(self, named_file_contents: NamedFileContents) -> Data:
        reader = Nanodrop8000Reader(named_file_contents)
        rows = map_rows(reader.data, SpectroscopyRow.create)

        return Data(
            create_metadata(named_file_contents.original_file_path),
            measurement_groups=[create_measurement_group(row) for row in rows],
            # NOTE: in current implementation, calculated data is reported at global level for some reason.
            # TODO(nstender): should we move this inside of measurements?
            calculated_data=[item for row in rows for item in row.calculated_data],
        )
