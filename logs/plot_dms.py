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

# --- Hilfsfunktionen für das deutsche Zahlenformat ---
def german_ticks(x, pos):
    """Formatierer für die Matplotlib-Achsen (tauscht Punkt gegen Komma)."""
    return f"{x:g}".replace('.', ',')

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

# Optionaler Zeitbereich: python plot_dms.py logfile.log 2 3
t_start = float(sys.argv[2]) if len(sys.argv) > 2 else None
t_end = float(sys.argv[3]) if len(sys.argv) > 3 else None

if t_start is not None or t_end is not None:
    filtered = [(ti, ei) for ti, ei in zip(t, eps)
                if (t_start is None or ti >= t_start) and (t_end is None or ti <= t_end)]
    if not filtered:
        sys.exit(f"Keine Datenpunkte im Bereich [{t_start}, {t_end}] Sekunden gefunden.")
    t, eps = zip(*filtered)
    notes = [(sec, ue, note) for sec, ue, note in notes
              if (t_start is None or sec >= t_start) and (t_end is None or sec <= t_end)]
    
plt.figure(figsize=(8, 4.5))
plt.plot(t, eps, lw=0.9, color="#1f4e79", label="Dehnung")

plt.xlabel("Zeit in s")
plt.ylabel("Dehnung in µm/m")
plt.gca().xaxis.set_major_formatter(german_ticks)
plt.gca().yaxis.set_major_formatter(german_ticks)

title = "DMS-Messung"
if t_start is not None or t_end is not None:
    title += f" [{t_start or 0:.1f}–{t_end or t[-1]:.1f} s]"
plt.title(title)
plt.grid(True, alpha=0.3)
plt.tight_layout()
suffix = ""
if t_start is not None or t_end is not None:
    suffix = f"_{t_start or 0:.1f}-{t_end or t[-1]:.1f}s"

png_name = f"dms_plot{suffix}.png"
pdf_name = f"dms_plot{suffix}.pdf"

plt.savefig(png_name, dpi=300)
plt.savefig(pdf_name)
print(f"{len(t)} Punkte geplottet -> {png_name}, {pdf_name}")