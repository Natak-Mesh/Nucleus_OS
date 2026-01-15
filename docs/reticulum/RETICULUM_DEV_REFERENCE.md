# RETICULUM DEVELOPER REFERENCE (CONDENSED)

## OVERVIEW

Reticulum is a cryptography-based networking stack for building local and wide-area networks with minimal infrastructure. Operates over extremely low bandwidth (5+ bps), provides end-to-end encryption, forward secrecy, and autoconfiguring multi-hop transport.

**Key Properties:**
- No address allocation needed - destinations are cryptographic hashes
- Hardware agnostic - works over any medium (LoRa, WiFi, serial, TCP, etc)
- Trustless - no assumptions about network infrastructure security
- Initiator anonymous - packets don't reveal source addresses
- MTU: 500 bytes, Link MDU varies by configuration

## CORE CONCEPTS

### Destinations
Endpoints in the network. Types:
- **SINGLE**: Encrypted, one recipient (uses recipient's public key)
- **GROUP**: Symmetric encryption, pre-shared key
- **PLAIN**: Unencrypted, broadcast only

Destination hash = SHA-256(identity.pubkey + app_name + aspects)[:16 bytes]

### Identities
Cryptographic identity = 512-bit keypair (256-bit encryption + 256-bit signing)
- Uses X25519 for ECDH, Ed25519 for signatures
- Can create multiple destinations from one identity
- Portable across networks

### Transport
Multi-hop routing via announces:
- Destinations announce existence (signed packets with pubkey)
- Transport nodes forward announces, build path tables
- Packets routed hop-by-hop using destination hash
- No node knows full path, only next hop

### Links
Encrypted, verified bidirectional channels:
- 3-packet establishment (request, proof, confirmed)
- Total overhead: 297 bytes
- ECDH key exchange on Curve25519 → ephemeral AES-256
- Keepalive: 0.44 bits/sec
- Provides reliability, forward secrecy, optional authentication

---

## API REFERENCE

### RNS.Reticulum
```python
RNS.Reticulum(configdir=None, loglevel=None)
```
Initialize Reticulum. Required before any operations.

**Constants:**
- `MTU = 500` - Network MTU
- `ANNOUNCE_CAP = 2` - Max % bandwidth for announces

**Static Methods:**
- `get_instance()` → current instance
- `transport_enabled()` → bool
- `should_use_implicit_proof()` → bool

### RNS.Identity
```python
identity = RNS.Identity()  # Generate new
identity = RNS.Identity.from_bytes(prv_bytes)
identity = RNS.Identity.from_file(path)
identity.to_file(path)
```

**Key Methods:**
- `get_public_key()` → bytes
- `get_private_key()` → bytes
- `encrypt(plaintext)` → ciphertext
- `decrypt(ciphertext)` → plaintext
- `sign(message)` → signature
- `validate(signature, message)` → bool

**Static Methods:**
- `recall(dest_hash)` → Identity (from network memory)
- `recall_app_data(dest_hash)` → bytes
- `full_hash(data)` → SHA-256
- `truncated_hash(data)` → SHA-256[:16]
- `current_ratchet_id(dest_hash)` → bytes

**Ratchets (Forward Secrecy):**
- `RATCHET_EXPIRY = 2592000` (30 days)

### RNS.Destination
```python
dest = RNS.Destination(
    identity,           # RNS.Identity instance
    direction,          # RNS.Destination.IN or OUT
    type,              # SINGLE, GROUP, or PLAIN
    app_name,          # str
    *aspects           # str args
)
```

**Constants:**
- `RATCHET_COUNT = 512` - Default retained ratchets
- `RATCHET_INTERVAL = 1800` - Min seconds between rotations

**Methods:**
- `announce(app_data=None, send=True)`
- `accepts_links(accepts=None)` - Set/get if accepting links
- `set_link_established_callback(callback)` - `callback(link)`
- `set_packet_callback(callback)` - `callback(data, packet)`
- `set_proof_requested_callback(callback)` - `callback(packet)` → bool
- `set_proof_strategy(strategy)` - PROVE_NONE, PROVE_ALL, PROVE_APP
- `register_request_handler(path, response_generator, allow, allowed_list)`
- `deregister_request_handler(path)`
- `enable_ratchets(ratchets_path)` - Enable forward secrecy
- `enforce_ratchets()` - Reject packets encrypted with base key
- `set_retained_ratchets(count)`
- `set_ratchet_interval(seconds)`
- `encrypt(plaintext)` → ciphertext
- `decrypt(ciphertext)` → plaintext
- `sign(message)` → signature
- `set_default_app_data(app_data)`

**Static Methods:**
- `hash(identity, app_name, *aspects)` → bytes
- `expand_name(identity, app_name, *aspects)` → full_name_str

### RNS.Packet
```python
packet = RNS.Packet(destination, data, create_receipt=True)
packet.send()  # → PacketReceipt or False
packet.resend()
```

**Constants:**
- `ENCRYPTED_MDU = 383` bytes
- `PLAIN_MDU = 464` bytes

**Methods:**
- `get_rssi()` → float or None
- `get_snr()` → float or None
- `get_q()` → float or None

### RNS.PacketReceipt
```python
receipt.get_status()  # SENT, DELIVERED, FAILED, CULLED
receipt.get_rtt()  # seconds
receipt.set_timeout(seconds)
receipt.set_delivery_callback(callback)  # callback(receipt)
receipt.set_timeout_callback(callback)
```

### RNS.Link
```python
link = RNS.Link(destination, established_callback, closed_callback)
```

**Constants:**
- `ESTABLISHMENT_TIMEOUT_PER_HOP = 6` seconds
- `KEEPALIVE_TIMEOUT_FACTOR = 4`
- `STALE_GRACE = 5` seconds
- `KEEPALIVE = 360` seconds
- `STALE_TIME = 720` seconds

**Methods:**
- `identify(identity)` - Reveal initiator identity
- `request(path, data, response_callback, failed_callback, progress_callback, timeout)` → RequestReceipt
- `track_phy_stats(bool)` - Enable physical layer stats
- `get_rssi()`, `get_snr()`, `get_q()`
- `get_establishment_rate()` - bps
- `get_mtu()`, `get_mdu()`
- `get_expected_rate()` - Expected in-flight rate
- `get_mode()`
- `get_age()` - Seconds since established
- `no_inbound_for()`, `no_outbound_for()`, `no_data_for()`, `inactive_for()`
- `get_remote_identity()` → Identity or None
- `teardown()`
- `get_channel()` → Channel

**Callbacks:**
- `set_link_closed_callback(callback)` - `callback(link)`
- `set_packet_callback(callback)` - `callback(message, packet)`
- `set_resource_callback(callback)` - `callback(resource)` → bool (accept?)
- `set_resource_started_callback(callback)`
- `set_resource_concluded_callback(callback)`
- `set_remote_identified_callback(callback)` - `callback(link, identity)`
- `set_resource_strategy(strategy)` - ACCEPT_NONE, ACCEPT_ALL, ACCEPT_APP

### RNS.RequestReceipt
```python
receipt.get_request_id()  # bytes
receipt.get_status()  # FAILED, SENT, DELIVERED, READY
receipt.get_progress()  # 0.0-1.0
receipt.get_response()  # bytes or None
receipt.get_response_time()  # seconds
receipt.concluded()  # bool
```

### RNS.Resource
```python
resource = RNS.Resource(
    data,              # bytes or file handle
    link,              # RNS.Link
    advertise=True,
    auto_compress=True,
    callback=None,     # callback(resource)
    progress_callback=None
)
resource.advertise()
resource.cancel()
```

**Methods:**
- `get_progress()` - 0.0-1.0
- `get_transfer_size()` - bytes on wire
- `get_data_size()` - actual data bytes
- `get_parts()`, `get_segments()`, `get_hash()`
- `is_compressed()` → bool

### RNS.Channel
```python
channel = link.get_channel()
channel.register_message_type(MessageClass)
channel.add_message_handler(callback)  # callback(message) → bool
channel.remove_message_handler(callback)
channel.is_ready_to_send()  # bool
channel.send(message)  # MessageBase instance
channel.mdu  # property: max message size
```

**MessageBase (subclass this):**
```python
class MyMessage(RNS.MessageBase):
    MSGTYPE = 0x0101  # 2-byte unique ID (< 0xf000)
    
    def __init__(self, data=None):
        self.data = data
    
    def pack(self) -> bytes:
        return msgpack.packb(self.data)
    
    def unpack(self, raw: bytes):
        self.data = msgpack.unpackb(raw)
```

### RNS.Buffer
**Static factory methods:**
```python
reader = RNS.Buffer.create_reader(stream_id, channel, ready_callback)
writer = RNS.Buffer.create_writer(stream_id, channel)
rw_pair = RNS.Buffer.create_bidirectional_buffer(
    receive_stream_id, send_stream_id, channel, ready_callback
)
```

Returns BufferedReader, BufferedWriter, or BufferedRWPair (standard Python IO).

### RNS.Transport
**Static Methods:**
- `register_announce_handler(handler)` - handler.received_announce(dest_hash, identity, app_data)
- `deregister_announce_handler(handler)`
- `has_path(dest_hash)` → bool
- `hops_to(dest_hash)` → int
- `next_hop(dest_hash)` → bytes
- `next_hop_interface(dest_hash)` → Interface
- `await_path(dest_hash, timeout, on_interface)` → bool (blocks)
- `request_path(dest_hash, on_interface, tag, recursive)`

**Constants:**
- `PATHFINDER_M = 128` - Max hops

---

## EXAMPLE PATTERNS

### 1. Basic Setup
```python
import RNS

# Initialize Reticulum
reticulum = RNS.Reticulum()

# Create identity
identity = RNS.Identity()

# Create destination
destination = RNS.Destination(
    identity,
    RNS.Destination.IN,
    RNS.Destination.SINGLE,
    "myapp", "service"
)
destination.set_proof_strategy(RNS.Destination.PROVE_ALL)
```

### 2. Announce & Discovery
```python
# Server: Announce
destination.announce(app_data=b"my_status")

# Client: Listen for announces
class AnnounceHandler:
    def __init__(self, aspect_filter=None):
        self.aspect_filter = aspect_filter
    
    def received_announce(self, dest_hash, announced_identity, app_data):
        print(f"Discovered: {dest_hash.hex()}")

handler = AnnounceHandler("myapp.service")
RNS.Transport.register_announce_handler(handler)
```

### 3. Packet Send/Receive
```python
# Receiver setup
def packet_callback(data, packet):
    print(f"Received: {data.decode('utf-8')}")
    print(f"RSSI: {packet.rssi}, SNR: {packet.snr}")

destination.set_packet_callback(packet_callback)

# Sender
dest_hash = bytes.fromhex("...")
dest_identity = RNS.Identity.recall(dest_hash)
if dest_identity:
    out_dest = RNS.Destination(
        dest_identity, RNS.Destination.OUT,
        RNS.Destination.SINGLE, "myapp", "service"
    )
    packet = RNS.Packet(out_dest, b"Hello")
    receipt = packet.send()
    receipt.set_delivery_callback(lambda r: print("Delivered!"))
```

### 4. Link Establishment
```python
# Server
def client_connected(link):
    print("Client connected")
    link.set_link_closed_callback(client_disconnected)
    link.set_packet_callback(server_packet_received)

destination.set_link_established_callback(client_connected)

def server_packet_received(message, packet):
    print(f"Received over link: {message.decode('utf-8')}")
    reply = RNS.Packet(packet.link, b"ACK")
    reply.send()

# Client
server_identity = RNS.Identity.recall(dest_hash)
server_dest = RNS.Destination(
    server_identity, RNS.Destination.OUT,
    RNS.Destination.SINGLE, "myapp", "service"
)

def link_established(link):
    print("Link established")
    link.set_packet_callback(client_packet_received)
    packet = RNS.Packet(link, b"Hello server")
    packet.send()

def link_closed(link):
    print(f"Link closed: {link.teardown_reason}")

link = RNS.Link(server_dest)
link.set_link_established_callback(link_established)
link.set_link_closed_callback(link_closed)
```

### 5. Request/Response
```python
# Server: Register handler
def my_handler(path, data, request_id, link_id, remote_identity, requested_at):
    return b"response_data"

destination.register_request_handler(
    "/api/data",
    response_generator=my_handler,
    allow=RNS.Destination.ALLOW_ALL
)

# Client: Make request
def got_response(receipt):
    print(f"Response: {receipt.response}")

def request_failed(receipt):
    print("Request failed")

link.request(
    "/api/data",
    data=b"query",
    response_callback=got_response,
    failed_callback=request_failed
)
```

### 6. Channel Messaging
```python
# Define message type
class StatusMessage(RNS.MessageBase):
    MSGTYPE = 0x0101
    
    def __init__(self, status=None):
        self.status = status
        self.timestamp = time.time()
    
    def pack(self):
        return msgpack.packb((self.status, self.timestamp))
    
    def unpack(self, raw):
        self.status, self.timestamp = msgpack.unpackb(raw)

# Server
channel = link.get_channel()
channel.register_message_type(StatusMessage)

def message_received(message):
    if isinstance(message, StatusMessage):
        print(f"Status: {message.status} at {message.timestamp}")
        return True

channel.add_message_handler(message_received)

# Client
channel = link.get_channel()
channel.register_message_type(StatusMessage)
msg = StatusMessage("online")
channel.send(msg)
```

### 7. Buffer Streaming
```python
# Server
def server_buffer_ready(ready_bytes):
    data = buffer.read(ready_bytes)
    print(f"Received: {data.decode('utf-8')}")
    buffer.write(b"ACK\n")
    buffer.flush()

channel = link.get_channel()
buffer = RNS.Buffer.create_bidirectional_buffer(0, 0, channel, server_buffer_ready)

# Client
def client_buffer_ready(ready_bytes):
    data = buffer.read(ready_bytes)
    print(f"Received: {data.decode('utf-8')}")

channel = link.get_channel()
buffer = RNS.Buffer.create_bidirectional_buffer(0, 0, channel, client_buffer_ready)

buffer.write(b"Hello\n")
buffer.flush()
```

### 8. Resource Transfer
```python
# Server: Auto-receive
def resource_concluded(resource):
    if resource.status == RNS.Resource.COMPLETE:
        print(f"Received {resource.total_size} bytes")
        with open("received_file", "wb") as f:
            f.write(resource.data.read())

link.set_resource_strategy(RNS.Link.ACCEPT_ALL)
link.set_resource_concluded_callback(resource_concluded)

# Client: Send file
with open("myfile.dat", "rb") as f:
    resource = RNS.Resource(f, link)
```

---

## INTERFACE CONFIGURATION

### Config File Location
`~/.reticulum/config`

### Common Options (all interfaces)
```ini
enabled = yes|no
mode = full|gateway|access_point|roaming|boundary
outgoing = yes|no
network_name = string        # Virtual network segmentation
passphrase = string          # Authentication
ifac_size = 8-512           # bits, IFAC length
announce_cap = 1-100        # % bandwidth for announces
bitrate = N                 # bits/sec (if not auto-detected)
```

### AutoInterface (Local Ethernet/WiFi)
```ini
[[Local Network]]
type = AutoInterface
enabled = yes
group_id = reticulum
discovery_scope = link      # link|admin|site|organisation|global
devices = wlan0,eth1        # Specific devices
ignored_devices = tun0      # Exclude devices
```

### TCP Server
```ini
[[TCP Server]]
type = TCPServerInterface
enabled = yes
listen_ip = 0.0.0.0
listen_port = 4242
i2p_tunneled = no
```

### TCP Client
```ini
[[TCP Client]]
type = TCPClientInterface
enabled = yes
target_host = example.com
target_port = 4242
kiss_framing = no           # For external TNCs
i2p_tunneled = no
```

### I2P
```ini
[[I2P]]
type = I2PInterface
enabled = yes
connectable = yes
peers = base32addr.b32.i2p,another.b32.i2p
```

### RNode LoRa
```ini
[[RNode]]
type = RNodeInterface
enabled = yes
port = /dev/ttyUSB0         # or tcp://192.168.1.5 or ble://
frequency = 867200000       # Hz
bandwidth = 125000          # Hz
txpower = 7                 # dBm
spreadingfactor = 8         # 7-12
codingrate = 5              # 5-8
flow_control = no
```

### Serial/KISS
```ini
[[Serial]]
type = SerialInterface
enabled = yes
port = /dev/ttyUSB0
speed = 115200
databits = 8
parity = none
stopbits = 1
```

### Interface Modes
- **full**: All functionality (default)
- **gateway**: Resolves unknown paths for clients on interface
- **access_point**: Quiet until used, short path expiry
- **roaming**: For mobile nodes
- **boundary**: Connects significantly different network segments

---

## PROTOCOL DETAILS

### Wire Format
```
[HEADER 2B] [IFAC 1-64B] [ADDRESSES 16/32B] [CONTEXT 1B] [DATA 0-465B]

Header byte 1: [IFAC flag][Header type][Context][Propagation][Dest type][Packet type]
Header byte 2: Hops

Header types: type1=1 addr, type2=2 addrs
Propagation: broadcast(0), transport(1)
Dest types: single(00), group(01), plain(10), link(11)
Packet types: data(00), announce(01), link_request(10), proof(11)
```

### Cryptography
- **Identity**: X25519 encryption + Ed25519 signing (512-bit total)
- **Packet encryption**: Ephemeral ECDH → AES-256-CBC + HMAC-SHA256
- **Link encryption**: Per-link ephemeral keys (forward secrecy)
- **Ratchets**: Optional per-packet forward secrecy for single destinations
- **Hashing**: SHA-256, truncated to 128 bits for addresses

### Announce Propagation
Announces retransmitted by transport nodes with rules:
- Max retransmits: `m+1` (default m=128, so 129 hops max)
- Bandwidth allocation: Default 2% per interface
- Priority: Lower hop count = higher priority
- Deduplication: Exact announces ignored
- Rate limiting: Excessive announcers deprioritized

### Path Resolution
1. Destination sends announce (signed, includes pubkey)
2. Transport nodes forward, remember path
3. Client requests path if unknown: `Transport.request_path(dest_hash)`
4. Transport responds with cached path
5. Packets routed hop-by-hop using next_hop lookups

---

## QUICK START

```python
import RNS

# 1. Initialize
rns = RNS.Reticulum()

# 2. Create identity & destination
identity = RNS.Identity()
dest = RNS.Destination(identity, RNS.Destination.IN, 
                        RNS.Destination.SINGLE, "myapp", "service")

# 3. Set up callbacks
dest.set_packet_callback(lambda data, pkt: print(f"Got: {data}"))
dest.set_link_established_callback(lambda link: print("Link up"))

# 4. Announce
dest.announce()

# 5. Send packet to remote
remote_hash = bytes.fromhex("...")
if RNS.Transport.has_path(remote_hash):
    remote_id = RNS.Identity.recall(remote_hash)
    remote_dest = RNS.Destination(remote_id, RNS.Destination.OUT,
                                   RNS.Destination.SINGLE, "myapp", "service")
    packet = RNS.Packet(remote_dest, b"Hello")
    receipt = packet.send()
else:
    RNS.Transport.request_path(remote_hash)
```

---

## USEFUL PATTERNS

### Wait for Path
```python
import time
RNS.Transport.request_path(dest_hash)
while not RNS.Transport.has_path(dest_hash):
    time.sleep(0.1)
```

### Reliable Link Communication
```python
# Links provide automatic retries and ordering
link = RNS.Link(destination)
# Wait for establishment...
packet = RNS.Packet(link, data)
packet.send()  # Automatically retried if lost
```

### Large Data Transfer
```python
# Use Resource for files/large data
with open("large_file.bin", "rb") as f:
    resource = RNS.Resource(f, link, 
                           callback=lambda r: print(f"Done: {r.status}"))
```

### Identity Persistence
```python
# Save identity
identity.to_file("~/.myapp/identity")

# Load identity
identity = RNS.Identity.from_file("~/.myapp/identity")
```

### Announce with App Data
```python
# Include status/metadata in announce
status_data = {"version": "1.0", "capabilities": ["chat", "files"]}
dest.announce(app_data=msgpack.packb(status_data))

# Receiver gets it in announce handler
def received_announce(dest_hash, identity, app_data):
    status = msgpack.unpackb(app_data)
```

---

## UTILITIES

- `rnsd` - Run as daemon
- `rnstatus` - View interface status
- `rnpath` - Path management
- `rnprobe` - Test connectivity
- `rncp` - File transfer
- `rnx` - Remote execution
- `rnid` - Identity management

Example:
```bash
rnsd --config /path/to/config  # Start daemon
rnstatus                       # Check status
rnpath abc123def456            # Check path to destination
rnprobe example.service abc123def456  # Probe destination
```

---

**Full manual**: 217 pages at github.com/markqvist/Reticulum
**This reference**: Essential dev info compressed to ~10%
