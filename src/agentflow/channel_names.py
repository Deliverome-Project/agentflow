"""Display-only channel names; acquired detector IDs remain analytical keys."""

import os
import re
from pathlib import Path

# Display-only fallback names for instruments whose FCS files leave $PnS empty.
# Keys are case-insensitive substrings of $CYT; values map a detector's base
# name (its $PnN without -A/-H/-W) to a channel name. These are channel names,
# not evidence of which stain was used, and a nonempty $PnS always wins.
# Add others with register_instrument_aliases() or AGENTFLOW_CHANNEL_ALIASES.
INSTRUMENT_ALIASES = {
    "cytoflex": {
        "FL1": "PB450",
        "FL2": "KO525",
        "FL3": "Violet610",
        "FL4": "Violet660",
        "FL5": "FITC",
        "FL6": "PerCP",
        "FL7": "PE",
        "FL8": "ECD",
        "FL9": "PC5.5",
        "FL10": "PC7",
        "FL11": "APC",
        "FL12": "APC-A700",
        "FL13": "APC-A750",
    },
}
ALIASES_ENV = "AGENTFLOW_CHANNEL_ALIASES"
_loaded_files = set()


def register_instrument_aliases(instrument, aliases):
    """Add or replace fallback channel names for instruments whose $CYT contains ``instrument``."""
    if not isinstance(instrument, str) or not instrument.strip():
        raise ValueError("Name the instrument as it appears in $CYT, for example 'CytoFLEX'")
    if not isinstance(aliases, dict) or not aliases or not all(
        isinstance(k, str) and k.strip() and isinstance(v, str) and v.strip() for k, v in aliases.items()
    ):
        raise ValueError("Aliases must map detector base names (e.g. 'FL1') to nonempty channel names")
    INSTRUMENT_ALIASES[instrument.strip().lower()] = {k.strip(): v.strip() for k, v in aliases.items()}


def load_instrument_aliases(path):
    """Register every instrument in a JSON or YAML file of {instrument: {detector: name}}."""
    import yaml

    data = yaml.safe_load(Path(path).read_text())
    if not isinstance(data, dict) or not data:
        raise ValueError(f"{path}: expected a mapping of instrument names to detector aliases")
    for instrument, aliases in data.items():
        register_instrument_aliases(instrument, aliases)


def _configured_aliases():
    path = os.environ.get(ALIASES_ENV)
    if path and path not in _loaded_files:
        load_instrument_aliases(path)
        _loaded_files.add(path)
    return INSTRUMENT_ALIASES


def instrument_name(sample):
    metadata = {str(k).lower().lstrip("$"): v for k, v in sample.get_metadata().items()}
    return str(metadata.get("cyt") or "").strip() or "Unknown instrument"


def channel_annotation(sample, detector):
    index = sample.pnn_labels.index(detector)
    marker = str(sample.pns_labels[index] or "").strip() if sample.pns_labels else ""
    if marker and marker != detector:
        return {"detector": detector, "name": marker, "source": "FCS $PnS"}
    match = re.fullmatch(r"(.+)-([AHW])", detector)
    instrument = instrument_name(sample).lower()
    for key, aliases in _configured_aliases().items():
        alias = aliases.get(match[1]) if match and key in instrument else None
        if alias:
            return {
                "detector": detector,
                "name": f"{alias}-{match[2]}",
                "source": f"Configured '{key}' channel alias (not stain confirmation)",
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
