#!/usr/bin/env python3
"""
serial_test.py - UV-Pro TNC Serial Communication Test

Test raw serial communication with UV-Pro TNC over Bluetooth.
"""

import serial
import sys
import time
import argparse
from datetime import datetime

def timestamp():
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]

def send_mode(port, baudrate, interval=1.0):
    """Send test data periodically"""
    print(f"[{timestamp()}] Opening {port} at {baudrate} baud")
    ser = serial.Serial(port, baudrate, timeout=1, rtscts=False, dsrdtr=False)
    print(f"[{timestamp()}] Port open: {ser.is_open}")
    print(f"[{timestamp()}] RTS: {ser.rts}, DTR: {ser.dtr}, CTS: {ser.cts}, DSR: {ser.dsr}")
    
    # Try toggling DTR/RTS
    ser.dtr = True
    ser.rts = True
    time.sleep(0.1)
    
    counter = 0
    try:
        while True:
            message = f"TEST_{counter:04d}\n"
            ser.write(message.encode())
            ser.flush()
            print(f"[{timestamp()}] TX: {message.strip()} ({len(message)} bytes)")
            counter += 1
            time.sleep(interval)
    except KeyboardInterrupt:
        print(f"\n[{timestamp()}] Stopped")
    finally:
        ser.close()

def receive_mode(port, baudrate):
    """Listen for incoming data"""
    print(f"[{timestamp()}] Opening {port} at {baudrate} baud")
    ser = serial.Serial(port, baudrate, timeout=1)
    print(f"[{timestamp()}] Listening for data... (Ctrl+C to stop)")
    
    try:
        while True:
            if ser.in_waiting > 0:
                data = ser.read(ser.in_waiting)
                print(f"[{timestamp()}] RX ({len(data)} bytes): {data}")
            time.sleep(0.1)
    except KeyboardInterrupt:
        print(f"\n[{timestamp()}] Stopped")
    finally:
        ser.close()

def interactive_mode(port, baudrate):
    """Send and receive simultaneously"""
    print(f"[{timestamp()}] Opening {port} at {baudrate} baud")
    ser = serial.Serial(port, baudrate, timeout=1)
    print(f"[{timestamp()}] Interactive mode - type messages (Ctrl+C to stop)")
    print("TX shows sent data, RX shows received data")
    print()
    
    import threading
    
    def read_thread():
        while True:
            if ser.in_waiting > 0:
                data = ser.read(ser.in_waiting)
                print(f"[{timestamp()}] RX: {data}")
    
    reader = threading.Thread(target=read_thread, daemon=True)
    reader.start()
    
    try:
        while True:
            msg = input()
            ser.write((msg + "\n").encode())
            print(f"[{timestamp()}] TX: {msg}")
    except (KeyboardInterrupt, EOFError):
        print(f"\n[{timestamp()}] Stopped")
    finally:
        ser.close()

def info_mode(port, baudrate):
    """Display port information"""
    print(f"[{timestamp()}] Opening {port} at {baudrate} baud")
    ser = serial.Serial(port, baudrate, timeout=1)
    
    print(f"\nPort Information:")
    print(f"  Name:     {ser.name}")
    print(f"  Baudrate: {ser.baudrate}")
    print(f"  Bytesize: {ser.bytesize}")
    print(f"  Parity:   {ser.parity}")
    print(f"  Stopbits: {ser.stopbits}")
    print(f"  Timeout:  {ser.timeout}")
    print(f"  Open:     {ser.is_open}")
    
    # Test write
    print(f"\nTesting write...")
    ser.write(b"HELLO\n")
    print(f"  6 bytes written")
    
    # Check buffer
    time.sleep(0.5)
    print(f"\nChecking receive buffer...")
    print(f"  Bytes waiting: {ser.in_waiting}")
    
    ser.close()
    print(f"\n[{timestamp()}] Port closed")

def main():
    parser = argparse.ArgumentParser(description='UV-Pro Serial Test')
    parser.add_argument('mode', choices=['send', 'receive', 'interactive', 'info'],
                      help='Test mode')
    parser.add_argument('-p', '--port', default='/dev/rfcomm0',
                      help='Serial port (default: /dev/rfcomm0)')
    parser.add_argument('-b', '--baud', type=int, default=9600,
                      help='Baud rate (default: 9600)')
    parser.add_argument('-i', '--interval', type=float, default=1.0,
                      help='Send interval in seconds (default: 1.0)')
    
    args = parser.parse_args()
    
    if args.mode == 'send':
        send_mode(args.port, args.baud, args.interval)
    elif args.mode == 'receive':
        receive_mode(args.port, args.baud)
    elif args.mode == 'interactive':
        interactive_mode(args.port, args.baud)
    elif args.mode == 'info':
        info_mode(args.port, args.baud)

if __name__ == '__main__':
    main()
