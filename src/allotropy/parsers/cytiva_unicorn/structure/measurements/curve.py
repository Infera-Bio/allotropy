from __future__ import annotations

from allotropy.allotrope.models.shared.definitions.definitions import (
    FieldComponentDatatype,
)
from allotropy.allotrope.schema_mappers.adm.liquid_chromatography.benchling._2023._09.liquid_chromatography import (
    DeviceControlDoc,
)
from allotropy.allotrope.schema_mappers.data_cube import DataCubeComponent
from allotropy.parsers.cytiva_unicorn.constants import DEVICE_TYPE
from allotropy.parsers.cytiva_unicorn.reader.unicorn_zip_handler import (
    UnicornZipHandler,
)
from allotropy.parsers.cytiva_unicorn.structure.measurements.generic import (
    UnicornMeasurement,
)
from allotropy.parsers.cytiva_unicorn.structure.static_docs import (
    StaticDocs,
)
from allotropy.parsers.utils.strict_xml_element import (
    StrictXmlElement,
)


class CurveMeasurement(UnicornMeasurement):
    """A curve none of the named measurement types reads (a valve composition, a fraction
    collector temperature, a linear flow, a curve the user added). It is kept as recorded:
    the curve's name is the measure, in the unit the result file states for it."""

    @classmethod
    def create_or_none(
        cls,
        handler: UnicornZipHandler,
        element: StrictXmlElement,
        static_docs: StaticDocs,
    ) -> UnicornMeasurement | None:
        """The curve as a measurement, or None when it recorded no points. Raises
        CurveWithoutAxisError for amplitudes with no axis."""
        name = element.find("Name").get_text_or_none()
        if not name:
            return None
        unit = element.get_sub_text_or_none("AmplitudeUnit") or "(unitless)"
        data_cube = cls.get_data_cube_or_none(
            handler,
            element,
            DataCubeComponent(
                type_=FieldComponentDatatype.float, concept=name, unit=unit
            ),
        )
        if data_cube is None:
            return None
        return cls.get_measurement(
            static_docs=static_docs,
            chromatogram_data_cube=data_cube,
            device_control_docs=[
                DeviceControlDoc(
                    device_type=DEVICE_TYPE,
                    start_time=static_docs.start_time,
                    # No processed-data document is written without a processed
                    # cube or peaks, so the curve's own description goes here.
                    device_control_custom_info={
                        **cls.get_device_control_custom_info(element),
                        **cls.get_processed_data_custom_info(element),
                    },
                )
            ],
        )
