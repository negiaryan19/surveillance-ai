"""src.events: fan-out, ordering, drop-oldest, timeouts, close, thread safety."""

from __future__ import annotations

import threading
import time

import pytest

from src.events import EventBus, Subscription


def drain(sub: Subscription) -> list[tuple[str, dict]]:
    """Every event currently queued, in delivery order (non-blocking)."""
    items = []
    while True:
        item = sub.get(timeout=0)
        if item is None:
            return items
        items.append(item)


# --------------------------------------------------------------------------- #
# basic API shape
# --------------------------------------------------------------------------- #
def test_subscribe_returns_subscription_and_counts():
    bus = EventBus()
    assert bus.subscriber_count == 0
    a = bus.subscribe()
    assert isinstance(a, Subscription)
    assert bus.subscriber_count == 1
    b = bus.subscribe(max_queue=5)
    assert bus.subscriber_count == 2
    a.close()
    assert bus.subscriber_count == 1
    b.close()
    assert bus.subscriber_count == 0


def test_subscriber_count_is_a_read_only_int_property():
    bus = EventBus()
    assert isinstance(type(bus).subscriber_count, property)
    assert isinstance(bus.subscriber_count, int)
    with pytest.raises(AttributeError):
        bus.subscriber_count = 5  # type: ignore[misc]


def test_subscribe_rejects_non_positive_queue():
    bus = EventBus()
    with pytest.raises(ValueError):
        bus.subscribe(max_queue=0)
    with pytest.raises(ValueError):
        bus.subscribe(max_queue=-1)
    assert bus.subscriber_count == 0


def test_publish_with_no_subscribers_is_a_noop():
    bus = EventBus()
    bus.publish("status", {"cameras": [], "alerts_paused": False})  # must not raise
    assert bus.subscriber_count == 0


def test_get_returns_event_type_and_data_tuple():
    bus = EventBus()
    with bus.subscribe() as sub:
        payload = {"id": 7, "acknowledged": True}
        bus.publish("ack", payload)
        item = sub.get(timeout=1)
        assert item == ("ack", {"id": 7, "acknowledged": True})
        assert isinstance(item, tuple) and len(item) == 2
        assert item[1] is payload  # payloads are shared, not copied


# --------------------------------------------------------------------------- #
# fan-out + ordering
# --------------------------------------------------------------------------- #
def test_fan_out_to_multiple_subscribers():
    bus = EventBus()
    subs = [bus.subscribe() for _ in range(3)]
    bus.publish("incident", {"id": 1})
    bus.publish("zones", {"camera_id": "alpha"})
    bus.publish("faces", {"count": 4})
    expected = [("incident", {"id": 1}), ("zones", {"camera_id": "alpha"}), ("faces", {"count": 4})]
    for sub in subs:
        assert drain(sub) == expected
    for sub in subs:
        sub.close()


def test_events_are_delivered_in_publish_order():
    bus = EventBus()
    with bus.subscribe(max_queue=1000) as sub:
        for i in range(500):
            bus.publish("incident", {"id": i})
        ids = [data["id"] for _, data in drain(sub)]
        assert ids == list(range(500))


def test_subscriber_only_sees_events_published_after_subscribing():
    bus = EventBus()
    early = bus.subscribe()
    bus.publish("incident", {"id": 1})
    late = bus.subscribe()
    bus.publish("incident", {"id": 2})
    assert drain(early) == [("incident", {"id": 1}), ("incident", {"id": 2})]
    assert drain(late) == [("incident", {"id": 2})]
    early.close()
    late.close()


def test_consuming_from_one_subscriber_does_not_affect_another():
    bus = EventBus()
    a = bus.subscribe()
    b = bus.subscribe()
    bus.publish("ack", {"id": 1, "acknowledged": True})
    assert a.get(timeout=0) == ("ack", {"id": 1, "acknowledged": True})
    assert a.get(timeout=0) is None
    assert b.get(timeout=0) == ("ack", {"id": 1, "acknowledged": True})
    a.close()
    b.close()


# --------------------------------------------------------------------------- #
# never blocks: slow subscriber drops its OLDEST
# --------------------------------------------------------------------------- #
def test_full_subscriber_drops_oldest_and_keeps_newest():
    bus = EventBus()
    sub = bus.subscribe(max_queue=3)
    for i in range(10):
        bus.publish("incident", {"id": i})
    ids = [data["id"] for _, data in drain(sub)]
    assert ids == [7, 8, 9]
    sub.close()


