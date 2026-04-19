#!/usr/bin/env python3
"""
takmessage_to_xml — Convert TakMessage protobuf back to CoT XML string.

This is the missing glue between takproto and meshtastic_tak.
It reverses takproto's xml2message(): TakMessage → CoT XML.

CoT XML is the interchange format that both libraries understand.
"""

from datetime import datetime, timezone


def _ms_to_iso(ms: int) -> str:
    """Convert milliseconds-since-epoch to ISO 8601 UTC string."""
    if ms <= 0:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    dt = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def takmessage_to_xml(tak_message) -> str:
    """Convert a TakMessage protobuf object to a CoT XML string.

    Args:
        tak_message: A takproto TakMessage protobuf object
                     (as returned by parse_proto or xml2message).

    Returns:
        CoT XML string suitable for CotXmlParser.parse() or multicast injection.
    """
    ev = tak_message.cotEvent

    # Event envelope
    uid = ev.uid or "unknown"
    cot_type = ev.type or "a-f-G-U-C"
    how = ev.how or "m-g"
    time_str = _ms_to_iso(ev.sendTime)
    start_str = _ms_to_iso(ev.startTime)
    stale_str = _ms_to_iso(ev.staleTime)

    # Optional event attributes
    extra_attrs = ""
    if ev.access:
        extra_attrs += f' access="{ev.access}"'
    if ev.qos:
        extra_attrs += f' qos="{ev.qos}"'
    if ev.opex:
        extra_attrs += f' opex="{ev.opex}"'

    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<event version="2.0" uid="{uid}" type="{cot_type}" how="{how}"'
        f' time="{time_str}" start="{start_str}" stale="{stale_str}"{extra_attrs}>',
        f'  <point lat="{ev.lat}" lon="{ev.lon}" hae="{ev.hae}" ce="{ev.ce}" le="{ev.le}"/>',
        '  <detail>',
    ]

    # Detail typed fields — only emit if the sub-message has data
    detail = ev.detail

    if detail.HasField("contact"):
        c = detail.contact
        parts = []
        if c.callsign:
            parts.append(f'callsign="{c.callsign}"')
        if c.endpoint:
            parts.append(f'endpoint="{c.endpoint}"')
        if parts:
            lines.append(f'    <contact {" ".join(parts)}/>')

    if detail.HasField("group"):
        g = detail.group
        parts = []
        if g.name:
            parts.append(f'name="{g.name}"')
        if g.role:
            parts.append(f'role="{g.role}"')
        if parts:
            lines.append(f'    <__group {" ".join(parts)}/>')

    if detail.HasField("status"):
        s = detail.status
        if s.battery:
            lines.append(f'    <status battery="{s.battery}"/>')

    if detail.HasField("track"):
        t = detail.track
        lines.append(f'    <track speed="{t.speed}" course="{t.course}"/>')

    if detail.HasField("takv"):
        tv = detail.takv
        parts = []
        if tv.device:
            parts.append(f'device="{tv.device}"')
        if tv.platform:
            parts.append(f'platform="{tv.platform}"')
        if tv.os:
            parts.append(f'os="{tv.os}"')
        if tv.version:
            parts.append(f'version="{tv.version}"')
        if parts:
            lines.append(f'    <takv {" ".join(parts)}/>')

    if detail.HasField("precisionLocation"):
        pl = detail.precisionLocation
        parts = []
        if pl.geopointsrc:
            parts.append(f'geopointsrc="{pl.geopointsrc}"')
        if pl.altsrc:
            parts.append(f'altsrc="{pl.altsrc}"')
        if parts:
            lines.append(f'    <precisionlocation {" ".join(parts)}/>')

    # Catch-all: xmlDetail contains raw XML fragments for anything
    # that doesn't fit the typed fields above
    if detail.xmlDetail:
        lines.append(f'    {detail.xmlDetail}')

    lines.append('  </detail>')
    lines.append('</event>')

    return "\n".join(lines)
