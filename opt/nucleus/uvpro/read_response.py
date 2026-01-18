#!/usr/bin/env python3
"""
Read and display what the UV-Pro radio is sending back via channel 2
"""

import serial
import time
import sys

port = '/dev/rfcomm0'
baud = 9600

print(f"Opening {port} at {baud} baud...")
ser = serial.Serial(port, baud, timeout=1)

print(f"Port open: {ser.is_open}")
print(f"Waiting for data from radio...")
print()

try:
    # Read whatever is already in the buffer
    if ser.in_waiting > 0:
        data = ser.read(ser.in_waiting)
        print(f"Initial buffer ({len(data)} bytes):")
        print(f"  Hex: {data.hex()}")
        print(f"  ASCII (printable): {repr(data)}")
        print()
    
    # Send test data and see response
    print("Sending test message...")
    ser.write(b"HELLO\r\n")
    ser.flush()
    
    time.sleep(0.5)
    
    if ser.in_waiting > 0:
        data = ser.read(ser.in_waiting)
        print(f"Response ({len(data)} bytes):")
        print(f"  Hex: {data.hex()}")
        print(f"  ASCII (printable): {repr(data)}")
        print()
    else:
        print("No response received")
    
    print("\nListening for continuous data (Ctrl+C to stop)...")
    while True:
        if ser.in_waiting > 0:
            data = ser.read(ser.in_waiting)
            print(f"[{time.strftime('%H:%M:%S')}] RX ({len(data)} bytes): {data.hex()} | {repr(data)}")
        time.sleep(0.1)
        
except KeyboardInterrupt:
    print("\nStopped")
finally:
    ser.close()
