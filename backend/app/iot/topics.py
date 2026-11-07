"""MQTT topic schema for the device telemetry channel (Module 9).

Grammar (both transports — real broker and the in-process fallback):

    {MQTT_BASE_TOPIC}/{farm_id}/{device_code}/telemetry/{soil|weather}

e.g. ``asiis/v1/7/PROBE-1/telemetry/soil``.

Rules enforced here (a message that fails any of these is rejected before
the pipeline ever sees it):
  * exact segment count, no leading/trailing slash, no wildcards (a device
    may only address its own concrete topic),
  * `farm_id` is a positive integer,
  * `device_code` matches DEVICE_CODE_RE — the SAME pattern the device
    registry uses, so a topic can only ever name a registrable code,
  * the kind segment must be `soil` or `weather`; the kind (not the
    payload) selects the schema, so a soil batch on a weather topic is a
    validation error downstream, never a silent reinterpretation.
"""

import re
from dataclasses import dataclass

from app.models.iot import DEVICE_CODE_RE

TELEMETRY_SEGMENT = "telemetry"
KINDS = ("soil", "weather")

_FARM_ID_RE = re.compile(r"^[1-9][0-9]{0,9}$")
_DEVICE_CODE_RE = re.compile(DEVICE_CODE_RE)


class TopicError(ValueError):
    """Malformed / non-concrete topic — message rejected, nothing stored."""


@dataclass(frozen=True)
class ParsedTopic:
    farm_id: int
    device_code: str
    kind: str  # "soil" | "weather"

    @property
    def model(self) -> str:
        """telemetry_service model key ('soil' | 'weather')."""
        return self.kind


def build_topic(base: str, farm_id: int, device_code: str, kind: str) -> str:
    if kind not in KINDS:
        raise TopicError(f"telemetry kind must be one of {KINDS}, got {kind!r}")
    if not _FARM_ID_RE.match(str(farm_id)):
        raise TopicError(f"farm_id must be a positive integer, got {farm_id!r}")
    if not _DEVICE_CODE_RE.match(device_code):
        raise TopicError(f"device_code {device_code!r} violates the registry pattern")
    return f"{base.strip('/')}/{farm_id}/{device_code}/{TELEMETRY_SEGMENT}/{kind}"


def subscription_wildcard(base: str) -> str:
    """Wildcard filter a subscriber uses: every device, both kinds."""
    return f"{base.strip('/')}/+/+/{TELEMETRY_SEGMENT}/+"


def parse_topic(topic: str, base: str) -> ParsedTopic:
    """Validate `topic` against the schema; raise TopicError otherwise."""
    if not isinstance(topic, str) or not topic or topic != topic.strip():
        raise TopicError("topic must be a non-empty, untrimmed-free string")
    if "#" in topic or "+" in topic:
        raise TopicError("wildcards are not valid publish topics")
    base = base.strip("/")
    if not base:
        raise TopicError("MQTT_BASE_TOPIC is not configured")
    parts = topic.split("/")
    base_parts = base.split("/")
    if len(parts) != len(base_parts) + 4:
        raise TopicError(
            f"topic must have {len(base_parts) + 4} segments "
            f"({base}/<farm_id>/<device_code>/{TELEMETRY_SEGMENT}/<kind>)"
        )
    if parts[: len(base_parts)] != base_parts:
        raise TopicError(f"topic must start with base {base!r}")
    farm_id, device_code, literal, kind = parts[len(base_parts):]
    if literal != TELEMETRY_SEGMENT:
        raise TopicError(f"segment 3 must be {TELEMETRY_SEGMENT!r}")
    if not _FARM_ID_RE.match(farm_id):
        raise TopicError(f"farm_id segment {farm_id!r} is not a positive integer")
    if not _DEVICE_CODE_RE.match(device_code):
        raise TopicError(f"device_code segment {device_code!r} is invalid")
    if kind not in KINDS:
        raise TopicError(f"telemetry kind {kind!r} must be one of {KINDS}")
    return ParsedTopic(farm_id=int(farm_id), device_code=device_code, kind=kind)


# ---------------------------------------------------------------------------
# MQTT wildcard filter matching for the in-process bus (same semantics as
# spec §4.7: '+' matches exactly one level, '#' matches the remainder).
# ---------------------------------------------------------------------------

def topic_matches(filter_: str, topic: str) -> bool:
    f_parts = filter_.split("/")
    t_parts = topic.split("/")
    for i, fp in enumerate(f_parts):
        if fp == "#":
            # must be last level; matches everything remaining (incl. none)
            return i == len(f_parts) - 1
        if i >= len(t_parts):
            return False
        if fp != "+" and fp != t_parts[i]:
            return False
    return len(f_parts) == len(t_parts)
