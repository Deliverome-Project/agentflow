"""Acquisition metadata checks in the same signal units used by FlowKit."""


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
    for detector in detectors:
        index = sample.pnn_labels.index(detector)
        row = sample.channels.iloc[index]
        voltage = metadata.get(f"p{index + 1}v")
        if voltage is not None:
            try:
                voltage = float(voltage)
            except ValueError:
                voltage = str(voltage).strip() or None
        settings[detector] = {
            "gain": float(row["png"]),
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
            if value is not None and value != actual[setting]:
                raise ValueError(f"{detector}: compensation acquisition {setting} differs or is missing")
