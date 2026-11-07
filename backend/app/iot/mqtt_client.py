"""Real MQTT (paho-mqtt 2.x) subscriber for the device telemetry channel.

Connection parameters come from the environment only (never code):
MQTT_HOST/PORT/USERNAME/PASSWORD, MQTT_USE_TLS + MQTT_CA_CERTS for the
spec-mandated encrypted comms, MQTT_BASE_TOPIC for the topic schema.

Security model on a real broker (production, spec §Security):
  * each device/gateway opens its own TLS connection and authenticates at
    CONNECT with username = device code, password = its device API key
    (mosquitto verifies the key against the registry via its password
    file/plugin), and
  * a per-topic ACL confines every device to publish ONLY under
    `{base}/{farm_id}/{own_code}/#` — broker-enforced, before our code
    ever sees a byte. A ready-to-use mosquitto config + ACL example lives
    in `backend/iot/mosquitto/` (see README).
  * Defence in depth: the payload may additionally carry `"device_key"`,
    which `handler.process_telemetry_message` verifies against the topic's
    device even if the broker config were misconfigured.

Lifecycle: `start_if_enabled()` is called from the FastAPI lifespan. If
MQTT_ENABLED is false, or the broker is unreachable, it returns None and
the caller keeps the in-process fallback bus — with a loud log line, no
silent pretend-connected state.
"""

import logging
import ssl
from typing import Callable

import paho.mqtt.client as mqtt

from app.core.config import Settings, get_settings
from app.iot.bus import BusCredentials
from app.iot.handler import process_telemetry_message
from app.iot.topics import subscription_wildcard

logger = logging.getLogger("asiis.iot.mqtt")


class MqttTelemetrySubscriber:
    """Subscribes `{base}/+/+/telemetry/+` and feeds the shared handler."""

    def __init__(self, settings: Settings, session_factory,
                 on_result: Callable[[dict], None] | None = None) -> None:
        self._settings = settings
        self._session_factory = session_factory
        self._on_result = on_result or (lambda r: None)
        self._connected = False
        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id="asiis-backend-subscriber",
            protocol=mqtt.MQTTProtocolVersion.MQTTv311,
        )
        if settings.MQTT_USERNAME:
            self.client.username_pw_set(settings.MQTT_USERNAME,
                                        settings.MQTT_PASSWORD)
        if settings.MQTT_USE_TLS:
            if not settings.MQTT_CA_CERTS:
                raise ValueError(
                    "MQTT_USE_TLS=true requires MQTT_CA_CERTS (broker CA file) "
                    "— refusing an unverifiable TLS connection")
            self.client.tls_set(ca_certs=settings.MQTT_CA_CERTS,
                                cert_reqs=ssl.CERT_REQUIRED)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

    # -- paho callbacks -----------------------------------------------------

    def _on_connect(self, client, _userdata, _flags, reason_code, _props=None):
        if reason_code.is_failure:
            logger.error("MQTT connect failed: %s", reason_code)
            return
        wildcard = subscription_wildcard(self._settings.MQTT_BASE_TOPIC)
        client.subscribe(wildcard)
        self._connected = True
        logger.info("MQTT subscribed to %s at %s:%s tls=%s",
                    wildcard, self._settings.MQTT_HOST,
                    self._settings.MQTT_PORT, self._settings.MQTT_USE_TLS)

    def _on_disconnect(self, client, _userdata, _flags, reason_code,
                       _props=None):
        self._connected = False
        logger.warning("MQTT disconnected: %s", reason_code)

    def _on_message(self, client, _userdata, message):
        # Credentials seen by the subscriber are the broker-account ones the
        # backend itself connected with; real per-device authentication is
        # broker ACL-enforced upstream, and an optional payload device_key
        # is verified inside the handler (defence in depth).
        creds = BusCredentials(username=self._settings.MQTT_USERNAME,
                               password=self._settings.MQTT_PASSWORD)
        with self._session_factory() as db:
            result = process_telemetry_message(
                db, topic=message.topic, payload=message.payload,
                credentials=creds,
                base_topic=self._settings.MQTT_BASE_TOPIC,
            )
        if not result["ok"]:
            logger.warning("MQTT message rejected on %s: %s (%s)",
                           message.topic, result["status"],
                           result.get("error"))
        self._on_result(result)

    # -- lifecycle -----------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._connected

    def start(self, timeout_s: float = 5.0) -> None:
        """Blocking connect (raises OSError on unreachable broker), then a
        paho network thread for the app's lifetime."""
        self.client.connect(self._settings.MQTT_HOST, self._settings.MQTT_PORT,
                            keepalive=60)
        self.client.loop_start()

    def stop(self) -> None:
        self.client.loop_stop()
        try:
            self.client.disconnect()
        except Exception:  # noqa: BLE001 — best-effort teardown
            pass


def start_if_enabled(session_factory) -> MqttTelemetrySubscriber | None:
    """Start the real broker subscriber when configured/reachable.

    Returns None (with an explicit log) when disabled or unreachable — the
    caller then relies on the in-process fallback bus. No fake 'connected'
    state is ever reported.
    """
    settings = get_settings()
    if not settings.MQTT_ENABLED:
        return None
    sub = MqttTelemetrySubscriber(settings, session_factory)
    try:
        sub.start()
    except OSError as exc:
        logger.warning(
            "MQTT_ENABLED=true but broker %s:%s unreachable (%s) — telemetry "
            "over MQTT is NOT live; the in-process fallback bus remains "
            "available. Start mosquitto (see backend/iot/mosquitto/) or set "
            "MQTT_ENABLED=false.",
            settings.MQTT_HOST, settings.MQTT_PORT, exc,
        )
        return None
    return sub
