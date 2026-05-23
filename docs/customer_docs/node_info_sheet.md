<div style="text-align: center; display: flex; flex-direction: column; justify-content: center; align-items: center; min-height: 80vh;">
<img src="NatakMeshsecondary-overlay@2x.png" alt="Natak Mesh" style="max-width: 500px;">
<h1 style="margin-top: 50px; font-size: 2.5em;">Nucleus Configuration Information</h1>
<p style="font-size: 1.5em; margin-top: 20px;">natakmesh.com</p>
</div>

<div style="page-break-after: always;"></div>

## Node Information

**Serial Number:** _______________

**Node IP:** _______________

**AP Name:** `<node S/N>-nucleus`

**AP Password:** `52235223`

**Web UI:** `http://<node IP>:5000`

---

## SSH Credentials

**Hostname:** `<node S/N>-nucleus`

**Username:** `natak`

**Password:** `52235223`

> Example: `ssh natak@0013-nucleus.local`

---

## Meshtastic

**Pairing Password:** `123456`

Radios are configured as follows:

| Setting | Value |
|---|---|
| Long Name | `<node S/N> - <radio MAC>` |
| Short Name | `<node S/N>` |
| Preset | SHORT_FAST |
| Role | TAK |
| Rebroadcast | Local Only |
| Phone Location | Enabled (provide location to mesh) |

---

## OpenTAKServer

*If installed on this node:*

Accessible through the Nucleus Web UI or from a connected device at:

`http://<node IP>:8080`

| Credential | Value |
|---|---|
| Username | `administrator` |
| Password | `password` |