def test_dropped_counter_counts_lost_events():
    bus = EventBus()
    sub = bus.subscribe(max_queue=3)
    assert sub.dropped == 0
    for i in range(10):
        bus.publish("incident", {"id": i})
    assert sub.dropped == 7
    drain(sub)
    assert sub.dropped == 7  # draining does not reset the counter
    bus.publish("incident", {"id": 10})
    assert sub.dropped == 7  # room again -> nothing dropped
    sub.close()


def test_publish_never_blocks_on_a_full_subscriber_that_nobody_reads():
    bus = EventBus()
    sub = bus.subscribe(max_queue=1)
    started = time.monotonic()
    for i in range(10_000):
        bus.publish("status", {"cameras": [], "alerts_paused": False, "n": i})
    elapsed = time.monotonic() - started
    assert elapsed < 2.0  # generous: a blocking put would hang forever
    assert sub.dropped == 9_999
    assert drain(sub) == [("status", {"cameras": [], "alerts_paused": False, "n": 9_999})]
    sub.close()


def test_slow_subscriber_does_not_starve_a_fast_one():
    bus = EventBus()
    slow = bus.subscribe(max_queue=2)
    fast = bus.subscribe(max_queue=100)
    for i in range(20):
        bus.publish("incident", {"id": i})
    assert [d["id"] for _, d in drain(fast)] == list(range(20))
    assert [d["id"] for _, d in drain(slow)] == [18, 19]
    assert fast.dropped == 0 and slow.dropped == 18
    slow.close()
    fast.close()


# --------------------------------------------------------------------------- #
# get(timeout)
# --------------------------------------------------------------------------- #
def test_get_returns_none_on_timeout():
    bus = EventBus()
    with bus.subscribe() as sub:
        started = time.monotonic()
        assert sub.get(timeout=0.1) is None
        elapsed = time.monotonic() - started
        assert 0.08 <= elapsed < 1.0


def test_get_with_zero_timeout_polls():
    bus = EventBus()
    with bus.subscribe() as sub:
        assert sub.get(timeout=0) is None
        bus.publish("faces", {"count": 1})
        assert sub.get(timeout=0) == ("faces", {"count": 1})
        assert sub.get(timeout=0) is None


def test_get_wakes_when_an_event_is_published_from_another_thread():
    bus = EventBus()
    with bus.subscribe() as sub:
        threading.Timer(0.05, bus.publish, args=("zones", {"camera_id": "bravo"})).start()
        started = time.monotonic()
        assert sub.get(timeout=5) == ("zones", {"camera_id": "bravo"})
        assert time.monotonic() - started < 2.0  # woke on notify, not on timeout


def test_get_without_timeout_blocks_until_event():
    bus = EventBus()
    with bus.subscribe() as sub:
        threading.Timer(0.05, bus.publish, args=("ack", {"id": 3, "acknowledged": False})).start()
        assert sub.get() == ("ack", {"id": 3, "acknowledged": False})


# --------------------------------------------------------------------------- #
# close()
# --------------------------------------------------------------------------- #
def test_close_removes_subscriber_and_stops_delivery():
    bus = EventBus()
    sub = bus.subscribe()
    other = bus.subscribe()
    sub.close()
    assert bus.subscriber_count == 1
    bus.publish("incident", {"id": 1})
    assert sub.get(timeout=0) is None
    assert drain(other) == [("incident", {"id": 1})]
    other.close()


def test_close_unblocks_a_waiting_get():
    bus = EventBus()
    sub = bus.subscribe()
    results: list = []

    def consumer():
        results.append(sub.get(timeout=10))

    worker = threading.Thread(target=consumer, daemon=True)
    worker.start()
    time.sleep(0.05)  # let the consumer block inside get()
    started = time.monotonic()
    sub.close()
    worker.join(timeout=2)
    assert not worker.is_alive()
    assert time.monotonic() - started < 2.0
    assert results == [None]


def test_close_discards_queued_events_and_reports_closed():
    bus = EventBus()
    sub = bus.subscribe()
    bus.publish("incident", {"id": 1})
    assert sub.closed is False
    sub.close()
    assert sub.closed is True
    assert sub.get(timeout=0) is None
    assert sub.get() is None  # closed -> returns immediately even without a timeout


