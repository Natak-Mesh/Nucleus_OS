#!/usr/bin/env python3
"""
gps_nmea.py — NMEA 0183 parser shared by the GPS tools.

Not run directly. gps-monitor.py feeds it raw sentences and keeps the
resulting fix; gps-status.py renders that fix. Splitting the parser out
means the future GPS_INPUT (MAVLink msgid 232) sender is a thin consumer
of this same module rather than a rewrite — the Fix fields below are
deliberately named to line up with GPS_INPUT.

Sentences understood:
    GxGGA  fix quality, lat/lon, altitude, sats used, HDOP
    GxRMC  validity, ground speed, course, UTC date+time
    GxGSA  fix type (1 none / 2 2D / 3 3D), PDOP/HDOP/VDOP
    GxGSV  satellites in view, with per-sat SNR

"x" is the talker: GP (GPS), GL (GLONASS), GA (Galileo), GN (combined).
"""

MESH_CONF = "/etc/nucleus/mesh.conf"

DEFAULT_PORT = "/dev/ttyUSB1"
DEFAULT_BAUD = 115200
STATE_FILE = "/run/nucleus/gps.json"


def read_mesh_conf():
    """Pull GPS_* out of mesh.conf if present. Same shape as the other tools."""
    conf = {}
    try:
        with open(MESH_CONF) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                conf[key.strip()] = val.strip().strip('"').strip("'")
    except OSError:
        pass
    return conf


def valid_checksum(sentence):
    """True if the NMEA checksum matches. sentence includes the leading $."""
    if not sentence.startswith("$") or "*" not in sentence:
        return False
    body, _, cksum = sentence[1:].partition("*")
    cksum = cksum.strip()
    if len(cksum) < 2:
        return False
    calc = 0
    for ch in body:
        calc ^= ord(ch)
    try:
        return calc == int(cksum[:2], 16)
    except ValueError:
        return False


def _to_float(s):
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _dm_to_deg(value, hemi):
    """NMEA ddmm.mmmm + hemisphere -> signed decimal degrees."""
    v = _to_float(value)
    if v is None or not hemi:
        return None
    deg = int(v / 100)
    minutes = v - deg * 100
    dec = deg + minutes / 60.0
    if hemi in ("S", "W"):
        dec = -dec
    return dec


class Fix:
    """Rolling snapshot of GNSS state, updated as sentences arrive.

    Field names track MAVLink GPS_INPUT where they overlap so the sender
    added later reads straight across.
    """

    def __init__(self):
        self.fix_type = 0            # 0/1 none, 2 = 2D, 3 = 3D
        self.lat = None             # decimal degrees
        self.lon = None             # decimal degrees
        self.alt = None             # metres MSL
        self.satellites_visible = 0  # from GSV
        self.satellites_used = 0     # from GGA
        self.hdop = None
        self.vdop = None
        self.pdop = None
        self.speed = None           # m/s over ground
        self.course = None          # degrees true
        self.utc_time = None        # "HHMMSS.ss"
        self.utc_date = None        # "DDMMYY"
        # constellation -> {prn: snr_or_None}, rebuilt across GSV pages
        self.sats = {}
        self._gsv_acc = {}

    @property
    def has_fix(self):
        return self.fix_type >= 2 and self.lat is not None

    def update(self, sentence):
        """Feed one raw NMEA line. Bad or unknown sentences are ignored."""
        sentence = sentence.strip()
        if not valid_checksum(sentence):
            return
        body = sentence[1:].split("*", 1)[0]
        parts = body.split(",")
        talker, kind = parts[0][:2], parts[0][2:]
        if kind == "GGA":
            self._gga(parts)
        elif kind == "RMC":
            self._rmc(parts)
        elif kind == "GSA":
            self._gsa(parts)
        elif kind == "GSV":
            self._gsv(talker, parts)

    def _gga(self, p):
        try:
            quality = int(p[6]) if p[6] else 0
        except ValueError:
            quality = 0
        if quality >= 1:
            self.lat = _dm_to_deg(p[2], p[3])
            self.lon = _dm_to_deg(p[4], p[5])
            self.alt = _to_float(p[9])
        else:
            self.lat = self.lon = self.alt = None
        try:
            self.satellites_used = int(p[7]) if p[7] else 0
        except ValueError:
            self.satellites_used = 0
        self.hdop = _to_float(p[8])
        self.utc_time = p[1] or None

    def _rmc(self, p):
        if p[2] != "A":
            self.speed = None
            self.course = None
        else:
            kn = _to_float(p[7])
            self.speed = kn * 0.514444 if kn is not None else None
            self.course = _to_float(p[8])
        self.utc_time = p[1] or self.utc_time
        self.utc_date = p[9] or self.utc_date

    def _gsa(self, p):
        try:
            self.fix_type = int(p[2]) if p[2] else self.fix_type
        except ValueError:
            pass
        self.pdop = _to_float(p[15]) if len(p) > 15 else None
        self.hdop = _to_float(p[16]) if len(p) > 16 else self.hdop
        self.vdop = _to_float(p[17]) if len(p) > 17 else None

    def _gsv(self, talker, p):
        try:
            total = int(p[1]); num = int(p[2])
        except (ValueError, IndexError):
            return
        acc = self._gsv_acc.setdefault(talker, {})
        for i in range(4, len(p) - 3, 4):
            prn = p[i]
            if not prn:
                continue
            snr = p[i + 3]
            acc[prn] = int(snr) if snr.isdigit() else None
        if num >= total:
            self.sats[talker] = acc
            self._gsv_acc[talker] = {}
            self.satellites_visible = sum(len(s) for s in self.sats.values())

    def to_dict(self):
        return {
            "fix_type": self.fix_type,
            "has_fix": self.has_fix,
            "lat": self.lat,
            "lon": self.lon,
            "alt": self.alt,
            "satellites_used": self.satellites_used,
            "satellites_visible": self.satellites_visible,
            "hdop": self.hdop,
            "vdop": self.vdop,
            "pdop": self.pdop,
            "speed": self.speed,
            "course": self.course,
            "utc_time": self.utc_time,
            "utc_date": self.utc_date,
            "sats": self.sats,
        }

