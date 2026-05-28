# UFW Rules for TAKServer on Nucleus

```bash
# Mesh backbone (required — without this, Babel routing breaks)
sudo ufw allow in on wlan1

# SSH
sudo ufw allow 22/tcp

# TAKServer
sudo ufw allow 8089/tcp
sudo ufw allow 8443/tcp
sudo ufw allow 8554/tcp

# Nucleus Web UI
sudo ufw allow 5000/tcp

# OpenDHT
sudo ufw allow 4222/tcp
sudo ufw allow 4242/tcp
sudo ufw allow 4243/tcp

sudo ufw enable
```
