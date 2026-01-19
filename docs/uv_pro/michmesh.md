Btech UV-Pro and similar radios
Thanks to HamRadioTech for figuring this out for us. This method assumes using linux. If someone wants to test it out on other platforms and get me a write up, I'll gladly post it.

On the radion enable KISS TNC under menu -> General Settings -> KISS TNC -> Enable KISS TNC
Make sure the app on your phone is not connected to the radio. I removed it from my BT pairings just to make sure it didnt try as it will boot your KISS comms.
Setup the radio's bluetooth connection.
In a terminal, run bluetoothctl.
Once in the bluetoothctl shell, run scan on
Enable pairing on the radio by going to menu -> Pairing
You should see your radio listed in the bluetoothctl shell. Once you do, run scan off
Copy the bluetooth mac address
run pair 38:D2:00:AA:BB:CC, pasting your mac address instead of 38:D2:00:AA:BB:CC
run trust 38:D2:00:AA:BB:CC, again pasting your mac address instead of 38:D2:00:AA:BB:CC
run sudo rfcomm bind /dev/rfcomm0 38:D2:00:AA:BB:CC 1 to create the /dev/rfcomm0 device. If you need to delete it and recreate, the delete command is sudo rfcomm release 0
ctrl-d will exit out of the bluetoothctl shell. ctrl-d again will exit out of your terminal.
Restart your radio. Delete the device with sudo rfcomm release 0, once your radio is back up, re-create the device. (This part might be cargo-culting, but it's what I had to do to get it to work the first time)
edit your ~/.reticulum/config file and add the following to the [interfaces] section:
  [[uv-pro]]
    type = KISSInterface 
    interface_enabled = true
    port = /dev/rfcomm0
    speed = 1200
    databits = 8
    parity = none
    stopbits = 1
    flow_control = false
    preamble = 150 
    txtail = 10
    persistence = 200
    slottime = 20

Save and restart rnsd - If you are using the systemd config above, you can do this with sudo systemctl restart rnsd. You will need to restart rnsd whenever any changes are made to the rns config.
If the bluetooth connection is lost, you may need to restart the radio, recreate the device, and restart rns. I made this little script to do so:
#!/bin/bash
sudo sudo rfcomm release 0
sudo rfcomm bind /dev/rfcomm0 38:D2:00:AA:BB:CC 1 ### change the mac address to match your radio
sudo systemctl restart rnsd

