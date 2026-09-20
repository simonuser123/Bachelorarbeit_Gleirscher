# DMS-Funktelemetrie – Dehnungsmessung an rotierender Welle

Drahtloses Messsystem zur Erfassung mechanischer Dehnung (µε) mit einem
Dehnungsmessstreifen (DMS) in Viertelbrücke. Ein ESP32-Sensorknoten
digitalisiert das DMS-Signal hochauflösend, überträgt die Rohwerte per WLAN/UDP
an einen PC, der sie dekodiert, in Mikrostrain umrechnet, Paketverluste erkennt
und als CSV protokolliert. Ein separates Plot-Skript erzeugt daraus
berichtstaugliche Grafiken.

Der Aufbau ist speziell für **rotierende Wellen** gedacht: Da eine
Kabelverbindung dort nicht praktikabel ist, sitzt der komplette Messknoten
mitdrehend auf der Welle und funkt seine Daten kabellos an eine ortsfeste
Empfangsstation.

---

## Inhalt

- [Systemüberblick](#systemüberblick)
- [Hardware](#hardware)
- [Komponenten im Detail](#komponenten-im-detail)
- [Quick Start](#quick-start)
- [Betriebsanleitung (Runbook)](#betriebsanleitung-runbook)
- [UDP-Protokoll (Referenz)](#udp-protokoll-referenz)
- [CSV-Datenformat](#csv-datenformat)
- [Umrechnung Code → Mikrostrain](#umrechnung-code--mikrostrain)
- [Konfiguration & Abtastraten](#konfiguration--abtastraten)
- [Fehlersuche](#fehlersuche)
- [Bekannte Einschränkungen](#bekannte-einschränkungen)

---

## Systemüberblick

Die Messkette besteht aus drei Stufen: Sensorknoten (funkt), PC-Server
(empfängt und protokolliert) und Plot-Tool (visualisiert).

```
  ROTIERENDE WELLE                              ORTSFESTE STATION (PC)
 ┌───────────────────────────────┐            ┌──────────────────────────────┐
 │  DMS (Viertelbrücke)          │            │  pc_udp_server.py            │
 │        │                       │            │   • dekodiert Binärpakete    │
 │        ▼                       │            │   • zählt Paketverlust       │
 │  ADS1220 (24-Bit, Gain 128)   │            │   • Nullabgleich (Tara)      │
 │        │ SPI                   │  WLAN/UDP  │   • rechnet in µε um         │
 │        ▼                       │  ───────►  │   • schreibt CSV             │
 │  XIAO ESP32S3                 │  Port 3333 │            │                  │
 │   • Core 1: Erfassung (acq)   │            │            ▼                  │
 │   • Core 0: Netzwerk (net)    │            │  dms_rot_YYYYMMDD_HHMMSS.csv │
 │   • Status-LED                │            │            │                  │
 └───────────────────────────────┘            │            ▼                  │
                                               │  plot_dms.py → PNG + PDF     │
                                               └──────────────────────────────┘
```

Der Datenpfad in Kurzform:

1. Der ADS1220 wandelt das DMS-Brückensignal kontinuierlich mit fester
   Abtastrate. Jeder fertige Wert löst über die DRDY-Leitung einen Interrupt aus.
2. Auf dem ESP32 liest der **Erfassungs-Task** (Core 1) den Rohwert aus, versieht
   ihn mit einer fortlaufenden Sequenznummer und einem Mikrosekunden-Zeitstempel
   und legt ihn in eine Queue.
3. Der **Netzwerk-Task** (Core 0) bündelt mehrere Samples zu einem binären
   UDP-Paket und sendet es an den PC.
4. Der **PC-Server** dekodiert die Pakete, erkennt Lücken in den Sequenznummern
   (= Paketverlust), tariert die Nulllage und rechnet die ADC-Codes in
   Mikrostrain um. Alles landet in einer CSV.
5. **`plot_dms.py`** liest die CSV und erzeugt eine PNG- und eine PDF-Grafik.

---

## Hardware

| Bauteil        | Typ / Modell                     | Funktion                                        |
|----------------|----------------------------------|-------------------------------------------------|
| Mikrocontroller| Seeed **XIAO ESP32S3** (Dual-Core)| WLAN, Erfassung, Bündelung, Versand            |
| ADC            | Olimex **BB-ADS1220**            | 24-Bit-Delta-Sigma-ADC mit integriertem PGA     |
| Sensor         | DMS in **Viertelbrücke**         | wandelt Dehnung in Widerstandsänderung          |

### Verdrahtung (ESP32 ↔ ADS1220 über SPI)

| ESP32-Pin | Signal | ADS1220 |
|-----------|--------|---------|
| `D0`      | CS     | Chip-Select |
| `D1`      | DRDY   | Data-Ready (Interrupt-Eingang) |
| `D8`      | SCK    | SPI-Takt |
| `D9`      | MISO   | SPI Daten (ADC → ESP32) |
| `D10`     | MOSI   | SPI Daten (ESP32 → ADC) |

SPI läuft mit **4 MHz, Modus 1** (`SPI_MODE1`). Das DMS-Signal wird an den
Kanälen **AIN0/AIN1** des ADS1220 mit **Verstärkung 128** (PGA aktiv)
aufgenommen, Referenz ist AVDD.

Die Onboard-LED (GPIO21, *active LOW*) dient als Statusanzeige — siehe
[Fehlersuche](#fehlersuche).

---

## Komponenten im Detail

### `main.cpp` — ESP32-Firmware

Nutzt FreeRTOS und die beiden Kerne des ESP32S3 getrennt, damit die zeitkritische
Erfassung nicht durch den WLAN-Stack gestört wird:

- **`acqTask` (Core 1, Priorität 3):** Wartet auf das DRDY-Interrupt-Signal,
  liest den 24-Bit-Wert per SPI, ergänzt Sequenznummer (`seq`, zählt *jedes*
  Sample) und Zeitstempel (`esp_timer_get_time()`, µs) und schreibt das Sample
  in die Queue. Läuft die Queue über, wird ein Zähler (`dropped`) erhöht — die
  Lücke wird später am PC über die Sequenznummern sichtbar.
- **`netTask` (Core 0, Priorität 2):** Verwaltet die WLAN-Verbindung
  (Auto-Reconnect, kein Modem-Sleep), entnimmt Samples aus der Queue und bündelt
  sie zu einem Paket. Ein Paket wird verschickt, sobald **200 Samples**
  (`BATCH_MAX`) gesammelt sind **oder 100 ms** (`BATCH_MS`) vergangen sind — je
  nachdem, was zuerst eintritt. Das begrenzt gleichzeitig Paketgröße (< MTU) und
  Latenz.
- **`loop()` (Status-LED):** Steuert das Blinkmuster der Onboard-LED je nach
  Verbindungs- und Pufferzustand.

Die Sample-Queue fasst **2048 Einträge** — ein großzügiger Puffer, der kurze
WLAN-Aussetzer überbrückt.

### `pc_udp_server.py` — Empfänger & Protokollierung

Lauscht auf **UDP-Port 3333** und verarbeitet jedes eingehende Paket:

- **Dekodierung:** Entpackt den 20-Byte-Header und die nachfolgenden
  int32-Rohwerte.
- **Verlusterkennung:** Vergleicht die erwartete nächste Sequenznummer mit der
  tatsächlichen (`seq_start`). Jede Lücke wird als verlorene Samples gezählt und
  regelmäßig als Prozentwert ausgegeben.
- **Nullabgleich (Tara):** Mittelt die ersten **2 Sekunden** an Rohwerten
  (`sps × 2`, mind. 10 Werte) zum Nullpunkt `code_zero`. Bis der Nullpunkt steht,
  wird dynamisch über alle bisherigen Werte gemittelt.
- **Umrechnung:** Rechnet jeden Rohwert in Mikrostrain um (siehe
  [Formel](#umrechnung-code--mikrostrain)).
- **Zeitrekonstruktion:** Der Header trägt nur den Zeitstempel des *ersten*
  Samples; die übrigen werden aus der Abtastrate (`t_us + i·1000/sps`)
  interpoliert und auf einen gemeinsamen Nullpunkt `t0` bezogen.
- **Ausgabe:** Schreibt zeilenweise in `dms_rot_<Datum>_<Zeit>.csv`.

Beenden mit **Strg+C** — dann wird die Gesamt-Verluststatistik ausgegeben.

### `plot_dms.py` — Visualisierung

Liest eine CSV (Spalten `t_ms,code,microstrain`, optionale `note`-Spalte),
überspringt Kommentar- und Kopfzeilen und plottet die Dehnung über die Zeit.
Ergebnis: **`dms_plot.png`** (300 dpi) und **`dms_plot.pdf`** (vektoriell, für
den Bericht).

---

## Quick Start

**Voraussetzungen:** PlatformIO oder Arduino IDE (ESP32-Board-Support), Python 3
mit `matplotlib`, PC und ESP32 im selben WLAN/Subnetz.

```bash
# 1) PC-Server starten (schreibt CSV, wartet auf Pakete)
python pc_udp_server.py

# 2) ESP32 flashen (nachdem WLAN- und PC-IP in main.cpp gesetzt sind)
#    -> Knoten verbindet sich, LED blinkt 1×/s = alles ok, Daten fließen

# 3) Nach der Messung: Strg+C im Server -> Verluststatistik + Dateiname

# 4) Grafik erzeugen
python plot_dms.py dms_rot_20260706_162503.csv
```

---

## Betriebsanleitung (Runbook)

**Wann verwenden:** Für eine komplette Messung von Vorbereitung bis Grafik.

### 1. Vorbereitung (einmalig, in `main.cpp`)

Vor dem Flashen im Abschnitt `// ===== ANPASSEN =====` setzen:

| Konstante   | Bedeutung                                    |
|-------------|----------------------------------------------|
| `WIFI_SSID` | Name deines WLANs                            |
| `WIFI_PASS` | WLAN-Passwort                                |
| `PC_HOST`   | lokale IP-Adresse deines PCs                 |
| `PC_PORT`   | Ziel-Port (Standard **3333**, muss zum Server passen) |
| `ADC_SPS`   | Abtastrate — **muss zu `CFG[1]` passen** (siehe [Abtastraten](#konfiguration--abtastraten)) |

> ⚠️ **Firewall:** Eingehende UDP-Pakete auf Port 3333 am PC erlauben, sonst
> kommen keine Daten an.

### 2. Messung durchführen

1. **Server starten:** `python pc_udp_server.py`. Er meldet
   `Warte auf UDP-Pakete an Port 3333 ...`.
2. **ESP32 einschalten/flashen.** Die LED sucht zunächst (Dauerleuchten), dann
   1 Blitz/s = verbunden.
3. **Tara abwarten:** Die Welle in den ersten ~2 Sekunden **unbelastet** und
   ruhig lassen. Der Server meldet z. B. `codeZero = -116000 (tariert über 660
   Werte)`. Dieser Nullpunkt gilt für die ganze Messung.
4. **Messung fahren:** Last aufbringen. Der Server gibt alle 100 Pakete Status
   inkl. Verlustquote aus.
5. **Beenden:** **Strg+C**. Endstatistik und CSV-Dateiname werden angezeigt.

### 3. Auswertung

```bash
python plot_dms.py dms_rot_20260706_162503.csv
# -> dms_plot.png und dms_plot.pdf
```

### Rollback / Wiederholung

Eine Messung lässt sich nicht „rückgängig“ machen — bei Fehlern (z. B. Tara auf
belasteter Welle, hoher Verlust) einfach Server neu starten (neue CSV) und die
Messung wiederholen. Alte CSV-Dateien bleiben unangetastet erhalten.

### Eskalation

- **Anhaltend hoher Paketverlust:** WLAN-Signal / Abstand / Störquellen prüfen,
  ggf. Abtastrate senken.
- **Keine Daten trotz „verbunden“:** Firewall, `PC_HOST`-IP und Subnetz prüfen.

---

## UDP-Protokoll (Referenz)

Jedes UDP-Paket besteht aus einem **20-Byte-Header** (`PktHeader`, little-endian,
gepackt) gefolgt von `count` Rohwerten à 4 Byte (`int32`, little-endian).

| Offset | Feld        | Typ      | Größe | Bedeutung                                   |
|-------:|-------------|----------|------:|---------------------------------------------|
| 0      | `magic`     | uint8    | 1 B   | Kennung, immer **0xA5**                     |
| 1      | `version`   | uint8    | 1 B   | Protokollversion, aktuell **1**             |
| 2      | `sps`       | uint16   | 2 B   | Abtastrate (für Zeitrekonstruktion am PC)   |
| 4      | `count`     | uint16   | 2 B   | Anzahl der folgenden int32-Werte            |
| 6      | `reserved`  | uint16   | 2 B   | reserviert (0)                              |
| 8      | `seq_start` | uint32   | 4 B   | Sequenznummer des 1. Samples im Paket       |
| 12     | `t_us`      | uint64   | 8 B   | Zeitstempel (µs) des 1. Samples             |
| 20     | `codes[]`   | int32[]  | 4·n B | `count` ADC-Rohwerte                        |

Das Struct-Format auf PC-Seite lautet entsprechend `"<BBHHHIQ"`.

**Verlusterkennung:** Der PC erwartet, dass `seq_start` des nächsten Pakets
gleich `seq_start + count` des vorigen ist. Jede positive Differenz zählt als
verlorene Samples. So werden sowohl im ESP32 verworfene (`dropped`) als auch auf
dem Funkweg verlorene Samples erfasst.

---

## CSV-Datenformat

Kopfzeile: `t_ms,code,microstrain`

| Spalte       | Einheit | Beschreibung                                            |
|--------------|---------|---------------------------------------------------------|
| `t_ms`       | ms      | Zeit seit erstem Sample (`t0` = 0)                      |
| `code`       | –       | ADC-Rohwert (int32, 24-Bit-vorzeichenbehaftet)          |
| `microstrain`| µε      | umgerechnete Dehnung, nullpunktbezogen                  |

Beispiel:

```csv
t_ms,code,microstrain
0.000,-116475,-0.81
3.030,-115836,0.32
6.061,-115697,0.57
```

Der Zeitabstand von ~1 ms zwischen den Zeilen entspricht der Standard-Rate
von **1000 SPS** (1/1000 s ≈ 1 ms).

---

## Umrechnung Code → Mikrostrain

Der PC-Server rechnet jeden ADC-Rohwert `c` in Mikrostrain um:

```
eps [µε] = 4 · (c − code_zero) / (K · GAIN · FS) · 1e6
```

| Symbol      | Wert / Bedeutung                                    |
|-------------|-----------------------------------------------------|
| `c`         | aktueller ADC-Rohwert                               |
| `code_zero` | tarierter Nullpunkt (Mittel der ersten 2 s)         |
| `4`         | Brückenfaktor der **Viertelbrücke**                 |
| `K`         | Gauge-Faktor des DMS, **2.06** (aus Datenblatt)     |
| `GAIN`      | PGA-Verstärkung des ADS1220, **128**                |
| `FS`        | Vollausschlag = 2²³ = **8 388 608**                 |

> Die DMS-spezifischen Parameter `K`, `GAIN` und `FS` stehen im Kopf von
> `pc_udp_server.py` und müssen zur eingesetzten Hardware passen.

---

## Konfiguration & Abtastraten

Die Abtastrate steckt im ADS1220-Registerwert **`CFG[1]`** (`main.cpp`). Sie muss
**mit `ADC_SPS` übereinstimmen**, denn dieser Wert wird im Paket-Header
mitgeschickt und dient dem PC zur Zeitrekonstruktion.

| SPS   | `CFG[1]` | Anmerkung           |
|------:|----------|---------------------|
| 20    | `0x04`   | nur hier 50/60-Hz-Filter möglich |
| 45    | `0x24`   |                     |
| 90    | `0x44`   |                     |
| 175   | `0x64`   |                     |
| 330   | `0x84`   |                     |
| 600   | `0xA4`   |                     |
| **1000**  | **`0xC4`**   |**aktuelle Einstellung** |
| 2000  | `0xD4`   | Turbo — zusätzlich `ADC_SPS = 2000` setzen |

Weitere Register (`CFG` in `main.cpp`):

- **CONFIG0 = 0x0E:** Eingänge AIN0/AIN1, Gain 128, PGA aktiv.
- **CONFIG2 = 0xC0:** Referenz AVDD, interner 50/60-Hz-Filter **aus** (`0xD0`
  schaltet ihn ein, geht aber nur bei 20 SPS).
- **CONFIG3 = 0x00.**

---

## Fehlersuche

### Status-LED (Onboard, GPIO21)

| Muster              | Bedeutung                                   |
|---------------------|---------------------------------------------|
| **Schnelles Blinken / Dauerleuchten** | WLAN-Suche, noch nicht verbunden |
| **1 Blitz pro Sekunde** | Verbunden, alles ok                      |
| **2 Blitze pro Sekunde** | Puffer lief über — Samples wurden verworfen |

### Typische Probleme

- **Keine Pakete am PC:** Firewall blockt UDP 3333; `PC_HOST` falsch; ESP32 und
  PC in unterschiedlichen Subnetzen.
- **Hoher Verlust (%):** Schlechtes WLAN / großer Abstand / Störungen; Abtastrate
  zu hoch für die Funkstrecke → niedrigere SPS wählen.
- **2 Blitze/s (Puffer-Überlauf):** Erfassung schneller als Versand — WLAN
  instabil oder Rate zu hoch; Queue (2048) reicht bei längeren Aussetzern nicht.
- **Dehnung offset-/driftbehaftet:** Tara auf belasteter oder bewegter Welle
  durchgeführt → Messung mit ruhiger, unbelasteter Startphase wiederholen.
- **Falsche µε-Werte:** `K`, `GAIN` oder `FS` in `pc_udp_server.py` passen nicht
  zur Hardware; `ADC_SPS` ≠ `CFG[1]` verzerrt die Zeitachse.

---

## Bekannte Einschränkungen

- **UDP ohne Quittung:** Verlorene Pakete werden erkannt und gezählt, aber nicht
  erneut angefordert. Für lückenlose Aufzeichnung muss die Funkstrecke stabil
  sein.
- **Zeitstempel interpoliert:** Nur das erste Sample je Paket trägt einen echten
  Zeitstempel; der Server schätzt die reale Rate zur Laufzeit 
- **`ADC_SPS` und `CFG[1]` sind manuell zu synchronisieren** — es gibt keine
  automatische Prüfung.
- **Parameter fest im Code:** WLAN-Zugang, Ziel-IP und DMS-Kalibrierung sind
  Compile-Zeit- bzw. Skript-Konstanten, keine Laufzeit-Konfiguration.
```

*Diese Dokumentation beschreibt den Stand der vorliegenden Quelldateien
(`main.cpp`, `pc_udp_server.py`, `plot_dms.py`).*
