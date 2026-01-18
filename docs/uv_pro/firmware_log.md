V0.9.0 — December 17, 2025
Fixes
Fixed Mic-e Parsing Errors Caused by Overflows
V0.8.15 — December 03, 2025
New
GPWPL Location Reporting: Adds support for reporting received position reports using GPWPL. (Requires enabling “GPWPL Upload” under: General Settings → Data Mode → GPWPL Upload.Signaling format selector in Signaling Settings (choose BSS or APRS)).
Improvements
Satellite Mode Enhancements: Now displays satellite name, azimuth, elevation, orbital altitude, range to satellite, and pass countdown timer on-screen.
Keypad Lock Behavior: The radio now restores the previous keypad lock state after powering back on. (When the keypad is locked, volume adjustment via the potentiometer is disabled to prevent accidental changes.)
Battery Indicator Optimization: Battery percentage display has been smoothed to reduce rapid or drastic fluctuations over short periods.
Mute Status Indicators: The mute icon now distinguishes between different mute conditions (e.g., manual mute, squelch, other system mutes) for clearer status feedback.
Fixes
KISS / TNC  Data: Supports sending KISS data packets when the squelch (SQ) is open, improving compatibility with external packet/APRS software.
V0.8.12 — October 09, 2025
New
Signaling format selector in Signaling Settings (choose BSS or APRS).
Custom Location override for cases without GPS or when a fixed position is preferred.
Improvements
BK4819 RF driver hardening: added host-write error detection and automatic recovery on PLL loss-of-lock.
Fixes
APRS Mic-E: default icon set now applies when no icon is configured in the app, preventing malformed/incorrect packets.
Audio Relay: resolved occasional silent transmit due to audio re-sampling.
V0.8.9-1 — August 07, 2025
New
Support for Satellite Mode
Added Alarm Volume option in Sound Settings (Adjust NOAA Alarm Volume)
Fixes
Fixed the issue where announcing the current channel would cause exiting VFO mode
Other
Frequency mode transmit power supports local control
V0.8.8 — June 23, 2025
New
Smart Beaconing™ (adaptive APRS beacon intervals)
Mic-E APRS frames support
On-radio GPS sharing (radio can contribute position to the BTECH app)
Quicker volume overlay (auto-hide after ~1s)
Improvements
Reliable network audio; corrected rare transmit/receive channel mismatch
V0.8.4 — April 28, 2025
New
Added support for Busy Channel Lockout (BCL) to prevent message transmission on busy channels.
Added “VFO Step” configuration option in Radio Settings.
Improvements
Channel editor now supports BCL and modulation mode.
Optimized display colors and font for readability.
Reduced extra wait time for 1050 Hz tone check (BK4819) from 250 ms to 125 ms.
Consistent SQL value for NOAA channels to minimize unintended squelch openings.
Channel switching interface can jump directly to VFO channels.
DTMF input interface now shows text.
“Frequency Rapid Scan” supports fine frequency adjust; results save to VFO.
Fixes
Fixed Audio Relay abnormal operation.
Fixed premature exit/timeout behavior in NOAA alert mode around 1050 Hz tone detection.
Fixed incorrect scan results when scanning frequencies alongside channels using frequency-offset mode.
Resolved additional audio relay issues.
V0.8.1 — February 26, 2025
Improvements
Bluetooth headset now correctly disables PTT release prompt tone when system tones are off.
Channel groups: switch directly from main screen via Right Soft Key.
Improved RX performance.
New
APRS destination address updated to “APBTUV.”
V0.8.0 — January 22, 2025
Large firmware update; a Factory Reset is recommended after updating.

Bluetooth & VOX
Improved stability with third-party Bluetooth accessories.
Added VOX support for Bluetooth headsets.
Optional routing to use the radio speaker/mic while a Bluetooth headset remains paired (selectable in Sound Settings).
On-Radio Menu
Audio Relay settings moved into radio menu.
VOX settings added.
KISS & APRS
Stability improvements and ACK handling fixes for onboard APRS.
SMS and APRS ACK reliability improvements.
KISS protocol stability and message handling improved.
ACKs now sent via the receiving channel.
Added channel save function to store current channel during scanning.
BS-22 Accessory
Eliminated squelched-state hiss through the BS-22 microphone.
V0.7.11 — December 11, 2024
New
KISS Bluetooth Mode for broader device/app compatibility; simple, standards-based interface.
New KISS UI menu on radio.
Improvements
Enhanced Bluetooth stability, buffering, and error correction.
Improved data throughput.
Fixes
Resolved intermittent app-pairing issues.
V0.7.8 — September 25, 2024
Improvements
Better dynamic sensitivity at lowest squelch settings for stronger receive—especially helpful for APRS.
New programmable button functions: Mute Switch, Freq Sync Rapid Scan.
If no signaling ID is set, the radio now displays the Call Sign.
Message list shows the call sign when the sender doesn’t provide an ID.
Audio Relay Switch added in Radio Settings.
