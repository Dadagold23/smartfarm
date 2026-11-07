"""Phase 2 (Module 9) — MQTT device channel.

Two interchangeable transports share ONE ingestion core (`handler`):

* `mqtt_client.MqttTelemetrySubscriber` — real paho-mqtt v2 subscriber for a
  reachable broker (mosquitto + TLS in production, credentials from env).
* `bus.InProcessMessageBus` — dependency-free fallback implementing the
  identical topic schema and publish/subscribe contract, so the whole MQTT
  path works on a machine without Docker/broker (dev, tests, embedded runs).

Both feed `app.services.telemetry_service` with `source='mqtt'`: identical
validation, (device, measured_at) dedupe and fault detection as HTTP ingest.
See README "IoT transport (MQTT)" for the security tradeoffs.
"""
