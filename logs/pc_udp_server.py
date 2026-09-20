#!/usr/bin/env python3
"""
Empfaengt die binaeren UDP-Pakete des Hochraten-Knotens, dekodiert sie,
erkennt Paketverluste ueber die Sequenznummern und schreibt eine CSV-Datei
im gewohnten Format (t_ms,code,microstrain) -> plot_dms.py funktioniert.

Zeitachse: Der Header traegt nur den Zeitstempel des ERSTEN Samples eines Pakets.
Die uebrigen werden interpoliert - dafuer wird die reale Abtastrate zur Laufzeit aus
Sequenznummern und Zeitstempeln geschaetzt (siehe unten). Der Nennwert aus dem Header
taugt dafuer nicht: der interne Oszillator des ADS1220 weicht typisch um einige Prozent
ab (gemessen: rund 980 statt 1000 SPS).

Aufruf:   python pc_udp_server.py
Beenden:  Strg+C  (gibt die Verlust- und Abtastratenstatistik aus)

Firewall: eingehende UDP-Pakete auf PORT erlauben. PC und ESP32 im selben Subnetz.
"""

import socket
import struct
import datetime

PORT = 3333

# Umrechnungsparameter (muessen zur Hardware passen)
K    = 2.06          # Gauge-Faktor aus DMS-Datenblatt
GAIN = 128.0
FS   = 8388608.0    # 2^23

HDR = struct.Struct("<BBHHHIQ")   # magic,version,sps,count,reserved,seq_start,t_us = 20 Byte

# Mindest-Zeitbasis, bevor der Ratenschaetzung getraut wird. Der Zeitstempel eines
# Pakets wackelt um etwa ein Sample; ueber 2 s Basis bleibt davon rund 0,05 % uebrig
# und damit deutlich weniger als die ~2 % Abweichung des Nennwerts.
RATE_MIN_SPAN_S = 2.0

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

rate      = None       # geschaetzte reale Abtastrate [Hz]
sps_nom   = None       # Nennwert aus dem Header (zum Vergleich)
seq_ref   = None       # Bezugspunkt der Ratenschaetzung
t_us_ref  = None
rate_shown = False     # Schaetzung schon einmal gemeldet?

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

            # --- Reale Abtastrate schaetzen ---
            # seq zaehlt JEDES erfasste Sample und t_us ist ein echter Hardware-
            # Zeitstempel. Damit ist dseq/dt die reale Datenrate des ADC - auch ueber
            # Paketverluste hinweg, weil die Sequenznummer dabei weiterlaeuft.
            # Bezugspunkt bleibt das erste Paket: je laenger die Basis, desto genauer.
            if seq_ref is None:
                seq_ref, t_us_ref = seq_start, t_us
                sps_nom, rate = float(sps), float(sps)   # bis zur Schaetzung gilt der Nennwert
            span_s = (t_us - t_us_ref) / 1e6
            if span_s >= RATE_MIN_SPAN_S and seq_start > seq_ref:
                rate = (seq_start - seq_ref) / span_s
                if not rate_shown:
                    print(f"reale Abtastrate = {rate:.2f} Hz "
                          f"(Nennwert {sps} Hz, {100*(rate/sps_nom - 1):+.2f} %)")
                    rate_shown = True

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
                t_ms = t_us / 1000.0 + i * 1000.0 / rate
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
    if rate is not None:
        span_s = (t_us - t_us_ref) / 1e6
        print(f"Abtastrate: {rate:.2f} Hz real, {sps_nom:.0f} Hz nominell "
              f"({100*(rate/sps_nom - 1):+.2f} %, Basis {span_s:.1f} s)"
              if rate_shown else
              f"Abtastrate: Messung zu kurz fuer eine Schaetzung, "
              f"Nennwert {sps_nom:.0f} Hz verwendet")
    print(f"Datei: {fname}")
finally:
    sock.close()