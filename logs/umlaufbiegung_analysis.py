import os
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from scipy.optimize import curve_fit
from scipy.fft import fft, fftfreq
import tkinter as tk
from tkinter import filedialog

# --- Hilfsfunktionen für das deutsche Zahlenformat ---
def fmt(value, decimals=3):
    """Formatiert eine Zahl mit der gewünschten Nachkommastelle und ersetzt den Punkt durch ein Komma."""
    return f"{value:.{decimals}f}".replace('.', ',')

def german_ticks(x, pos):
    """Formatierer für die Matplotlib-Achsen (tauscht Punkt gegen Komma)."""
    return f"{x:g}".replace('.', ',')

# Die mathematische Sinus-Funktion für das Curve-Fitting
def sine_model(t, offset, amplitude, f, phase):
    return offset + amplitude * np.sin(2 * np.pi * f * t + phase)

def main():
    # 1. Datei-Dialog öffnen
    root = tk.Tk()
    root.withdraw()
    root.attributes('-topmost', True)
    file_path = filedialog.askopenfilename(
        title="Wähle deine DMS CSV-Datei (unter Last) aus",
        filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")]
    )
    
    if not file_path:
        print("Keine Datei ausgewählt. Abbruch.")
        return

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

    df['Zeit_s'] = df['Zeit_ms'] / 1000.0

    if df.empty:
        print("Fehler: Die Datei enthält nach der Bereinigung keine gültigen Daten mehr.")
        return

    # 3. Vorab-Visualisierung
    plt.figure(figsize=(8, 4.5))
    plt.plot(df['Zeit_s'], df['Dehnung_ue'], linewidth=0.5, color='#1f77b4')
    plt.title("Umlaufbiegung - Voransicht")
    plt.xlabel("Zeit in s")
    plt.ylabel("Dehnung in µm/m")
    plt.gca().xaxis.set_major_formatter(ticker.FuncFormatter(german_ticks))
    plt.gca().yaxis.set_major_formatter(ticker.FuncFormatter(german_ticks))
    plt.grid(True, alpha=0.3)
    plt.show(block=False)
    plt.pause(0.1)

    # 4. Fenster für den Sinus-Fit auswählen
    print("\n--- Analysefenster für Sinus-Fit auswählen ---")
    print("Tipp: Wähle einen stabilen Bereich (z.B. 1 bis 2 Sekunden Länge)")
    try:
        t_start = float(input("Startzeit [s]: ").replace(',', '.'))
        t_end = float(input("Endzeit [s]: ").replace(',', '.'))
    except ValueError:
        print("Ungültige Eingabe.")
        return
    
    plt.close()

    mask = (df['Zeit_s'] >= t_start) & (df['Zeit_s'] <= t_end)
    df_window = df[mask].copy()

    if len(df_window) < 10:
        print("Zu wenige Datenpunkte im gewählten Fenster.")
        return

    time = df_window['Zeit_s'].values
    strain = df_window['Dehnung_ue'].values

    # 5. Startwerte für das Curve-Fitting ermitteln
    offset_guess = np.mean(strain)
    amp_guess = (np.max(strain) - np.min(strain)) / 2.0
    
    # Frequenz-Guess über FFT
    N = len(time)
    dt = np.mean(np.diff(time))
    yf = np.abs(fft(strain - offset_guess))
    xf = fftfreq(N, dt)
    
    idx_max = np.argmax(yf[1:N//2]) + 1 
    f_guess = xf[idx_max]
    
    p0 = [offset_guess, amp_guess, f_guess, 0.0]

    # 6. Sinus-Fit durchführen
    try:
        popt, pcov = curve_fit(sine_model, time, strain, p0=p0)
        offset_opt, amp_opt, f_opt, phase_opt = popt
        
        amp_opt = abs(amp_opt)
        f_opt = abs(f_opt)
        rpm = f_opt * 60.0
        
    except Exception as e:
        print(f"Fehler beim Sinus-Fit: {e}")
        return

    # 7. Fehlerrechnung (Residuen)
    strain_fit = sine_model(time, offset_opt, amp_opt, f_opt, phase_opt)
    residuals = strain - strain_fit
    rmse = np.sqrt(np.mean(residuals**2))
    
    # 8. Ergebnisse ausgeben (mit deutscher Formatierung)
    print("\n========================================")
    print("     ERGEBNISSE DER UMLAUFBIEGUNG       ")
    print("========================================")
    print(f"Mitteldehnung (Offset): {fmt(offset_opt, 3)} µm/m")
    print(f"Dehnungsamplitude:      {fmt(amp_opt, 3)} µm/m")
    print(f"Spitze-Spitze (Pk-Pk):  {fmt(2*amp_opt, 3)} µm/m")
    print("----------------------------------------")
    print(f"Frequenz:               {fmt(f_opt, 3)} Hz")
    print(f"Drehzahl Welle:         {fmt(rpm, 1)} U/min")
    print("----------------------------------------")
    print(f"Restrauschen (RMSE):    {fmt(rmse, 3)} µm/m")
    print("========================================\n")

    # 9. Vektorgrafiken generieren und exportieren
    ger_formatter = ticker.FuncFormatter(german_ticks)
    
    # Plot 1: Rohdaten vs. Gefitteter Sinus
    fig1, ax1 = plt.subplots(figsize=(8, 4.5))
    ax1.plot(time, strain, label='Messdaten', linewidth=0.8, color='#003366', alpha=0.7)
    ax1.plot(time, strain_fit, label=f'Fit (Amp: {fmt(amp_opt, 1)} µm/m, {fmt(f_opt, 1)} Hz)', color='red', linewidth=1.5)
    ax1.set_title("Umlaufbiegung: Messsignal und Sinus-Fit")
    ax1.set_xlabel("Zeit in s")
    ax1.set_ylabel("Dehnung in µm/m")
    ax1.xaxis.set_major_formatter(ger_formatter)
    ax1.yaxis.set_major_formatter(ger_formatter)
    ax1.grid(True, alpha=0.3)
    ax1.legend()
    fig1.tight_layout()
    pdf_path1 = os.path.join(base_dir, f"{base_name}_01_sinusfit.pdf")
    fig1.savefig(pdf_path1, format='pdf')

# Plot 2: FFT Spektrum (Frequenzanalyse logarithmisch)
    fig2, ax2 = plt.subplots(figsize=(8, 4.5))
    
    # zorder=3 holt die blaue Datenkurve in den absoluten Vordergrund
    ax2.plot(xf[1:N//2], yf[1:N//2] / (N/2), color='#336699', zorder=3)
    
    # alpha=0.4 (Transparenz), feine Linie und zorder=2 (Hintergrund)
    ax2.axvline(f_opt, color='red', linestyle='--', linewidth=1.2, alpha=0.4, zorder=2, label=f'Hauptfrequenz: {fmt(f_opt, 1)} Hz')
    
    ax2.set_title("Frequenzspektrum (FFT) - Drehzahlanalyse")
    ax2.set_xlabel("Frequenz in Hz")
    ax2.set_ylabel("Amplitude in µm/m (log)")
    
    # Logarithmische Skala aktivieren
    ax2.set_yscale('log')
    
    ax2.set_xlim(0, max(50, f_opt * 3))
    ax2.xaxis.set_major_formatter(ger_formatter)
    ax2.yaxis.set_major_formatter(ger_formatter) 
    
    # Grid für logarithmische Skalen anpassen (zorder=1 hält es ganz hinten)
    ax2.grid(True, which="major", alpha=0.5, color='gray', zorder=1)
    ax2.grid(True, which="minor", alpha=0.2, linestyle=':', zorder=1)
    ax2.legend()
    fig2.tight_layout()
    pdf_path2 = os.path.join(base_dir, f"{base_name}_02_spektrum.pdf")
    fig2.savefig(pdf_path2, format='pdf')

    # Plot 3: Residuen (Restrauschen und Störungen)
    fig3, ax3 = plt.subplots(figsize=(8, 4.5))
    ax3.plot(time, residuals, color='#6699cc', linewidth=0.8)
    ax3.axhline(0, color='black', linewidth=1)
    ax3.axhline(3*rmse, color='orange', linestyle=':', label='3σ Grenze')
    ax3.axhline(-3*rmse, color='orange', linestyle=':')
    ax3.set_title("Residuen (Abweichung des Messsignals vom idealen Sinus)")
    ax3.set_xlabel("Zeit in s")
    ax3.set_ylabel("Dehnung in µm/m")
    ax3.xaxis.set_major_formatter(ger_formatter)
    ax3.yaxis.set_major_formatter(ger_formatter)
    ax3.grid(True, alpha=0.3)
    ax3.legend()
    fig3.tight_layout()
    pdf_path3 = os.path.join(base_dir, f"{base_name}_03_residuen.pdf")
    fig3.savefig(pdf_path3, format='pdf')

    print(f"✅ Drei Analyse-PDFs erfolgreich gespeichert in:\n{base_dir}\n")
    
    plt.show()

if __name__ == "__main__":
    main()