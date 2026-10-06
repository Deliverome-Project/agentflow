"""Display-only channel names; acquired detector IDs remain analytical keys."""

import re

# User-supplied laboratory CytoFLEX configuration. These are channel aliases,
# not evidence of which stain, reporter or biological marker was used.
CYTOFLEX_ALIASES = {
    1: "PB450",
    2: "KO525",
    3: "Violet610",
    4: "Violet660",
    5: "FITC",
    6: "PerCP",
    7: "PE",
    8: "ECD",
    9: "PC5.5",
    10: "PC7",
    11: "APC",
    12: "APC-A700",
    13: "APC-A750",
}


def instrument_name(sample):
    metadata = {str(k).lower().lstrip("$"): v for k, v in sample.get_metadata().items()}
    return str(metadata.get("cyt") or "").strip() or "Unknown instrument"


def channel_annotation(sample, detector):
    index = sample.pnn_labels.index(detector)
    marker = str(sample.pns_labels[index] or "").strip() if sample.pns_labels else ""
    if marker and marker != detector:
        return {"detector": detector, "name": marker, "source": "FCS $PnS"}
    match = re.fullmatch(r"FL(\d+)-([AH])", detector)
    if "cytoflex" in instrument_name(sample).lower() and match:
        alias = CYTOFLEX_ALIASES.get(int(match[1]))
        if alias:
            return {
                "detector": detector,
                "name": f"{alias}-{match[2]}",
                "source": "User-supplied CytoFLEX channel alias (not stain confirmation)",
            }
    return {"detector": detector, "name": detector, "source": "FCS $PnN; stain unknown"}


def channel_label(sample, detector):
    name = channel_annotation(sample, detector)["name"]
    return detector if name == detector else f"{name} · {detector}"


def add_detector_choices(combo, sample, channels):
    """Qt-compatible adapter with no GUI import; item data always holds raw IDs."""
    for channel in channels:
        combo.addItem(channel_label(sample, channel), channel)


def select_detector(combo, detector):
    index = combo.findData(detector)
    if index >= 0:
        combo.setCurrentIndex(index)
