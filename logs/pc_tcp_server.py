#!/usr/bin/env python3
"""
Empfaengt den CSV-Stream des ESP32-Sensorknotens per TCP und schreibt ihn
in eine Datei (gleiches Format wie das USB-Log -> plot_dms.py funktioniert).

Aufruf:   python pc_tcp_server.py
Beenden:  Strg+C

Wichtig:
  - PC und ESP32 im selben WLAN/Subnetz.
  - Lokale PC-IP herausfinden (Windows: ipconfig, Linux/macOS: ip addr / ifconfig)
    und im ESP32-Sketch bei PC_HOST eintragen.
  - Firewall: eingehende Verbindungen auf PORT erlauben.
"""

import socket
import sys
import datetime

HOST = "0.0.0.0"          # auf allen Schnittstellen lauschen
PORT = 3333               # muss zu PC_PORT im Sketch passen

fname = "dms_wifi_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + ".csv"

srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
srv.bind((HOST, PORT))
srv.listen(1)
print(f"Warte auf ESP32 an Port {PORT} ... (Strg+C zum Beenden)")

try:
    while True:
        conn, addr = srv.accept()
        print(f"Verbunden mit {addr[0]}:{addr[1]}  ->  schreibe {fname}")
        with conn, open(fname, "a", encoding="utf-8") as f:
            while True:
                data = conn.recv(4096)
                if not data:
                    print("Verbindung getrennt - warte auf Neuverbindung ...")
                    break
                text = data.decode(errors="ignore")
                f.write(text)
                f.flush()
                sys.stdout.write(text)   # Live-Mitschau im Terminal
except KeyboardInterrupt:
    print(f"\nBeendet. Daten in: {fname}")
finally:
    srv.close()