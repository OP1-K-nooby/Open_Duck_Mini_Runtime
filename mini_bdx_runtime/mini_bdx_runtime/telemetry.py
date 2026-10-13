"""Append-only telemetry recordings: fixed-size records plus a JSON sidecar.

A recording is two files sharing a base path:
- <base>.json: the record layout (numpy dtype) and free-form metadata;
- <base>.bin: the records, back to back, appended as they come.

Records are handed to a background thread that writes and fsyncs them every
FLUSH_PERIOD_S, so a control loop never waits on the SD card, and a power cut
(how a duck usually dies) loses at most that much. load() reads every
complete record back as a numpy structured array.
"""

import json
import os
import threading
import time
from queue import Empty, Queue
from typing import Any

import numpy as np

FLUSH_PERIOD_S = 1.0


class TelemetryWriter:
    def __init__(
        self,
        base_path: str,
        fields: list[tuple[str, str, tuple[int, ...]]],
        meta: dict[str, Any],
    ) -> None:
        """fields: (name, numpy scalar type, shape) per record field."""
        self.base_path = base_path
        self.dtype = np.dtype([(name, kind, shape) for name, kind, shape in fields])
        directory = os.path.dirname(base_path) or "."
        os.makedirs(directory, exist_ok=True)
        with open(base_path + ".json", "w") as f:
            json.dump(
                {"dtype": self.dtype.descr, "created": time.time(), "meta": meta},
                f,
                indent=1,
                default=_json_default,
            )
            # Without this, a power cut (ext4's delayed allocation) left the
            # header an empty file and the recording unreadable.
            f.flush()
            os.fsync(f.fileno())
        self.file = open(base_path + ".bin", "ab")
        # Make both new directory entries durable too.
        dir_fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
        self.queue: Queue = Queue()
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self._writer, daemon=True)
        self.thread.start()

    def write(self, **values: Any) -> None:
        record = np.zeros((), dtype=self.dtype)
        for name, value in values.items():
            record[name] = value
        self.queue.put(record.tobytes())

    def close(self) -> None:
        self.stopping.set()
        self.thread.join()
        self.file.close()

    def _writer(self) -> None:
        last_sync = time.monotonic()
        while True:
            try:
                self.file.write(self.queue.get(timeout=FLUSH_PERIOD_S))
            except Empty:
                pass
            stopping = self.stopping.is_set() and self.queue.empty()
            if stopping or time.monotonic() - last_sync >= FLUSH_PERIOD_S:
                self.file.flush()
                os.fsync(self.file.fileno())
                last_sync = time.monotonic()
            if stopping:
                return


def load(base_path: str) -> tuple[np.ndarray, dict[str, Any]]:
    """Read a recording back: (records, header with 'meta')."""
    if base_path.endswith((".bin", ".json")):
        base_path = base_path.rsplit(".", 1)[0]
    with open(base_path + ".json") as f:
        header = json.load(f)
    dtype = np.dtype([tuple(field) for field in header["dtype"]])
    raw = np.fromfile(base_path + ".bin", dtype=np.uint8)
    # A power cut can leave a partial last record.
    complete = len(raw) // dtype.itemsize * dtype.itemsize
    return raw[:complete].view(dtype), header


def _json_default(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"not JSON serializable: {type(value)}")


if __name__ == "__main__":
    import sys

    for path in sys.argv[1:]:
        records, header = load(path)
        print(f"{path}: {len(records)} records, fields {list(records.dtype.names or ())}")
        if len(records) > 1 and "t" in (records.dtype.names or ()):
            span = records["t"][-1] - records["t"][0]
            print(f"  {span:.1f} s, {len(records) / max(span, 1e-9):.1f} records/s")
        if "marker" in (records.dtype.names or ()):
            print(f"  markers at records {np.flatnonzero(records['marker']).tolist()}")
