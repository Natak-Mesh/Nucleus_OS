# MAVLink to a GCS over Mesh and Cellular

How a ground control station reaches the drone over the 802.11s mesh in the
field, over Tailscale/cellular when out of mesh range, or both at once — with
no change to the drone configuration.

## The short version

The drone's `mavlink-router` already listens on **one** UDP endpoint bound to
all interfaces. That single endpoint is reachable over every network the Pi is
attached to. The GCS picks a path by choosing which of the drone's IP addresses
it connects to.

| Path | Drone address the GCS connects to | Carried on |
|---|---|---|
| Mesh (field) | `10.20.1.26:14550` | 802.11s mesh, `wlan1` |
| Cellular | `100.91.66.103:14550` | Tailscale over the LTE modem, `tailscale0` |

These are this node's addresses (`MESH_IP` in `mesh.conf` and `tailscale ip
-4`). Substitute the values for the node you are actually flying.

## Why one endpoint covers both

`/etc/mavlink-router/main.conf` has:

```ini
[UdpEndpoint ground]
Mode = Server
Address = 0.0.0.0
Port = 14550
```

`Address = 0.0.0.0` binds the port on **all** interfaces at once — mesh,
Tailscale, ethernet, everything the Pi has. There is nothing per-interface to
configure. A packet for `10.20.1.26:14550` and a packet for
`100.91.66.103:14550` both arrive on this one listener.

This is why no drone-side change is needed to add the cellular path, and why a
second endpoint would add nothing.

## How the drone knows which path to reply on

It does not choose. `Mode = Server` is passive: it learns each GCS from the
**source address of the packet the GCS sends in**, and streams telemetry back
to that same address.

- GCS connects over the mesh → packets arrive from `10.20.x.x` → replies go to
  `10.20.x.x` → the kernel routes them out `wlan1`.
- GCS connects over Tailscale → packets arrive from `100.x` → replies go to
  `100.x` → the kernel routes them out `tailscale0`.

The outbound interface is decided by the kernel routing table per destination
address. The drone simply mirrors traffic back along whichever path each client
used.

`Mode = Server` also tracks more than one client, so if the GCS connects over
**both** paths at once the drone streams to both.

## Setting up the GCS (QGroundControl on the laptop)

Nothing is entered on the drone. On the laptop, create two UDP comm links, one
per path:

1. Application Settings → Comm Links → Add.
2. Type: UDP. Add a link named e.g. `drone-mesh`, host `10.20.1.26`, port
   `14550`.
3. Add a second link named e.g. `drone-cell`, host `100.91.66.103`, port
   `14550`.

Connect the one that matches where you are:

- In the field, in mesh range: connect `drone-mesh`.
- Out of mesh range, on cellular: connect `drone-cell`.

## Switching paths

- **No drone-side change and no restart** is needed to switch. The drone is
  listening on both the whole time.
- Switching is done entirely on the laptop by changing which QGC comm link is
  connected.
- MAVLink re-syncs parameters on a fresh connection, so expect a short
  re-load when you connect a link.

## Not covered by this setup

- **No automatic failover.** If the connected path drops, QGC does not move to
  the other path on its own — you select the other link manually.
- **Two links connected simultaneously to the same vehicle is untested here.**
  The drone will stream to both; how QGC merges or duplicates the vehicle when
  both are up has not been verified.

## Cellular path prerequisites

The cellular path depends on Tailscale being up on both ends:

```sh
tailscale status          # drone and laptop both present and online
tailscale ip -4           # the drone address to use in the GCS link
```

The LTE modem carries the Tailscale traffic. The drone's carrier address is
CGNAT (`10.130.209.162/30` here), so the drone is not directly reachable on the
public internet — Tailscale is what makes the `100.x` address reachable.
