import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from scipy.signal import butter, filtfilt

# ==========================================
# 1. DATEN LADEN
# ==========================================
filename = 'dms_rot_20260625_330Hz_strom_ueber_akku.csv'
df = pd.read_csv(filename)

# Die Zeitachse in Sekunden umrechnen (für eine saubere X-Achse)
# Dein t_ms beginnt bei 0 und geht in 1ms-Schritten hoch (1000 Hz)
zeit_sekunden = df['t_ms'] / 1000.0
roh_dehnung = df['microstrain']

# ==========================================
# 2. DIGITALEN FILTER ERSTELLEN (Butterworth Tiefpass)
# ==========================================
abtastrate_hz = 1000.0  # Deine Messfrequenz
cutoff_frequenz = 50.0  # Grenzfrequenz in Hz (Alles über 20 Hz wird als Rauschen gelöscht)

# Nyquist-Frequenz ist die halbe Abtastrate
nyquist = 0.5 * abtastrate_hz
normierte_cutoff = cutoff_frequenz / nyquist

# Butterworth-Filter 4. Ordnung erstellen
b, a = butter(4, normierte_cutoff, btype='low', analog=False)

# Filter auf die Rohdaten anwenden (filtfilt verhindert Phasenverschiebung)
gefilterte_dehnung = filtfilt(b, a, roh_dehnung)

# ==========================================
# 3. DATEN PLOTTEN (Roh vs. Gefiltert)
# ==========================================
plt.figure(figsize=(12, 6))

# Rohdaten im Hintergrund (halbtransparent)
plt.plot(zeit_sekunden, roh_dehnung, color='lightgray', alpha=0.7, 
         label='Rohdaten (1000 Hz, starkes Rauschen)')

# Gefilterte Daten im Vordergrund
plt.plot(zeit_sekunden, gefilterte_dehnung, color='#004b79', linewidth=2, 
         label=f'Gefiltert (Tiefpass, Cutoff={cutoff_frequenz} Hz)')

# Layout anpassen
plt.title('DMS Signalverarbeitung: Rauschunterdrückung bei WLAN-Übertragung', fontsize=14)
plt.xlabel('Zeit [s]', fontsize=12)
plt.ylabel('Dehnung [µε]', fontsize=12)
plt.legend(loc='upper right')
plt.grid(True, linestyle='--', alpha=0.6)

# Achsen-Limits etwas anpassen, damit Ausreißer das Bild nicht sprengen
# Wir zoomen auf die interessanten ersten paar Sekunden
plt.xlim(0, max(zeit_sekunden))
plt.ylim(-150, 150)  

plt.tight_layout()
plt.savefig('gefilterte_messung.png', dpi=300)
plt.show()

# ==========================================
# 4. QUALITÄTSANALYSE AUSGEBEN
# ==========================================
rauschen_roh = np.std(roh_dehnung)
rauschen_gefiltert = np.std(gefilterte_dehnung)

print("=== Signalanalyse ===")
print(f"Standardabweichung (Rauschen) Rohdaten:   {rauschen_roh:.2f} µε")
print(f"Standardabweichung (Rauschen) Gefiltert:  {rauschen_gefiltert:.2f} µε")
print(f"Rauschunterdrückung um den Faktor:        {rauschen_roh / rauschen_gefiltert:.1f}x")