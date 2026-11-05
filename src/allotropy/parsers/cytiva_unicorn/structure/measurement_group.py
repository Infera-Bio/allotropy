import re
from typing import Any

from allotropy.allotrope.schema_mappers.adm.liquid_chromatography.benchling._2023._09.liquid_chromatography import (
    Fraction,
    Log,
    MeasurementGroup,
)
from allotropy.parsers.cytiva_unicorn.reader.unicorn_zip_handler import (
    UnicornZipHandler,
)
from allotropy.parsers.cytiva_unicorn.structure.data_cube.creator import (
    CurveWithoutAxisError,
)
from allotropy.parsers.cytiva_unicorn.structure.measurements.absorbance import (
    AbsorbanceMeasurement1,
    AbsorbanceMeasurement2,
    AbsorbanceMeasurement3,
)
from allotropy.parsers.cytiva_unicorn.structure.measurements.concentration import (
    ConcentrationMeasurement,
)
from allotropy.parsers.cytiva_unicorn.structure.measurements.conductivity import (
    ConductivityMeasurement,
)
from allotropy.parsers.cytiva_unicorn.structure.measurements.curve import (
    CurveMeasurement,
)
from allotropy.parsers.cytiva_unicorn.structure.measurements.flow import (
    FlowMeasurement,
)
from allotropy.parsers.cytiva_unicorn.structure.measurements.generic import (
    CONVERTED_CURVES,
    UnicornMeasurement,
)
from allotropy.parsers.cytiva_unicorn.structure.measurements.ph import (
    PhMeasurement,
)
from allotropy.parsers.cytiva_unicorn.structure.measurements.pressure import (
    PressureMeasurement,
)
from allotropy.parsers.cytiva_unicorn.structure.measurements.temperature import (
    TemperatureMeasurement,
)
from allotropy.parsers.cytiva_unicorn.structure.peaks import (
    get_peak_tables,
    PeakTables,
)
from allotropy.parsers.cytiva_unicorn.structure.static_docs import (
    StaticDocs,
)
from allotropy.parsers.utils.strict_xml_element import (
    StrictXmlElement,
)


def create_measurement_groups(
    handler: UnicornZipHandler, results: StrictXmlElement
) -> list[MeasurementGroup]:
    return [
        create_measurement_group(handler, results, chromatogram)
        for chromatogram in handler.get_chromatograms()
    ]


def create_measurement_group(
    handler: UnicornZipHandler,
    results: StrictXmlElement,
    chromatogram: StrictXmlElement,
) -> MeasurementGroup:
    analysis_settings = chromatogram.find_or_none("AnalysisSettings")
    event_curves = chromatogram.find_or_none("EventCurves")
    curves = chromatogram.find("Curves")
    elements = curves.findall("Curve")
    peak_tables = get_peak_tables(chromatogram)

    static_docs = StaticDocs.create(
        handler, curves.find("Curve"), results, analysis_settings
    )
    converted: set[int] = set()
    token = CONVERTED_CURVES.set(converted)
    try:
        measurements, without_axis = _measurements(
            handler, elements, static_docs, peak_tables, converted
        )
    finally:
        CONVERTED_CURVES.reset(token)
    # Some curves may not be read due not matching any supported measurement type, mark these as read.
    for element in elements:
        element.mark_read("attr:CurveDataType")

    chromatogram.mark_read(
        {
            "element:TimeUnit",
            "element:VolumeUnit",
            "element:IsReadonly",
            "attr:UNICORNVersion",
        }
    )

    return MeasurementGroup(
        measurements=[measurement for measurement in measurements if measurement],
        fractions=create_fractions(event_curves) if event_curves else None,
        logs=create_logs(event_curves) if event_curves else None,
        measurement_aggregate_custom_info={
            "RunIndex": results.get_sub_text_or_none("RunIndex"),
            "RunType": results.get_sub_text_or_none("RunType"),
            "Name": results.get_sub_text_or_none("Name"),
            "curves without an axis": "; ".join(without_axis) or None,
            **dict(sorted(chromatogram.get_unread().items())),
        },
    )


