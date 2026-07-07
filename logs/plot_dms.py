#!/usr/bin/env python3
"""
Plottet das DMS-CSV-Log (t_ms,code,microstrain,note) berichtstauglich.

Aufruf:
    python plot_dms.py  <logdatei>
Beispiel:
    python plot_dms.py  platformio-device-monitor-250101-120000.log

Erzeugt:  dms_plot.png (300 dpi) und dms_plot.pdf (vektoriell, fuer den Bericht).
Benoetigt:  pip install matplotlib
"""

import sys
import matplotlib.pyplot as plt

infile = sys.argv[1] if len(sys.argv) > 1 else "dms_log.csv"

t, eps, notes = [], [], []
with open(infile, encoding="utf-8", errors="ignore") as f:
    for line in f:
        line = line.strip()
        # Kommentare (#), Monitor-Zeilen (---) und leere Zeilen ueberspringen
        if not line or line.startswith("#") or line.startswith("---"):
            continue
        parts = line.split(",")
        if len(parts) < 3:
            continue
        try:
            t_ms = float(parts[0]); ue = float(parts[2])
        except ValueError:
            continue  # ueberspringt die Kopfzeile 't_ms,code,microstrain,note'
        sec = t_ms / 1000.0
        t.append(sec); eps.append(ue)
        note = parts[3].strip() if len(parts) > 3 else ""
        if note:
            notes.append((sec, ue, note))

if not t:
    sys.exit(f"Keine Messdaten in '{infile}' gefunden.")

plt.figure(figsize=(8, 4.5))
plt.plot(t, eps, lw=0.9, color="#1f4e79", label="Dehnung")

plt.xlabel("Zeit [s]")
plt.ylabel("Dehnung [µε]")
plt.title("DMS-Messung – Gewichtsbelastung (Viertelbrücke)")
plt.grid(True, alpha=0.3)
plt.tight_layout()

plt.savefig("dms_plot.png", dpi=300)
plt.savefig("dms_plot.pdf")
print(f"{len(t)} Punkte geplottet -> dms_plot.png, dms_plot.pdf")
