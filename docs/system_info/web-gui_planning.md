#       ..        .....        ...       
#       ....     ......       ....      
#       .......... ...       .....       
#       ........    ..      ......       
#       ......      ..     .......       
#       .....       ...  .........       
#       ....        .....     ....      
#       ...         ....        ..   

#############################################
#        N A T A K   -   Nucleus OS v2.0    #
#                                           #
#         Web Interface Planning            #
#############################################

## File Structure

Following Linux Filesystem Hierarchy Standard (FHS) and Flask conventions:

```
/opt/nucleus/web/                      # Flask web application
├── app.py                             # Main Flask application file
├── static/                            # Static assets (CSS, JS, images)
│   ├── css/
│   │   └── style.css
│   ├── js/
│   │   └── main.js
│   └── images/
│       └── NatakMeshsecondary-overlay.png  (already exists)
└── templates/                         # HTML Jinja2 templates
    ├── base.html                      # Base template with common elements
    ├── index.html                     # Dashboard/home page
    └── ...                            # Additional page templates

/etc/nucleus/                          # Configuration files (already exists)
└── mesh.conf                          # Mesh configuration

/opt/nucleus/bin/                      # Shell scripts (already exists)
├── config_generation.sh
├── mesh-start.sh
└── eth0-mode.sh
```

## Mesh Connection Monitoring

### Babeld Configuration
Enable monitoring interface in `/etc/babeld.conf`:
```
local-port 33123
```

### Data Sources for Mesh Connections

**1. Babeld Monitoring Interface**
```bash
echo "dump" | nc localhost 33123
```
Provides:
- Neighbor link-local IPv6 addresses (e.g., `fe80::11`)
- Link quality metrics: `cost`, `reach`, `rxcost`, `txcost`
- Interface information (wlan1)
- Router IDs
- Route information

**2. IPv4 Neighbor Cache**
```bash
ip neigh show dev wlan1
```
Provides: IPv4 addresses of neighbors on wlan1 interface

### Correlation Logic
1. Query babeld for neighbors on wlan1 with link metrics
2. Query IPv4 neighbor cache for addresses on wlan1
3. Match neighbors by interface (both on wlan1)
4. Result: Display IPv4 addresses with babeld's link quality metrics

**Note:** IPv6 neighbor cache not used since kernel doesn't maintain fe80 neighbors for wlan1. Simplified approach matches by interface instead of MAC address.

### Web Interface Implementation
- Connect to babeld's monitoring port (localhost:33123)
- Parse neighbor data from `dump` command
- Query system neighbor caches to resolve IPv4 addresses
- Display: Node IP, Link Quality/Cost, Connection Status
- Use `monitor` command for real-time updates
