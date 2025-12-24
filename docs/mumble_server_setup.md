# Mumble Server Setup for Mesh Voice

## Install

```bash
sudo apt update
sudo apt install mumble-server
```

## Configure

Edit `/etc/mumble-server.ini`:

```ini
# Bind to br-lan interface
host=10.20.12.1

# Server password (optional)
serverpassword=your_password_here

# Bandwidth (lower for mesh reliability)
bandwidth=72000

# Maximum users
users=20

# Server port (default)
port=64738
```

## Firewall

```bash
sudo ufw allow 64738/tcp
sudo ufw allow 64738/udp
sudo ufw reload
```

## Service

```bash
sudo systemctl enable mumble-server
sudo systemctl start mumble-server
sudo systemctl status mumble-server
```

## Verify

```bash
# Check it's listening
sudo netstat -tulpn | grep 64738
```

Clients connect to: `10.20.12.1:64738` (or the br-lan IP of the node running mumble-server)
