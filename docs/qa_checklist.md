<div style="text-align: center; display: flex; flex-direction: column; justify-content: center; align-items: center; min-height: 80vh;">
<img src="NatakMeshsecondary-overlay@2x.png" alt="Natak Mesh" style="max-width: 500px;">
<h1 style="margin-top: 50px; font-size: 2.5em;">QA Checklist</h1>
<p style="font-size: 1.5em; margin-top: 20px;">natakmesh.com</p>
</div>

<div style="page-break-after: always;"></div>

**Unit Serial Number:** _______________  
**Tested By:** _______________  
**Date:** _______________  

---

☐ Git repo clones and all required packages installed/deployed  
☐ Config file updated to match node S/N and openDHT peers  
☐ OpenTAKserver installed (if selected)  
☐ Config files written correctly  
☐ Reboot  

---

### Post Boot

☐ AP up and able to be connected to  
☐ Web UI functional  
☐ Wi-Fi mesh peers visible  
☐ LoRa radio name set correctly  
☐ LoRa radios set on shared channel  
☐ Tailscale login to natak tailnet  
☐ Confirm web UI Meshtastic tab can operate LoRa radio via serial and return it  
☐ Confirm Reticulum instance is up and functional  
☐ Confirm openDHT server is running and peered  
☐ If running OpenTAKserver, confirm access to web UI  

---

### Integration Tests

☐ Test ATAK position, direct and group message, picture and POI marker  
☐ Test Meshtastic via app and serial  
☐ Test Reticulum text and picture  
☐ Test Jami text, voice and video  
☐ Confirm node shows on tailnet monitor  
