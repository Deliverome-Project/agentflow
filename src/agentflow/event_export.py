"""Lossless float64 event tables with stable identities and explicit signal spaces."""

import json

import flowio
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from .acquisition import instrument_provenance
from .provenance import software_identity


class EventWriter:
    def __init__(self, path, records, recipe):
        channels = set()
        for record in records:
            header = flowio.FlowData(record["fcs_path"], only_text=True)
            channels.update(c["pnn"] for c in header.channels.values())
        self.channels = sorted(channels)
        self.metadata = sorted({key for record in records for key in record})
        fields = [
            pa.field("sample_id", pa.string()),
            pa.field("event_index", pa.int64()),
            pa.field("input_sha256", pa.string()),
            pa.field("signal_space", pa.string()),
            pa.field("instrument_json", pa.string()),
            pa.field("compensation_json", pa.string()),
        ]
        fields += [pa.field("metadata:" + key, pa.string()) for key in self.metadata]
        fields += [
            pa.field(prefix + channel, pa.float64())
            for prefix in ["raw:", "signal:"]
            for channel in self.channels
        ]
        fields += [
            pa.field("gate:" + name, pa.bool_()) for name in ["root"] + [g["name"] for g in recipe["gates"]]
        ]
        self.schema = pa.schema(
            fields,
            metadata={
                b"agentflow_events": json.dumps(
                    {
                        "version": 1,
                        "recipe": recipe,
                        "agentflow": software_identity(),
                        "event_index": "zero-based original FCS event order",
                        "raw": "FlowKit preprocessed uncompensated units, not original FCS encoded values",
                        "signal": "compensated when a matrix is assigned; before display transformation",
                        "missing_detector": "null",
                        "instrument_json": "all recorded instrument fields and FCS keywords",
                    }
                ).encode()
            },
        )
        self.writer = pq.ParquetWriter(path, self.schema, compression="zstd")

    def write(self, prepared, masks, record, fingerprint):
        if not set(prepared.sample.pnn_labels) <= set(self.channels):
            raise ValueError("Acquired detectors changed during export")
        n = prepared.sample.event_count
        raw = prepared.sample.get_events(source="raw")
        instrument = json.dumps(instrument_provenance(prepared.sample), sort_keys=True, allow_nan=False)
        compensation = json.dumps(
            None
            if prepared.matrix is None
            else {"detectors": prepared.matrix.detectors, "values": prepared.matrix.matrix.tolist()},
            allow_nan=False,
        )
        # Bounded Arrow batches; no whole-experiment event concatenation.
        for start in range(0, n, 50000):
            stop = min(n, start + 50000)
            size = stop - start
            values = {
                "sample_id": [record["sample_id"]] * size,
                "event_index": np.arange(start, stop, dtype=np.int64),
                "input_sha256": [fingerprint] * size,
                "signal_space": ["raw" if prepared.matrix is None else "compensated"] * size,
                "instrument_json": [instrument] * size,
                "compensation_json": [compensation] * size,
            }
            values.update({"metadata:" + key: [str(record.get(key, ""))] * size for key in self.metadata})
            for channel in self.channels:
                present = channel in prepared.sample.pnn_labels
                values["raw:" + channel] = (
                    raw[start:stop, prepared.sample.pnn_labels.index(channel)] if present else [None] * size
                )
                values["signal:" + channel] = (
                    prepared.values[channel].iloc[start:stop].to_numpy() if present else [None] * size
                )
            values.update({"gate:" + name: mask[start:stop] for name, mask in masks.items()})
            self.writer.write_table(pa.Table.from_pydict(values, schema=self.schema))

    def close(self):
        self.writer.close()
