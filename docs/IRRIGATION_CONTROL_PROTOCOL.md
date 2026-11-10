# Irrigation controller protocol (M8/M9)

The backend sends zone commands only to one active `irrigation_controller`
device assigned to that zone. A zone start must reference a current,
safety-checked, approved irrigation schedule and a configured operator
application-rate cap. The controller must enforce the same runtime and local
hardware interlocks; the API does not directly operate a valve or pump.

## Device API

All device calls use the device's `X-Device-Key`; user JWTs cannot poll or
acknowledge actuator commands.

- `POST /api/v1/devices/heartbeat` updates controller liveness.
- `POST /api/v1/devices/commands/pending` returns queued commands and retries
  unacknowledged deliveries after 30 seconds.
- `POST /api/v1/devices/commands/{command_id}/ack` acknowledges execution.
- `POST /api/v1/devices/runtime` reports live running/flow/pressure state and
  completion of a previously acknowledged start command.

The command envelope contains `id`, `correlation_id`, `zone_id`,
`control_action`, `payload_json`, and `expires_at`. Devices should deduplicate
by `correlation_id`, process commands in order, and return the observed
physical running state. A successful `clear_emergency_stop` acknowledgement
must additionally set `interlocks_clear` to `true`.

The backend changes `is_running` only after a successful acknowledgement
confirms the requested state. Failed, mismatched, or expired commands latch
the backend emergency stop; they do not represent proof that the hardware is
off. Stop/emergency-stop commands do not expire. If no active controller is
available, the backend reports that physical shutdown is unconfirmed.
The controller must report scheduled completion through `/devices/runtime`
so the schedule and zone state do not remain marked as executing.

## Hardware safety boundary

Firmware must implement a local, normally-safe output state and an independent
physical emergency-stop input. Pump/valve sequencing, pressure/flow limits,
watchdog behavior, and offline operation must be enforced at the controller,
not inferred from API success. The backend command API cannot replace those
local protections. A live ESP32/Raspberry Pi integration test is required
before enabling control on real equipment.
