# UV-Pro Link Transfer Failure

## Issue Summary
- Packet transfer works fine with current UV-Pro pairing method
- Larger file transfers via link fail, killing the connection
- Requires reset after failure

## Observed Behavior
- File transfer consistently fails at 42.7% sent
- Occurs at both 1200 and 9600 baud speeds

## Log Messages

### Sending Node
```
[2026-01-19 19:18:51] [Debug] Outbound interface doesn't support MTU autoconfiguration, disabling link MTU upgrade
[2026-01-19 19:18:55] [Extra] Link request proof validated for transport via TCPInterface[Client on LAN TCP Server/10.20.2.56:42958]
```

### Receiving Node
```
[2026-01-19 19:18:52] [Extra] Link request proof validated for transport via KISSInterface[UV-RF]
[2026-01-19 19:20:39] [Debug] Path request for <b6fe4c38c9ac8c0480cea10071e00da3> on TCPInterface[Client on LAN TCP Server/10.20.3.23:48014]
[2026-01-19 19:20:39] [Debug] Answering path request for <b6fe4c38c9ac8c0480cea10071e00da3> on TCPInterface[Client on LAN TCP Server/10.20.3.23:48014], path is known
```

## Status
- Under investigation
- Next test: 115200 baud
