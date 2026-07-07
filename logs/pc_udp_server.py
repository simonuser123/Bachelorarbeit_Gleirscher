#!/usr/bin/env python3
"""
Empfaengt die binaeren UDP-Pakete des Hochraten-Knotens, dekodiert sie,
erkennt Paketverluste ueber die Sequenznummern und schreibt eine CSV-Datei
im gewohnten Format (t_ms,code,microstrain) -> plot_dms.py funktioniert.

Aufruf:   python pc_udp_server.py
Beenden:  Strg+C  (gibt die Verluststatistik aus)

Firewall: eingehende UDP-Pakete auf PORT erlauben. PC und ESP32 im selben Subnetz.
"""

import socket
import struct
import datetime

PORT = 3333

# Umrechnungsparameter (muessen zur Hardware passen)
K    = 2.11          # Gauge-Faktor aus DMS-Datenblatt
GAIN = 128.0
FS   = 8388608.0    # 2^23

HDR = struct.Struct("<BBHHHIQ")   # magic,version,sps,count,reserved,seq_start,t_us = 20 Byte

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("0.0.0.0", PORT))

fname = "dms_rot_" + datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + ".csv"
print(f"Warte auf UDP-Pakete an Port {PORT} ...  (Strg+C zum Beenden)")

code_zero = None
baseline  = []
expected  = None       # erwartete naechste Sequenznummer
lost      = 0          # verlorene Samples (Luecken)
recv      = 0          # empfangene Samples
t0_ms     = None       # Zeit-Nullpunkt fuer schoenen Plot
pkts      = 0

try:
    with open(fname, "w", encoding="utf-8") as f:
        f.write("t_ms,code,microstrain\n")
        while True:
            data, addr = sock.recvfrom(2048)
            if len(data) < HDR.size:
                continue
            magic, ver, sps, count, _res, seq_start, t_us = HDR.unpack_from(data, 0)
            if magic != 0xA5 or count == 0:
                continue
            codes = struct.unpack_from("<%di" % count, data, HDR.size)
            pkts += 1

            # --- Verlusterkennung ueber Sequenznummern ---
            if expected is not None and seq_start > expected:
                lost += seq_start - expected
            expected = seq_start + count
            recv += count

            # --- Nullabgleich: Dynamisch an SPS angepasst ---
            if code_zero is None:
                baseline.extend(codes)
                required_tara_samples = sps * 2  # 2 Sekunden Tara-Zeit
                if required_tara_samples < 10: required_tara_samples = 10
                
                if len(baseline) >= required_tara_samples:
                    code_zero = sum(baseline) / len(baseline)
                    print(f"codeZero = {code_zero:.0f} (tariert ueber {len(baseline)} Werte)")

            # Temporaerer Nullpunkt waehrend der Tara-Phase
            if code_zero is not None:
                cz = code_zero
            else:
                # Alle bisherigen mitteln, NICHT nur das aktuelle (1er) Paket!
                cz = sum(baseline) / len(baseline) if len(baseline) > 0 else codes[0]

            for i, c in enumerate(codes):
                t_ms = t_us / 1000.0 + i * 1000.0 / sps
                if t0_ms is None:
                    t0_ms = t_ms
                eps = 4.0 * (c - cz) / (K * GAIN * FS) * 1e6
                f.write(f"{t_ms - t0_ms:.3f},{c},{eps:.2f}\n")
                f.flush()

            if pkts % 100 == 0:
                tot = recv + lost
                pct = (100.0 * lost / tot) if tot else 0.0
                print(f"  Pakete {pkts} | Samples {recv} | Verlust {lost} ({pct:.2f} %)")

except KeyboardInterrupt:
    tot = recv + lost
    pct = (100.0 * lost / tot) if tot else 0.0
    print(f"\nBeendet. {recv} Samples empfangen, {lost} verloren ({pct:.2f} %).")
    print(f"Datei: {fname}")
finally:
    sock.close()