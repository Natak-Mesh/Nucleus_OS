# Jami configuration with OpenDHT
This is going to be set on an example node 0004 with the 
bootstrap ip at 10.20.4.1:4222 and 
DHT proxy of 10.20.4.1:8000

that information can be found in the opendht section of the web ui accessed at <node IP>:5000

## Settings to apply in Jami app on your EUD
If any settings are not specifically called out, leave as default
account settings> advanced
- bootstrap: 10.20.4.1:8000
- 'Use DHT Proxy': enabled
- DHT proxy address: 10.20.4.1:8000
- 'use DHT proxy list': disabled
- enable local peer discovery: enabled
- enable UPnp: disabled
- use Turn: disabled