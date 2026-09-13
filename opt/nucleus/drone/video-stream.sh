#!/bin/bash
# ============================================================
# Nucleus OS (Drone) - Video Stream
# ============================================================
# Captures H.264 from the CSI camera with rpicam-vid, wraps it in RTP with
# gstreamer, and pushes it to the ground station.
#
# QGroundControl's "UDP h.264" source is an RTP receiver, not a raw-stream
# reader, so the raw Annex-B that `rpicam-vid -o udp://...` emits will not
# render. gstreamer's rtph264pay supplies the RTP packetization QGC expects.
#
# rpicam-vid does the capture and hardware encode; gstreamer only payloads
# and sends. This avoids needing gstreamer1.0-libcamera for capture.
#
# Started by nucleus-video.service, which is gated on /etc/nucleus/video.enabled.
# config_generation.sh writes that flag from VIDEO_ENABLED in mesh.conf.

set -o pipefail

source /etc/nucleus/mesh.conf

if [ -z "${GCS_IP}" ]; then
    echo "video-stream: GCS_IP is empty in /etc/nucleus/mesh.conf - nothing to" >&2
    echo "video-stream: push video to. Set GCS_IP and re-run config_generation.sh." >&2
    exit 1
fi

WIDTH="${VIDEO_WIDTH:-640}"
HEIGHT="${VIDEO_HEIGHT:-480}"
FPS="${VIDEO_FPS:-30}"
BITRATE="${VIDEO_BITRATE:-750000}"
PORT="${VIDEO_UDP_PORT:-5600}"

# Only one process can hold the camera. A second rpicam-vid takes the UDP
# port but fails to get the sensor ("Device or resource busy"), accepting
# connections while sending no frames. Clear any stray instance first.
pkill -f rpicam-vid 2>/dev/null || true
sleep 1

echo "video-stream: ${WIDTH}x${HEIGHT}@${FPS} ${BITRATE}bps -> ${GCS_IP}:${PORT} (RTP H.264)"

# --inline + config-interval=1 repeat SPS/PPS so QGC can join mid-stream.
# --intra = FPS gives 1s keyframes for fast recovery. --profile baseline
# avoids B-frame reorder delay. mtu=1400 keeps RTP under the mesh MTU so the
# 802.11s path does not IP-fragment. sync=false drops rather than buffers
# when the link congests.
rpicam-vid -t 0 -n \
    --width "${WIDTH}" --height "${HEIGHT}" --framerate "${FPS}" \
    --codec h264 --inline --intra "${FPS}" --profile baseline \
    --bitrate "${BITRATE}" -o - \
  | gst-launch-1.0 -q \
    fdsrc ! h264parse config-interval=1 \
    ! rtph264pay pt=96 config-interval=1 mtu=1400 \
    ! udpsink host="${GCS_IP}" port="${PORT}" sync=false
