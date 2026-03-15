from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.errors import ServiceBusyError


@dataclass(slots=True)
class BusyStatus:
    active_jobs: int
    queued_jobs: int
    max_concurrent_jobs: int
    max_queue: int

    @property
    def busy(self) -> bool:
        return self.active_jobs >= self.max_concurrent_jobs


class BusyLease:
    def __init__(self, guard: "BusyGuard") -> None:
        self._guard = guard

    async def __aenter__(self) -> "BusyLease":
        await self._guard._acquire()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._guard._release()


class BusyGuard:
    def __init__(self, max_concurrent_jobs: int, max_queue: int) -> None:
        self.max_concurrent_jobs = max(1, max_concurrent_jobs)
        self.max_queue = max(0, max_queue)
        self._active = 0
        self._waiting = 0
        self._condition = asyncio.Condition()

    def acquire(self) -> BusyLease:
        return BusyLease(self)

    def snapshot(self) -> BusyStatus:
        return BusyStatus(
            active_jobs=self._active,
            queued_jobs=self._waiting,
            max_concurrent_jobs=self.max_concurrent_jobs,
            max_queue=self.max_queue,
        )

    async def _acquire(self) -> None:
        async with self._condition:
            if self._active < self.max_concurrent_jobs:
                self._active += 1
                return

            if self._waiting >= self.max_queue:
                raise ServiceBusyError(
                    "ImageForge is busy. Reduce concurrency or retry later.",
                    details=self.snapshot().__dict__,
                )

            self._waiting += 1
            try:
                while self._active >= self.max_concurrent_jobs:
                    await self._condition.wait()
                self._active += 1
            finally:
                self._waiting -= 1

    async def _release(self) -> None:
        async with self._condition:
            if self._active > 0:
                self._active -= 1
            self._condition.notify(1)
