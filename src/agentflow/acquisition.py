"""Acquisition metadata checks in the same signal units used by FlowKit."""

import re


def upper_limits(sample):
    """Convert the recorded upper bin to FlowKit's preprocessed, uncompensated units."""
    limits = sample.channels["pnr"].to_numpy(dtype=float) - 1
    if not sample.is_preprocessed:
        return limits
    metadata = sample.get_metadata()
    if "Time" in sample.pnn_labels:
        limits[sample.pnn_labels.index("Time")] *= float(str(metadata.get("timestep", 1)).strip() or 1)
    for i, row in sample.channels.iterrows():
        decades, zero = row["pne"]
        if decades > 0:
            limits[i] = zero * 10 ** (decades * limits[i] / row["pnr"])
        if row["png"] not in (0, 1):
            limits[i] /= row["png"]
    return limits


def acquisition_settings(sample, detectors):
    metadata = {k.lower(): v for k, v in sample.get_metadata().items()}
    settings = {}
    vendor_channels = {}
    if "cytoflex" in str(metadata.get("cyt", "")).lower():
        for key, value in metadata.items():
            match = re.fullmatch(r"ch(\d+)id", key)
            if match:
                vendor_channels.setdefault(str(value), []).append("ch" + match[1])
    for detector in detectors:
        index = sample.pnn_labels.index(detector)
        row = sample.channels.iloc[index]
        voltage = metadata.get(f"p{index + 1}v")
        if voltage is not None:
            try:
                voltage = float(voltage)
            except ValueError:
                voltage = str(voltage).strip() or None
        gain_key = f"p{index + 1}g"
        gain = metadata.get(gain_key)
        gain = float(gain) if gain is not None and str(gain).strip() else None
        # Channel IDs, not numeric ordering, connect vendor channels to FCS parameters.
        base = re.sub(r"-(A|H|W)$", "", detector)
        vendor = vendor_channels.get(base, [])
        vendor_key = vendor[0] + "gain" if len(vendor) == 1 else None
        vendor_gain = metadata.get(vendor_key) if vendor_key else None
        settings[detector] = {
            "gain": gain,
            "gain_source": f"$P{index + 1}G" if gain is not None else None,
            "preprocessing_gain": float(row["png"]),
            "detector_gain": float(vendor_gain) if vendor_gain is not None else None,
            "detector_gain_source": vendor_key if vendor_gain is not None else None,
            "range": float(row["pnr"]),
            "amplification": list(row["pne"]),
            "voltage": voltage,
        }
    return {"instrument": metadata.get("cyt"), "detectors": settings}


def check_acquisition(reference, current):
    """Reject contradictory reported settings; absent reference metadata stays unknown."""
    if reference.get("instrument") and reference["instrument"] != current.get("instrument"):
        raise ValueError("Compensation acquisition instrument differs or is missing")
    for detector, expected in reference["detectors"].items():
        actual = current["detectors"][detector]
        for setting, value in expected.items():
            if setting.endswith("_source"):
                continue
            if value is not None and value != actual.get(setting):
                raise ValueError(f"{detector}: compensation acquisition {setting} differs or is missing")


def instrument_provenance(sample):
    """Reported FCS acquisition fields; missing information is explicitly unknown."""
    metadata = {k.lower(): v for k, v in sample.get_metadata().items()}
    settings = acquisition_settings(sample, sample.pnn_labels)
    return {
        "source": "FCS metadata (instrument-reported; not independently verified)",
        "instrument": settings["instrument"],
        "serial_number": metadata.get("cytsn"),
        "acquisition_date": metadata.get("date"),
        "start_time": metadata.get("btim"),
        "end_time": metadata.get("etim"),
        "acquisition_system": metadata.get("sys"),
        "acquisition_software": metadata.get("creator"),
        "software_hint": "CytExpert (vendor keyword; version unknown)"
        if str(metadata.get("cytexpertfil", "")).lower() == "true"
        else None,
        "gain_definitions": {
            "gain": "Reported FCS $PnG; null if absent. Not interchangeable with vendor detector gain.",
            "preprocessing_gain": "Gain factor used by FlowKit, including its default when not reported.",
            "detector_gain": "Vendor gain matched by explicit CHnID; not applied again to event values.",
        },
        "recorded_filename": metadata.get("fil"),
        "event_count": sample.event_count,
        "detectors": settings["detectors"],
        "fcs_keywords": metadata,
    }
