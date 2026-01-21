# Tailscale Web GUI Integration

## Overview

This document describes the implementation plan to replace the rpi-connect remote access functionality with Tailscale integration in the Nucleus OS web GUI. The implementation leverages Tailscale's native CLI commands for profile management and status reporting.

## Requirements

- Replace `/remote` page UI to show Tailscale controls instead of rpi-connect
- Display current Tailscale status: connected/disconnected, IP address, tailnet name
- Provide on/off toggle for Tailscale connection
- Allow switching between pre-configured tailnet profiles
- All functionality must use verified Tailscale CLI commands (no made-up APIs)

## Verified Tailscale CLI Commands

Based on system verification, these commands are available:

### Connection Management
```bash
# Connect to Tailscale
tailscale up

# Disconnect from Tailscale
tailscale down
```

### Status and Information
```bash
# Get status in JSON format (includes state, peer info, tailnet)
tailscale status --json

# Get only the IPv4 address of current machine
tailscale ip -4

# Get only the IPv6 address of current machine
tailscale ip -6
```

### Profile/Account Switching
```bash
# List all logged-in Tailscale accounts/profiles
tailscale switch --list

# Switch to a specific profile by ID, tailnet name, or display name
tailscale switch <id>
```

## Implementation Plan

### 1. Backend API Endpoints (app.py)

#### GET `/api/tailscale/status`
**Purpose**: Get current Tailscale connection state, IP, and tailnet information

**Implementation**:
```python
subprocess.run(['tailscale', 'status', '--json'], capture_output=True, text=True)
```

**Returns JSON**:
```json
{
  "connected": true,
  "ip": "100.x.x.x",
  "tailnet": "example.tailnet.ts.net",
  "hostname": "0002-nucleus",
  "status": "Running"
}
```

**Error handling**: If tailscale is not running or returns error, return `connected: false`

---

#### POST `/api/tailscale/up`
**Purpose**: Turn on Tailscale connection

**Implementation**:
```python
subprocess.run(['sudo', 'tailscale', 'up'], capture_output=True, text=True, timeout=30)
```

**Returns JSON**:
```json
{
  "success": true,
  "message": "Tailscale connected"
}
```

**Notes**: 
- May require sudo depending on system configuration
- Command may take several seconds to complete
- Should verify status after command completes

---

#### POST `/api/tailscale/down`
**Purpose**: Turn off Tailscale connection

**Implementation**:
```python
subprocess.run(['sudo', 'tailscale', 'down'], capture_output=True, text=True, timeout=10)
```

**Returns JSON**:
```json
{
  "success": true,
  "message": "Tailscale disconnected"
}
```

---

#### GET `/api/tailscale/profiles`
**Purpose**: List available Tailscale profiles/accounts for switching

**Implementation**:
```python
subprocess.run(['tailscale', 'switch', '--list'], capture_output=True, text=True)
```

**Parse output** (example format):
```
  ID: 123456
  Account: user@example.com
  Server: controlplane.tailscale.com

* ID: 789012
  Account: user@company.com
  Server: controlplane.tailscale.com
```

**Returns JSON**:
```json
{
  "profiles": [
    {
      "id": "123456",
      "account": "user@example.com",
      "current": false
    },
    {
      "id": "789012",
      "account": "user@company.com",
      "current": true
    }
  ]
}
```

**Notes**: 
- Lines starting with `*` indicate the currently active profile
- Parse each profile block to extract ID and Account fields

---

#### POST `/api/tailscale/switch`
**Purpose**: Switch to a different Tailscale profile

**Request body**:
```json
{
  "profile_id": "123456"
}
```

**Implementation**:
```python
profile_id = request.json.get('profile_id')
subprocess.run(['sudo', 'tailscale', 'switch', profile_id], capture_output=True, text=True, timeout=30)
```

**Returns JSON**:
```json
{
  "success": true,
  "message": "Switched to profile 123456"
}
```

**Notes**:
- After switching, the connection should automatically establish with the new tailnet
- Should verify new status after switch completes

---

### 2. Frontend UI (templates/remote.html)

#### Layout Structure

