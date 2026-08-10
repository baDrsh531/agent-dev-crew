"""In-process fan-out of events to live SSE subscribers.

Persistence and delivery are separate concerns: the database is the record, the
broker is the notification. A subscriber that disappears mid-run cannot block
the orchestrator — a full queue drops the oldest event rather than applying
back-pressure, and the client recovers the gap by replaying from `after_seq`.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

QUEUE_MAX = 512


class EventBroker:
    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def subscribe(self, run_id: str) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=QUEUE_MAX)
        async with self._lock:
            self._subscribers[run_id].add(queue)
        return queue

    async def unsubscribe(self, run_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        async with self._lock:
            self._subscribers[run_id].discard(queue)
            if not self._subscribers[run_id]:
                self._subscribers.pop(run_id, None)

    async def publish(self, run_id: str, payload: dict[str, Any]) -> None:
        async with self._lock:
            queues = list(self._subscribers.get(run_id, ()))
        for queue in queues:
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                # Slow client: drop the oldest so live tailing keeps up. The
                # client can backfill from the database using seq numbers.
                try:
                    queue.get_nowait()
                    queue.put_nowait(payload)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass

    def subscriber_count(self, run_id: str) -> int:
        return len(self._subscribers.get(run_id, ()))


_broker: EventBroker | None = None


def get_broker() -> EventBroker:
    global _broker
    if _broker is None:
        _broker = EventBroker()
    return _broker
