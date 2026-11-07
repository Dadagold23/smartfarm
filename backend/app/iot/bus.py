"""In-process message bus — dependency-free MQTT transport FALLBACK.

Implements the identical topic schema (app/iot/topics.py) and the same
publish/subscribe contract as the broker path, so the whole MQTT channel
(thesis: devices publish telemetry, backend subscribes and ingests) runs on
a machine with no broker and no Docker. This is NOT a mock of the pipeline:
published messages travel through the real handler, the real device-key
authentication, and the real telemetry_service ingestion + fault engine.

Contract parity with MQTT 3.1.1:
  * `subscribe(filter, handler)` — filter supports `+` and `#` wildcards.
  * `publish(topic, payload, credentials=...)` — synchronous fan-out to every
    matching subscriber; payload str|bytes like an MQTT PUBLISH.

Security tradeoff vs a real broker (documented in README):
  * no TLS — messages live in this process's memory, nothing hits a network;
  * authentication is CONSUMER-enforced (the subscriber validates the
    device key carried with each message), whereas mosquitto enforces it
    BROKER-side at CONNECT plus per-topic ACLs and can transport over TLS.
  Therefore the fallback is suitable for development/tests/embedded single-
  process runs only; production uses `MQTT_ENABLED=true` against a TLS
  broker with per-device credentials.
"""

import logging
import threading
from dataclasses import dataclass, field
from typing import Callable

from app.iot.topics import topic_matches

logger = logging.getLogger("asiis.iot.bus")

# Per-publish credentials mirror the MQTT CONNECT fields a publishing
# device presents to a real broker (username = device code, password =
# device API key).
@dataclass(frozen=True)
class BusCredentials:
    """Per-publish credentials — mirrors MQTT CONNECT username/password."""
    username: str = ""
    password: str = ""


@dataclass(frozen=True)
class BusMessage:
    topic: str
    payload: bytes
    credentials: BusCredentials = field(default_factory=BusCredentials)


MessageHandler = Callable[[BusMessage], None]


class InProcessMessageBus:
    """Minimal pub/sub with MQTT wildcard semantics; thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subs: dict[int, tuple[str, MessageHandler]] = {}
        self._next_id = 1
        self.published_count = 0

    def subscribe(self, filter_: str, handler: MessageHandler) -> int:
        if not filter_ or "/" not in filter_:
            raise ValueError(f"invalid subscription filter {filter_!r}")
        with self._lock:
            token = self._next_id
            self._next_id += 1
            self._subs[token] = (filter_, handler)
        return token

    def unsubscribe(self, token: int) -> None:
        with self._lock:
            self._subs.pop(token, None)

    def clear(self) -> None:
        with self._lock:
            self._subs.clear()

    def publish(self, topic: str, payload: str | bytes, *,
                credentials: BusCredentials | None = None) -> int:
        """Fan out one message; returns how many subscribers received it.

        Handler exceptions are contained (logged): like a real broker
        dropping delivery to a faulted subscriber, one bad consumer must
        not crash the publisher.
        """
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        msg = BusMessage(topic=topic, payload=payload,
                         credentials=credentials or BusCredentials())
        with self._lock:
            targets = [(f, h) for (f, h) in self._subs.values()
                       if topic_matches(f, topic)]
            self.published_count += 1
        delivered = 0
        for _flt, handler in targets:
            try:
                handler(msg)
                delivered += 1
            except Exception:  # noqa: BLE001 — contain consumer faults
                logger.exception("bus subscriber failed for topic %s", topic)
        return delivered


_bus: InProcessMessageBus | None = None
_bus_lock = threading.Lock()


def get_bus() -> InProcessMessageBus:
    """Process-wide fallback bus (created on first use)."""
    global _bus
    with _bus_lock:
        if _bus is None:
            _bus = InProcessMessageBus()
        return _bus


def reset_bus() -> None:
    """Drop all subscriptions — test isolation helper."""
    global _bus
    with _bus_lock:
        if _bus is not None:
            _bus.clear()
        _bus = None