def test_close_is_idempotent():
    bus = EventBus()
    sub = bus.subscribe()
    sub.close()
    sub.close()
    sub.close()
    assert bus.subscriber_count == 0


def test_closing_one_subscription_does_not_remove_others():
    bus = EventBus()
    subs = [bus.subscribe() for _ in range(4)]
    subs[1].close()
    assert bus.subscriber_count == 3
    bus.publish("faces", {"count": 2})
    for i in (0, 2, 3):
        assert subs[i].get(timeout=0) == ("faces", {"count": 2})
    for i in (0, 2, 3):
        subs[i].close()
    assert bus.subscriber_count == 0


# --------------------------------------------------------------------------- #
# context manager
# --------------------------------------------------------------------------- #
def test_context_manager_closes_on_exit():
    bus = EventBus()
    with bus.subscribe() as sub:
        assert sub is not None
        assert bus.subscriber_count == 1
        bus.publish("incident", {"id": 1})
        assert sub.get(timeout=0) == ("incident", {"id": 1})
    assert bus.subscriber_count == 0
    assert sub.closed


def test_context_manager_closes_on_exception():
    bus = EventBus()
    with pytest.raises(RuntimeError):
        with bus.subscribe() as sub:
            raise RuntimeError("boom")
    assert bus.subscriber_count == 0
    assert sub.closed


def test_enter_returns_the_same_subscription():
    bus = EventBus()
    sub = bus.subscribe()
    with sub as entered:
        assert entered is sub
    assert bus.subscriber_count == 0


# --------------------------------------------------------------------------- #
# thread safety
# --------------------------------------------------------------------------- #
def test_publisher_thread_and_three_consumers_see_every_event():
    bus = EventBus()
    total = 2000
    consumers = 3
    subs = [bus.subscribe(max_queue=total + 10) for _ in range(consumers)]
    received: list[list[int]] = [[] for _ in range(consumers)]

    def consume(index: int):
        while True:
            item = subs[index].get(timeout=5)
            if item is None:
                return
            received[index].append(item[1]["id"])
            if item[0] == "done":
                return

    def produce():
        for i in range(total):
            bus.publish("incident", {"id": i})
        bus.publish("done", {"id": total})

    threads = [threading.Thread(target=consume, args=(i,), daemon=True) for i in range(consumers)]
    for t in threads:
        t.start()
    producer = threading.Thread(target=produce, daemon=True)
    producer.start()
    producer.join(timeout=10)
    for t in threads:
        t.join(timeout=10)
    assert not producer.is_alive()
    assert all(not t.is_alive() for t in threads)
    expected = list(range(total)) + [total]
    for index in range(consumers):
        assert received[index] == expected, f"consumer {index} missed or reordered events"
        assert subs[index].dropped == 0
    for sub in subs:
        sub.close()


def test_multiple_publisher_threads_lose_nothing_with_a_big_queue():
    bus = EventBus()
    per_thread = 500
    publishers = 4
    sub = bus.subscribe(max_queue=per_thread * publishers + 10)

    def produce(tag: int):
        for i in range(per_thread):
            bus.publish("incident", {"tag": tag, "id": i})

    threads = [threading.Thread(target=produce, args=(tag,), daemon=True) for tag in range(publishers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    items = drain(sub)
    assert len(items) == per_thread * publishers
    assert sub.dropped == 0
    # Per-publisher order is preserved even though the interleaving is arbitrary.
    for tag in range(publishers):
        assert [d["id"] for _, d in items if d["tag"] == tag] == list(range(per_thread))
    sub.close()


def test_concurrent_subscribe_and_close_while_publishing():
    bus = EventBus()
    stop = threading.Event()

    def publish_loop():
        n = 0
        while not stop.is_set():
            bus.publish("status", {"cameras": [], "alerts_paused": False, "n": n})
            n += 1

    def churn():
        for _ in range(200):
            with bus.subscribe(max_queue=5) as sub:
                sub.get(timeout=0)

    publisher = threading.Thread(target=publish_loop, daemon=True)
    publisher.start()
    churners = [threading.Thread(target=churn, daemon=True) for _ in range(3)]
    for t in churners:
        t.start()
    for t in churners:
        t.join(timeout=10)
    stop.set()
    publisher.join(timeout=5)
    assert not publisher.is_alive()
    assert all(not t.is_alive() for t in churners)
    assert bus.subscriber_count == 0
