import threading
import time

import pytest

from src.events import EventBus
from src.threat_assessor import ThreatAssessor


# ------------------------------------------------------------------ events
def test_fan_out_ordering_and_timeout():
    bus = EventBus()
    a, b = bus.subscribe(), bus.subscribe()
    assert bus.subscriber_count == 2
    for i in range(3):
        bus.publish("incident", {"id": i})
    assert [a.get(0.1)[1]["id"] for _ in range(3)] == [0, 1, 2]
    assert [b.get(0.1)[1]["id"] for _ in range(3)] == [0, 1, 2]
    assert a.get(timeout=0.05) is None


def test_slow_subscriber_drops_oldest_and_publish_never_blocks():
    bus = EventBus()
    slow = bus.subscribe(max_queue=3)
    t0 = time.monotonic()
    for i in range(10):
        bus.publish("status", {"n": i})
    assert time.monotonic() - t0 < 0.5
    got = [slow.get(0.1)[1]["n"] for _ in range(3)]
    assert got == [7, 8, 9]


def test_close_removes_subscriber_and_context_manager():
    bus = EventBus()
    with bus.subscribe() as sub:
        assert bus.subscriber_count == 1
        bus.publish("ack", {"id": 1})
        assert sub.get(0.1)[0] == "ack"
    assert bus.subscriber_count == 0
    bus.publish("ack", {"id": 2})  # nobody listening: fine
    sub2 = bus.subscribe()
    waiter = threading.Thread(target=lambda: sub2.get(timeout=5))
    waiter.start()
    time.sleep(0.05)
    sub2.close()
    waiter.join(timeout=2)
    assert not waiter.is_alive()  # close unblocks a waiting get


def test_thread_safety_every_consumer_sees_every_event():
    bus = EventBus()
    subs = [bus.subscribe(max_queue=1000) for _ in range(3)]
    seen = {i: [] for i in range(3)}

    def consume(i):
        while True:
            item = subs[i].get(timeout=0.5)
            if item is None:
                return
            seen[i].append(item[1]["n"])

    consumers = [threading.Thread(target=consume, args=(i,)) for i in range(3)]
    for c in consumers:
        c.start()
    producers = [
        threading.Thread(target=lambda k=k: [bus.publish("x", {"n": k * 100 + j}) for j in range(100)])
        for k in range(4)
    ]
    for p in producers:
        p.start()
    for p in producers:
        p.join()
    for c in consumers:
        c.join()
    for i in range(3):
        assert sorted(seen[i]) == sorted(k * 100 + j for k in range(4) for j in range(100))


# ------------------------------------------------------------------ threat
@pytest.fixture
def ta():
    return ThreatAssessor(loiter_threshold=10.0)


def test_zone_and_object_weights(ta):
    assert ta.calculate_threat("SAFE", "Person")[0] == 50  # 30 person + 20 unknown
    assert ta.calculate_threat("PERIMETER", "Person")[0] == 70
    assert ta.calculate_threat("WARNING", "Person")[0] == 80
    assert ta.calculate_threat("CRITICAL", "Person")[0] == 90
    assert ta.calculate_threat("WARNING", "Car", face_status="N/A")[0] == 70
    assert ta.calculate_threat("WARNING", "Dog", face_status="N/A")[0] == 40
    assert ta.calculate_threat("SAFE", "Car", face_status="N/A")[0] == 40


def test_face_status_rules_only_for_persons(ta):
    score, cat, reasons = ta.calculate_threat("WARNING", "Person", face_status="KNOWN")
    assert score == 10 and cat == "LOW" and "Authorized Personnel" in reasons
    score, cat, reasons = ta.calculate_threat("WARNING", "Person", face_status="SPOOF")
    assert score == 100 and cat == "CRITICAL" and any("Spoof" in r for r in reasons)
    score, cat, reasons = ta.calculate_threat("WARNING", "Person", face_status="VERIFYING")
    assert score == 60 and cat == "WARNING" and "Verifying liveness" in reasons
    assert ta.calculate_threat("WARNING", "Car", face_status="KNOWN")[0] == 70  # ignored for vehicles


def test_behaviour_rules(ta):
    score, _, reasons = ta.calculate_threat("SAFE", "Person", is_crawling=True)
    assert score == 100 and "Suspicious Posture: Crawling/Prone" in reasons
    score, _, reasons = ta.calculate_threat("SAFE", "Person", is_anomaly=True, anomaly_type="RUNNING")
    assert score == 90 and "Anomalous Behavior: RUNNING" in reasons
    score, _, reasons = ta.calculate_threat("WARNING", "Person", loiter_seconds=12)
    assert score == 100 and "Loitering 12s" in reasons
    assert ta.calculate_threat("WARNING", "Person", loiter_seconds=9.9)[0] == 80
    assert ta.calculate_threat("SAFE", "Person", loiter_seconds=99)[0] == 50  # never in SAFE
    assert ta.calculate_threat("WARNING", "Person", face_status="KNOWN", loiter_seconds=99)[0] == 10
    assert ta.calculate_threat("WARNING", "Person", loiter_seconds=5, loiter_threshold=4)[0] == 100


def test_weapon_overrides_everything(ta):
    assert ta.calculate_threat("SAFE", "Weapon (Knife)", face_status="KNOWN", has_weapon=True) == (
        100,
        "CRITICAL",
        ["CRITICAL: Lethal Weapon Detected!"],
    )


def test_clamping_categories_and_purity(ta):
    assert ta.calculate_threat("SAFE", "Person", face_status="KNOWN")[0] == 0
    assert ta.calculate_threat("CRITICAL", "Person", face_status="SPOOF", is_crawling=True, is_anomaly=True)[0] == 100
    assert ta.calculate_threat("SAFE", "Dog", face_status="N/A")[1] == "LOW"  # 10
    assert ta.calculate_threat("PERIMETER", "Dog", face_status="N/A")[1] == "WARNING"  # 30
    assert ta.calculate_threat("WARNING", "Dog", face_status="N/A")[1] == "WARNING"  # 40
    assert ta.calculate_threat("PERIMETER", "Person")[1] == "CRITICAL"  # 70
    first = ta.calculate_threat("WARNING", "Person", is_anomaly=True)
    assert ta.calculate_threat("WARNING", "Person", is_anomaly=True) == first
