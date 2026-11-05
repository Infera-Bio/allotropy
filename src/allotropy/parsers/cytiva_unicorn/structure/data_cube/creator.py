from __future__ import annotations

from allotropy.allotrope.models.shared.definitions.definitions import (
    FieldComponentDatatype,
)
from allotropy.allotrope.schema_mappers.data_cube import DataCube, DataCubeComponent
from allotropy.exceptions import AllotropeConversionError
from allotropy.parsers.cytiva_unicorn.reader.unicorn_zip_handler import (
    UnicornZipHandler,
)
from allotropy.parsers.cytiva_unicorn.structure.data_cube.reader import (
    DataCubeReader,
)
from allotropy.parsers.cytiva_unicorn.structure.data_cube.transformations import (
    Transformation,
)
from allotropy.parsers.utils.strict_xml_element import (
    StrictXmlElement,
)

RETENTION_VOLUME = DataCubeComponent(
    type_=FieldComponentDatatype.float,
    concept="retention volume",
    unit="mL",
)
RETENTION_TIME = DataCubeComponent(
    type_=FieldComponentDatatype.float,
    concept="retention time",
    unit="s",
)


class UnconvertibleCurveError(AllotropeConversionError):
    """A curve whose recorded arrays cannot form a data cube: amplitudes with no axis to
    place them on, or one array empty while the other holds values. The chromatogram
    lists it instead of losing the whole file."""


# The schema states retention volume in mL and retention time in s.
_VOLUME_UNITS = frozenset({"ml", "mL"})
_SECONDS_PER = {"s": 1.0, "sec": 1.0, "min": 60.0}


def _spaced_axis(
    curve: StrictXmlElement | None, count: int
) -> tuple[DataCubeComponent, list[float]] | None:
    """The axis of a curve stored as amplitudes only (an evaluation result), from the
    start and spacing its XML states, in the coordinate its isochrone names and the unit
    the XML gives for it. None when any of these is missing or not one the schema holds.
    """
    if curve is None:
        return None
    start = curve.get_sub_float_or_none("DistanceToStartPoint")
    step = curve.get_sub_float_or_none("DistanceBetweenPoints")
    if start is None or step is None:
        return None
    isochrone = curve.get_sub_text_or_none("IsoChroneType")
    if (
        isochrone == "Volume"
        and curve.get_sub_text_or_none("VolumeUnit") in _VOLUME_UNITS
    ):
        return RETENTION_VOLUME, [start + i * step for i in range(count)]
    if isochrone == "Time":
        scale = _SECONDS_PER.get(curve.get_sub_text_or_none("TimeUnit") or "")
        if scale is not None:
            return RETENTION_TIME, [(start + i * step) * scale for i in range(count)]
    return None


def create_data_cube(
    handler: UnicornZipHandler,
    label: str,
    data_cube_component: DataCubeComponent,
    transformation: Transformation | None,
    curve: StrictXmlElement | None = None,
) -> DataCube:
    amplitudes = list(
        DataCubeReader(
            handler=handler,
            name="Amplitudes",
            transformation=transformation,
        ).get_data()
    )
    axis = RETENTION_VOLUME
    volumes: list[float] = []
    if handler.get_inner_path_or_none("CoordinateData.Volumes$"):
        volumes = list(DataCubeReader(handler=handler, name="Volumes").get_data())
    if not volumes and amplitudes:
        spaced = _spaced_axis(curve, len(amplitudes))
        if spaced is None:
            msg = "amplitudes with no axis to place them on"
            raise UnconvertibleCurveError(msg)
        axis, volumes = spaced
    if volumes and not amplitudes:
        msg = f"{len(volumes)} axis values with no amplitudes"
        raise UnconvertibleCurveError(msg)
    return DataCube(
        label=label,
        structure_dimensions=[axis],
        structure_measures=[data_cube_component],
        dimensions=[volumes],
        measures=[amplitudes],
    )
