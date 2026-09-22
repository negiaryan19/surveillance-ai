"""In-process publish/subscribe bus feeding the dashboard's SSE stream.

Publishers are camera worker threads, so ``publish`` must never wait for a
consumer: every subscriber owns a bounded queue, and when a slow subscriber's
queue is full its OLDEST event is dropped. A stalled browser tab therefore
costs bounded memory and loses only its own stale events.

Event types and payloads (payloads are shared between subscribers and must be
treated as read-only):

* ``"incident"`` / ``"incident_updated"`` -- the API incident dict
* ``"status"`` -- ``{"cameras": [worker.status(), ...], "alerts_paused": bool}``
* ``"ack"`` -- ``{"id", "acknowledged"}``
* ``"zones"`` -- ``{"camera_id"}``
* ``"faces"`` -- ``{"count"}``
"""

from __future__ import annotations

import threading
from collections import deque


class Subscription:
    """One consumer's bounded event queue. Usable as a context manager."""

    def __init__(self, bus: EventBus, max_queue: int):
        self._bus = bus
        # deque(maxlen=n) evicts from the left on append: drop-oldest for free.
        self._queue: deque[tuple[str, dict]] = deque(maxlen=max_queue)
        self._ready = threading.Condition()
        self._closed = False
        self._dropped = 0

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def dropped(self) -> int:
        """Number of events this subscriber lost because it was too slow."""
        return self._dropped

    def _offer(self, item: tuple[str, dict]) -> None:
        """Called by the bus. Holds the lock for an append only -- never waits."""
        with self._ready:
            if self._closed:
                return
            if len(self._queue) == self._queue.maxlen:
                self._dropped += 1
            self._queue.append(item)
            self._ready.notify()

    def get(self, timeout: float | None = None) -> tuple[str, dict] | None:
        """Next ``(event_type, data)``, or None on timeout or once closed.

        ``timeout=None`` waits until an event arrives or the subscription is
        closed; ``timeout=0`` polls.
        """
        with self._ready:
            self._ready.wait_for(lambda: self._queue or self._closed, timeout)
            if self._closed or not self._queue:
                return None
            return self._queue.popleft()

    def close(self) -> None:
        """Detach from the bus and wake any blocked ``get``. Idempotent."""
        with self._ready:
            if self._closed:
                return
            self._closed = True
            self._queue.clear()
            self._ready.notify_all()
        self._bus._remove(self)

    def __enter__(self) -> Subscription:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


class EventBus:
    """Fan-out of events to every live :class:`Subscription`."""

    def __init__(self):
        self._lock = threading.Lock()
        self._subscriptions: tuple[Subscription, ...] = ()

    def publish(self, event_type: str, data: dict) -> None:
        """Deliver to every subscriber without ever blocking on one of them."""
        item = (event_type, data)
        # The tuple is replaced, never mutated, so iterating needs no lock.
        for subscription in self._subscriptions:
            subscription._offer(item)

    def subscribe(self, max_queue: int = 100) -> Subscription:
        if max_queue < 1:
            raise ValueError("max_queue must be at least 1")
        subscription = Subscription(self, int(max_queue))
        with self._lock:
            self._subscriptions = (*self._subscriptions, subscription)
        return subscription

    @property
    def subscriber_count(self) -> int:
        return len(self._subscriptions)

    def _remove(self, subscription: Subscription) -> None:
        with self._lock:
            self._subscriptions = tuple(existing for existing in self._subscriptions if existing is not subscription)