```
┌─────────────────────────────────────┐
│  Remote Access (Tailscale)          │
├─────────────────────────────────────┤
│  Status: Connected                   │
│  Tailscale IP: 100.x.x.x            │
│  Tailnet: example.tailnet.ts.net    │
├─────────────────────────────────────┤
│  [Turn On]  [Turn Off]              │
├─────────────────────────────────────┤
│  Switch Tailnet:                     │
│  ┌─────────────────────────────┐   │
│  │ user@example.com (current) ▼│   │
│  └─────────────────────────────┘   │
│           [Switch]                   │
└─────────────────────────────────────┘
```

#### UI Components

**Status Display**:
- Show connection state (Connected/Disconnected)
- Display Tailscale IP when connected
- Display current tailnet name

**Control Buttons**:
- "Turn On" button → calls `/api/tailscale/up`
- "Turn Off" button → calls `/api/tailscale/down`
- Disable buttons during operation to prevent duplicate requests

**Profile Selector**:
- Dropdown populated from `/api/tailscale/profiles`
- Show account email/name for each profile
- Mark current profile in dropdown
- "Switch" button → calls `/api/tailscale/switch` with selected profile ID

#### JavaScript Behavior

1. **On page load**: 
   - Call `GET /api/tailscale/status` to populate status
   - Call `GET /api/tailscale/profiles` to populate dropdown

2. **Status refresh**:
   - Auto-refresh status every 10 seconds
   - Refresh immediately after turn on/off/switch operations

3. **Button handlers**:
   - Disable button during operation
   - Show loading indicator
   - Display success/error message
   - Re-enable button after completion

---

### 3. Code Changes Required

#### Files to Modify:

1. **opt/nucleus/web/app.py**:
   - Remove `/api/rpi-connect/*` endpoints (lines 731-797)
   - Add new `/api/tailscale/*` endpoints as described above

2. **opt/nucleus/web/templates/remote.html**:
   - Replace entire UI with Tailscale-focused layout
   - Update JavaScript to call new API endpoints
   - Keep navigation header unchanged

#### Files to Remove (cleanup):
- No files need to be removed
- Old rpi-connect endpoints can be removed or commented out

---

### 4. Sudo Permissions

The following commands may require sudo access:
- `tailscale up`
- `tailscale down`
- `tailscale switch`

**Recommended sudoers entry** (`/etc/sudoers.d/tailscale-web`):
```
natak ALL=(ALL) NOPASSWD: /usr/bin/tailscale up
natak ALL=(ALL) NOPASSWD: /usr/bin/tailscale down
natak ALL=(ALL) NOPASSWD: /usr/bin/tailscale switch*
```

---

### 5. Testing Plan

1. **Connection control**:
   - Start with Tailscale off → turn on → verify status shows connected
   - Turn off → verify status shows disconnected
   - Check that Tailscale IP appears when connected

2. **Profile switching**:
   - Verify dropdown lists all logged-in profiles
   - Switch to different profile → verify tailnet changes
   - Confirm current profile marked correctly in dropdown

3. **Error handling**:
   - Test with no profiles logged in
   - Test switching while disconnected
   - Verify error messages display properly

4. **UI responsiveness**:
   - Verify auto-refresh works
   - Check button disable/enable during operations
   - Test on mobile viewport

---

### 6. Future Enhancements

Potential additions for future versions:

1. **Exit node control**: Add toggle for exit node mode
2. **Network routes**: Display advertised routes
3. **Peer list**: Show other devices on current tailnet
4. **QR code**: Generate connection QR for mobile devices
5. **Auth key setup**: UI to add new profiles with auth keys

---

## Implementation Order

1. ✅ Document Tailscale CLI commands (this file)
2. Create new backend API endpoints in app.py
3. Update remote.html UI and JavaScript
4. Configure sudo permissions if needed
5. Test all functionality
6. Remove/comment out old rpi-connect code

---

## Notes

- All Tailscale commands verified on system version (see help output in planning)
- Implementation uses only official Tailscale CLI, no third-party libraries
- Design maintains consistency with existing Nucleus OS web GUI styling
- Profile switching assumes users have already authenticated via `tailscale login` on the device
