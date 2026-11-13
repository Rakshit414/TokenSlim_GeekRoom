"""SSE event bus for streaming real-time agent execution traces."""
import asyncio
from typing import Dict, Set
from sse_starlette.sse import ServerSentEvent

class EventBus:
    def __init__(self):
        self._queues: Dict[str, Set[asyncio.Queue]] = {}

    def subscribe(self, run_id: str) -> asyncio.Queue:
        if run_id not in self._queues:
            self._queues[run_id] = set()
        queue = asyncio.Queue()
        self._queues[run_id].add(queue)
        return queue

    def unsubscribe(self, run_id: str, queue: asyncio.Queue):
        if run_id in self._queues:
            self._queues[run_id].discard(queue)
            if not self._queues[run_id]:
                del self._queues[run_id]

    async def broadcast(self, run_id: str, event_data: dict):
        if run_id in self._queues:
            for queue in list(self._queues[run_id]):
                await queue.put(event_data)

event_bus = EventBus()
