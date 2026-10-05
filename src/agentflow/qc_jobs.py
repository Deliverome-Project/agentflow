"""Bounded process-isolated QC rendering; Matplotlib is not thread-safe."""

import multiprocessing
from collections import deque
from concurrent.futures import ProcessPoolExecutor

from .plots import save_qc, save_time_qc


def render(prepared, recipe, masks, folder, index, sample_id):
    save_qc(prepared, recipe, masks, folder / f"gates-{index + 1:04d}.png", sample_id)
    save_time_qc(prepared, folder / f"time-{index + 1:04d}.png")


class QcJobs:
    """At most one queued sample per worker; failures prevent publication."""

    def __init__(self, workers):
        self.workers = workers
        self.pending = deque()
        self.pool = None

    def __enter__(self):
        if self.workers > 1:
            self.pool = ProcessPoolExecutor(
                max_workers=self.workers, mp_context=multiprocessing.get_context("spawn")
            )
        return self

    def submit(self, *args):
        if self.pool is None:
            render(*args)
        else:
            if len(self.pending) >= self.workers:
                self.pending.popleft().result()
            self.pending.append(self.pool.submit(render, *args))

    def __exit__(self, exc_type, exc, traceback):
        try:
            if exc_type is None:
                for future in self.pending:
                    future.result()
        finally:
            if self.pool is not None:
                for future in self.pending:
                    future.cancel()
                self.pool.shutdown(wait=True, cancel_futures=True)
