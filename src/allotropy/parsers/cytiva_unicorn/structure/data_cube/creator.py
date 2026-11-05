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


class CurveWithoutAxisError(AllotropeConversionError):
    """A curve that holds amplitudes but neither a volume array nor the start and spacing
    of an evenly sampled axis."""


def _spaced_axis(
    curve: StrictXmlElement | None, count: int
) -> tuple[DataCubeComponent, list[float]] | None:
    """The axis of a curve stored as amplitudes only (an evaluation result), from the
    start and spacing its XML states: in volume when its isochrone is volume, else in
    time."""
    if curve is None:
        return None
    start = curve.get_sub_float_or_none("DistanceToStartPoint")
    step = curve.get_sub_float_or_none("DistanceBetweenPoints")
    if start is None or step is None:
        return None
    if curve.get_sub_text_or_none("IsoChroneType") == "Volume":
        unit = curve.get_sub_text_or_none("VolumeUnit")
        component = (
            RETENTION_VOLUME
            if unit in (None, "ml", "mL")
            else DataCubeComponent(
                type_=FieldComponentDatatype.float,
                concept="retention volume",
                unit=unit,
            )
        )
    else:
        component = DataCubeComponent(
            type_=FieldComponentDatatype.float,
            concept="retention time",
            unit=curve.get_sub_text_or_none("TimeUnit") or "min",
        )
    return component, [start + i * step for i in range(count)]


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
            msg = (
                f"The curve {label} holds amplitudes but no axis to plot them against."
            )
            raise CurveWithoutAxisError(msg)
        axis, volumes = spaced
    return DataCube(
        label=label,
        structure_dimensions=[axis],
        structure_measures=[data_cube_component],
        dimensions=[volumes],
        measures=[amplitudes],
    )
