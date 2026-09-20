import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker  # NEU: Für die Komma-Formatierung der Achsen
from scipy.stats import linregress
import tkinter as tk
from tkinter import filedialog

# --- NEU: Hilfsfunktionen für das deutsche Zahlenformat ---
def fmt(value, decimals=3):
    """Formatiert eine Zahl mit der gewünschten Nachkommastelle und ersetzt den Punkt durch ein Komma."""
    return f"{value:.{decimals}f}".replace('.', ',')

def german_ticks(x, pos):
    """Formatierer für die Matplotlib-Achsen (tauscht Punkt gegen Komma)."""
    return f"{x:g}".replace('.', ',')
# ----------------------------------------------------------

def main():
    # 1. Datei-Dialog öffnen
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    file_path = filedialog.askopenfilename(
        title="Wähle deine DMS CSV-Datei aus",
        filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")]
    )
    
    if not file_path:
        print("Keine Datei ausgewählt. Abbruch.")
        return

    # Verzeichnis und Dateiname für den automatischen PDF-Export vorbereiten
    base_dir = os.path.dirname(file_path)
    base_name = os.path.splitext(os.path.basename(file_path))[0]

    # 2. Daten robust einlesen
    print(f"Lese Datei ein: {file_path}")
    try:
        df = pd.read_csv(file_path, header=None, names=['Zeit_ms', 'Raw_ADC', 'Dehnung_ue'], low_memory=False)
        df['Zeit_ms'] = pd.to_numeric(df['Zeit_ms'], errors='coerce')
        df['Raw_ADC'] = pd.to_numeric(df['Raw_ADC'], errors='coerce')
        df['Dehnung_ue'] = pd.to_numeric(df['Dehnung_ue'], errors='coerce')
        df = df.dropna()
    except Exception as e:
        print(f"Fehler beim Einlesen: {e}")
        return

    # 3. Zeit in Sekunden umrechnen
    df['Zeit_s'] = df['Zeit_ms'] / 1000.0

    if df.empty:
        print("Fehler: Die Datei enthält nach der Bereinigung keine gültigen Daten mehr.")
        return

    # 4. Vorab-Visualisierung zur Auswahl des Fensters
    plt.figure(figsize=(8, 4.5))
    plt.plot(df['Zeit_s'], df['Dehnung_ue'], linewidth=0.5, color='#1f77b4')
    plt.title("Gesamtverlauf - Voransicht (Bitte Start- und Endzeit ablesen)")
    plt.xlabel("Zeit [s]")
    plt.ylabel("Dehnung [µm/m]")
    
    # Voransicht auch mit deutschen Achsen
    plt.gca().xaxis.set_major_formatter(ticker.FuncFormatter(german_ticks))
    plt.gca().yaxis.set_major_formatter(ticker.FuncFormatter(german_ticks))
    
    plt.grid(True, alpha=0.3)
    plt.show(block=False)
    plt.pause(0.1)

    # 5. Benutzereingabe für das Analysefenster
    print("\n--- Analysefenster auswählen ---")
    try:
        # .replace(',', '.') erlaubt es dir, die Zeiten im Terminal mit Komma einzutippen!
        t_start = float(input("Startzeit [s]: ").replace(',', '.'))
        t_end = float(input("Endzeit [s]: ").replace(',', '.'))
    except ValueError:
        print("Ungültige Eingabe. Bitte Zahlen verwenden.")
        return
    
    plt.close() # Schließt die Voransicht

    # Daten auf das Fenster filtern
    mask = (df['Zeit_s'] >= t_start) & (df['Zeit_s'] <= t_end)
    df_window = df[mask].copy()

    if df_window.empty:
        print("Keine Daten in diesem Zeitraum gefunden.")
        return

    # 6. Berechnung der Parameter
    time = df_window['Zeit_s'].values
    strain = df_window['Dehnung_ue'].values

    slope, intercept, r_value, p_value, std_err = linregress(time, strain)
    drift_line = slope * time + intercept
    strain_detrended = strain - drift_line
    
    mean_offset = np.mean(strain)
    drift_per_sec = slope
    noise_p2p = np.max(strain_detrended) - np.min(strain_detrended)
    noise_rms = np.std(strain_detrended)
    
    outlier_threshold = 3 * noise_rms
    outliers = np.abs(strain_detrended) > outlier_threshold
    num_outliers = np.sum(outliers)

    # 7. Ergebnisse in der Konsole ausgeben (jetzt mit Komma-Formatierung)
    print("\n========================================")
    print("        ERGEBNISSE DER ANALYSE          ")
    print("========================================")
    print(f"Analysiertes Fenster:  {fmt(t_start, 2)} s bis {fmt(t_end, 2)} s")
    print(f"Anzahl Datenpunkte:    {len(time)} Samples")
    print("----------------------------------------")
    print(f"Mittlerer Offset:      {fmt(mean_offset, 3)} µm/m")
    print(f"Drift-Rate:            {fmt(drift_per_sec, 5)} µm/ms")
    print(f"Peak-to-Peak Rauschen: {fmt(noise_p2p, 3)} µm/m")
    print(f"RMS Rauschen (1 Sigma):{fmt(noise_rms, 3)} µm/m")
    print(f"Erkannte Spikes (>3σ): {num_outliers} Stück")
    print("========================================\n")

    # 8. Einzelne Abschluss-Plots als Vektorgrafik erstellen & exportieren
    
    # Zuweisen des Formatierers an eine Variable für leichtere Lesbarkeit
    ger_formatter = ticker.FuncFormatter(german_ticks)
    
    # Plot 1: Signalausschnitt & Drift
    fig1, ax1 = plt.subplots(figsize=(8, 4.5))
    ax1.plot(time, strain, label='Messsignal', linewidth=0.8, color='#1f77b4')
    ax1.plot(time, drift_line, label=f'Drift ({fmt(drift_per_sec, 3)} µm/ms)', color='red', linestyle='--')
    ax1.set_title("Signalausschnitt & thermischer Drift")
    ax1.set_xlabel("Zeit in s")
    ax1.set_ylabel("Dehnung in µm/m")
    ax1.xaxis.set_major_formatter(ger_formatter)
    ax1.yaxis.set_major_formatter(ger_formatter)
    ax1.grid(True, alpha=0.3)
    ax1.legend()
    fig1.tight_layout()
    pdf_path1 = os.path.join(base_dir, f"{base_name}_01_drift.pdf")
    fig1.savefig(pdf_path1, format='pdf')

    # Plot 2: Bereinigtes Rauschen (ohne Drift)
    fig2, ax2 = plt.subplots(figsize=(8, 4.5))
    ax2.plot(time, strain_detrended, linewidth=0.8, color='#1f77b4')
    ax2.axhline(outlier_threshold, color='orange', linestyle=':', label='3σ Grenze')
    ax2.axhline(-outlier_threshold, color='orange', linestyle=':')
    ax2.scatter(time[outliers], strain_detrended[outliers], color='red', s=15, label='Spikes', zorder=5)
    ax2.set_title("Detrendetes Rauschen (Drift bereinigt)")
    ax2.set_xlabel("Zeit in s")
    ax2.set_ylabel("Dehnung in µm/m")
    ax2.xaxis.set_major_formatter(ger_formatter)
    ax2.yaxis.set_major_formatter(ger_formatter)
    ax2.grid(True, alpha=0.3)
    ax2.legend()
    fig2.tight_layout()
    pdf_path2 = os.path.join(base_dir, f"{base_name}_02_rauschen.pdf")
    fig2.savefig(pdf_path2, format='pdf')

    # Plot 3: Histogramm
    fig3, ax3 = plt.subplots(figsize=(8, 4.5))
    ax3.hist(strain_detrended, bins=50, color='#6699cc', edgecolor='black', alpha=0.7)
    ax3.set_title("Rauschverteilung (Histogramm)")
    ax3.set_xlabel("Dehnung in µm/m")
    ax3.set_ylabel("Häufigkeit")
    ax3.xaxis.set_major_formatter(ger_formatter)
    ax3.yaxis.set_major_formatter(ger_formatter)
    ax3.grid(True, alpha=0.3)
    fig3.tight_layout()
    pdf_path3 = os.path.join(base_dir, f"{base_name}_03_histogramm.pdf")
    fig3.savefig(pdf_path3, format='pdf')

    print(f"✅ Die Grafiken wurden erfolgreich als PDF-Vektorgrafiken gespeichert in:\n{base_dir}\n")

    # Alle drei Fenster auf dem Bildschirm anzeigen
    plt.show()

if __name__ == "__main__":
    main()