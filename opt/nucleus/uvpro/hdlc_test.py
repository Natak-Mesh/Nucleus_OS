#!/usr/bin/env python3
"""
Test script to send HDLC-framed data to UV-Pro radio on channel 2
Based on Wireshark capture analysis
"""

import serial
import time
import sys

def send_hdlc_frame(port, data):
    """
    Send an HDLC frame with BSS header
    Frame format: 7e [BSS header] [data] 7e
    """
    # HDLC frame delimiter
    frame_start = b'\x7e'
    frame_end = b'\x7e'
    
    # BSS header from capture: 00 9c 71 12
    bss_header = b'\x00\x9c\x71\x12'
    
    # Build complete frame
    frame = frame_start + bss_header + data + frame_end
    
    print(f"Sending {len(frame)} bytes:")
    print(' '.join(f'{b:02x}' for b in frame))
    
    port.write(frame)
    port.flush()
    print("Frame sent")

def main():
    # Connect to /dev/rfcomm0 (must be bound to channel 2 first)
    try:
        print("Opening /dev/rfcomm0...")
        ser = serial.Serial('/dev/rfcomm0', 115200, timeout=1)
        print(f"Port open: {ser.is_open}")
        print(f"Port: {ser.name}")
        
        time.sleep(0.5)
        
        # Send a test frame with simple data
        test_data = b'TEST123'
        print(f"\nSending test frame with data: {test_data}")
        send_hdlc_frame(ser, test_data)
        
        time.sleep(1)
        
        # Check for any response
        if ser.in_waiting > 0:
            response = ser.read(ser.in_waiting)
            print(f"\nReceived {len(response)} bytes:")
            print(' '.join(f'{b:02x}' for b in response))
        else:
            print("\nNo response received")
        
        input("\nPress Enter to close...")
        
        ser.close()
        print("Port closed")
        
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