def _measurements(
    handler: UnicornZipHandler,
    elements: list[StrictXmlElement],
    static_docs: StaticDocs,
    peak_tables: PeakTables,
    converted: set[int],
) -> tuple[list[UnicornMeasurement | None], list[str]]:
    """The named measurements, then one for every other curve the run recorded, as the
    file names it; and the names of curves that hold amplitudes with no axis."""
    measurements: list[UnicornMeasurement | None] = [
        AbsorbanceMeasurement1.create_or_none(
            handler, elements, static_docs, peak_tables
        ),
        AbsorbanceMeasurement2.create_or_none(
            handler, elements, static_docs, peak_tables
        ),
        AbsorbanceMeasurement3.create_or_none(
            handler, elements, static_docs, peak_tables
        ),
        ConductivityMeasurement.create_or_none(
            handler, elements, static_docs, peak_tables
        ),
        PhMeasurement.create_or_none(handler, elements, static_docs),
        ConcentrationMeasurement.create_or_none(handler, elements, static_docs),
        PressureMeasurement.create_or_none(handler, elements, static_docs),
        FlowMeasurement.create_or_none(handler, elements, static_docs),
        TemperatureMeasurement.create_or_none(handler, elements, static_docs),
    ]
    without_axis: list[str] = []
    for element in elements:
        if id(element) in converted:
            continue
        try:
            measurements.append(
                CurveMeasurement.create_or_none(handler, element, static_docs)
            )
        except CurveWithoutAxisError:
            without_axis.append(element.find("Name").get_text_or_none() or "")
    return measurements, without_axis


def create_fractions(event_curves: StrictXmlElement) -> list[Fraction]:
    event_curve_fraction = None
    for event_curve in event_curves.findall("EventCurve"):
        if event_curve.get_attr_or_none("EventCurveType") == "Fraction":
            event_curve_fraction = event_curve
            break

    if event_curve_fraction is None:
        return []

    if events := event_curve_fraction.find_or_none("Events"):
        return [
            Fraction(
                index=f"Fraction Event {idx}",
                fraction_role=event.get_sub_text_or_none("EventText"),
                field_type=event.get_attr_or_none("EventType"),
                retention_time=(
                    None
                    if (t_min := event.get_sub_float_or_none("EventTime")) is None
                    else t_min * 60
                ),
                retention_volume=event.get_sub_float_or_none("EventVolume"),
                custom_info=event.get_unread(),
            )
            for idx, event in enumerate(events.findall("Event"), start=1)
            if event.get_attr_or_none("EventType") in ["Fraction", "Method"]
        ]

    return []


# A logbook instruction states its value with the unit in braces, the way UNICORN writes
# it: "System flow 5.000 {ml/min} Pre column pressure (Completed)". The instruction is the
# text before the first value, so it never holds an earlier value in braces.
_SETTING = re.compile(
    r"^(?P<instruction>[^{}]*?\S)\s+"
    r"(?P<value>[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)"
    r"\s*\{(?P<unit>[^{}]+)\}"
)


def instruction_setting(event_text: str, taken: dict[str, Any]) -> dict[str, Any]:
    """The instruction and the first value it sets, with its unit, as the logbook states
    them, so a setting can be compared with the curve the system recorded. Text with no
    value in braces adds nothing. The keys are prefixed with "logbook" when the event
    already carries an element of the same name, so neither is lost."""
    match = _SETTING.match(event_text)
    if match is None:
        return {}
    parsed = {
        "instruction": match.group("instruction"),
        "setting": {"value": float(match.group("value")), "unit": match.group("unit")},
    }
    return {(f"logbook {k}" if k in taken else k): v for k, v in parsed.items()}


def create_logs(event_curves: StrictXmlElement) -> list[Log]:
    event_curve_logs = None
    for event_curve in event_curves.findall("EventCurve"):
        if event_curve.get_attr_or_none("EventCurveType") == "Logbook":
            event_curve_logs = event_curve
            break

    if event_curve_logs is None:
        return []

    if events := event_curve_logs.find_or_none("Events"):
        logs, method_id = [], None

        for idx, event in enumerate(events.findall("Event"), start=1):
            if event.get_attr_or_none("EventType") not in [
                "System",
                "Method",
                "Manual",
            ]:
                event.get_unread()
                continue

            event_text = event.get_sub_text_or_none("EventText")
            if event_text is None:
                event.get_unread()
                continue

            event_subtype = event.get_attr_or_none("EventSubType")
            if event_subtype == "BlockStart":
                regex = r"Phase (.+) \(Issued\) \(Processing\) \(Completed\)"
                if res := re.match(regex, event_text):
                    method_id = res.group(1)

            logs.append(
                Log(
                    index=f"Run Log Event {idx}",
                    log_entry=event_text,
                    method_identifier=method_id,
                    retention_time=(
                        None
                        if (t_min := event.get_sub_float_or_none("EventTime")) is None
                        else t_min * 60
                    ),
                    retention_volume=event.get_sub_float_or_none("EventVolume"),
                    custom_info={
                        **(unread := event.get_unread()),
                        **instruction_setting(event_text, unread),
                    },
                )
            )

            if event_subtype == "BlockEnd" and event_text.startswith("End Phase"):
                method_id = None

    return logs
