/*
 * ADS1220 WLAN-Sensorknoten - HOCHRATE / rotierende Welle
 * Board: Seeed XIAO ESP32S3 (dual-core)  |  ADC: BB-ADS1220 (Olimex)
 *
 * - hohe Abtastrate (Standard 1000 SPS, optional 2000 SPS Turbo)
 * - acqTask (Core 1): DRDY-Interrupt -> ADC lesen -> Sequenznr. + us-Zeitstempel -> Queue
 * - netTask (Core 0): bündelt Samples binär und sendet sie per UDP an den PC
 * - Status-LED auf der Onboard-LED (GPIO21, active LOW):
 *     schnelles Blinken = WLAN-Suche
 *     1 Blitz/s        = verbunden, alles ok
 *     2 Blitze/s       = Puffer lief über (Samples verworfen)
 *
 * PC-Seite: pc_udp_server.py  (dekodiert, zählt Paketverlust, schreibt CSV).
 */

#include <Arduino.h>
#include <SPI.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include "esp_timer.h"

// ===== ANPASSEN =====
#define WIFI_SSID  "XXXXXXXXXX"
#define WIFI_PASS  "XXXXXXXXXX"
#define PC_HOST    "192.168.0.3"    // lokale IP deines PCs 
#define PC_PORT    3333
#define ADC_SPS    1000                 // muss zu CFG[1] passen (siehe Zeile 50)
// ====================

// ---------- Pins ----------
#define PIN_CS    D0
#define PIN_DRDY  D1
#define PIN_SCK   D8
#define PIN_MISO  D9
#define PIN_MOSI  D10
#define LED_PIN   LED_BUILTIN           // XIAO ESP32S3: GPIO21, active LOW
#define LED_ON    LOW
#define LED_OFF   HIGH

// ---------- ADS1220 ----------
#define CMD_RESET 0x06
#define CMD_START 0x08
#define CMD_WREG  0x40
// CONFIG0: AIN0/AIN1, Gain 128, PGA an
// CONFIG1: Datenrate + Mode + kontinuierlich
//          20 Hz (0x04), 45 Hz (0x24), 90 Hz (0x44), 175 Hz (0x64), 330 Hz (0x84), 600 Hz (0xA4), 1000 Hz (0xC4), 2000 Hz (0xD4)
//          (bei Turbo zusaetzlich ADC_SPS oben auf 2000 setzen)
// CONFIG2: Ref = AVDD, 0xC0 interner 50/60-Hz-Filter ausgeschaltet, 0xD0 50/60-Hz-Filter eingeschaltet(geht nur bei 20 SPS)
// CONFIG3: 0x00
const uint8_t CFG[4] = { 0x0E, 0xC4, 0xC0, 0x00 };

// ---------- Datenstrukturen ----------
struct Sample { uint32_t seq; uint64_t t_us; int32_t code; };

struct __attribute__((packed)) PktHeader {
  uint8_t  magic;       // 0xA5
  uint8_t  version;     // 1
  uint16_t sps;         // Abtastrate (Zeitrekonstruktion am PC)
  uint16_t count;       // Anzahl int32-codes danach
  uint16_t reserved;
  uint32_t seq_start;   // Sequenznr. des 1. Samples im Paket
  uint64_t t_us;        // Zeitstempel (us) des 1. Samples
};  // 20 Byte

QueueHandle_t  sampleQ;
TaskHandle_t   acqHandle = NULL;
WiFiUDP        udp;
volatile uint32_t dropped = 0;
volatile bool  g_wifiOk = false;

SPISettings spiCfg(4000000, MSBFIRST, SPI_MODE1);

static const uint16_t BATCH_MAX = 200;   // Sicherheitsgrenze (Paket < MTU)
static const uint32_t BATCH_MS  = 100;    // max. Sammelfenster -> begrenzt Latenz

// ================= ADC =================
void adcCommand(uint8_t cmd) {
  SPI.beginTransaction(spiCfg);
  digitalWrite(PIN_CS, LOW); SPI.transfer(cmd); digitalWrite(PIN_CS, HIGH);
  SPI.endTransaction();
}
void adcWriteConfig() {
  SPI.beginTransaction(spiCfg);
  digitalWrite(PIN_CS, LOW);
  SPI.transfer(CMD_WREG | (0 << 2) | (4 - 1));
  for (int i = 0; i < 4; i++) SPI.transfer(CFG[i]);
  digitalWrite(PIN_CS, HIGH);
  SPI.endTransaction();
}
int32_t adcReadData() {
  SPI.beginTransaction(spiCfg);
  digitalWrite(PIN_CS, LOW);
  uint8_t b0 = SPI.transfer(0), b1 = SPI.transfer(0), b2 = SPI.transfer(0);
  digitalWrite(PIN_CS, HIGH);
  SPI.endTransaction();
  int32_t raw = ((int32_t)b0 << 16) | ((int32_t)b1 << 8) | b2;
  if (raw & 0x00800000) raw |= 0xFF000000;
  return raw;
}

// ================= Erfassung (Core 1) =================
void IRAM_ATTR drdyISR() {
  BaseType_t hpw = pdFALSE;
  vTaskNotifyGiveFromISR(acqHandle, &hpw);
  portYIELD_FROM_ISR(hpw);
}
void acqTask(void *) {
  uint32_t seq = 0;
  for (;;) {
    if (ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(1000)) == 0) continue;
    Sample s;
    s.code = adcReadData();
    s.t_us = (uint64_t)esp_timer_get_time();
    s.seq  = seq++;                                  // zaehlt JEDES erfasste Sample
    if (xQueueSend(sampleQ, &s, 0) != pdTRUE) dropped++;  // Luecke wird am PC sichtbar
  }
}

// ================= Netzwerk / UDP (Core 0) =================
void netTask(void *) {
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.setSleep(false);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  udp.begin(4210);                                   // lokaler Port (nur Senden)

  static uint8_t pkt[1500];
  Sample s;
  uint32_t lastTry = millis();
  for (;;) {
    if (WiFi.status() != WL_CONNECTED) {
      g_wifiOk = false;
      if (millis() - lastTry > 8000) {          // erst nach 8 s einen neuen Versuch
        WiFi.begin(WIFI_SSID, WIFI_PASS);
        lastTry = millis();
      }
      vTaskDelay(pdMS_TO_TICKS(200));
      continue;
    }
    g_wifiOk = true;

  if (!g_wifiOk) {
      // Daten der Verbindungsphase verwerfen
      xQueueReset(sampleQ);
      dropped = 0;
      g_wifiOk = true;
    }
    
    if (xQueueReceive(sampleQ, &s, pdMS_TO_TICKS(100)) != pdTRUE) continue;

    PktHeader *h = (PktHeader *)pkt;
    uint8_t   *pl = pkt + sizeof(PktHeader);
    uint16_t   n  = 0;
    uint32_t   seqStart = s.seq;
    uint64_t   tStart   = s.t_us;
    memcpy(pl + 4 * n, &s.code, 4); n++;

    uint32_t tb = millis();
    while (n < BATCH_MAX && (millis() - tb) < BATCH_MS) {
      if (xQueueReceive(sampleQ, &s, pdMS_TO_TICKS(5)) == pdTRUE) {
        memcpy(pl + 4 * n, &s.code, 4); n++;
      }
    }

    h->magic = 0xA5; h->version = 1; h->sps = ADC_SPS;
    h->count = n; h->reserved = 0; h->seq_start = seqStart; h->t_us = tStart;

    udp.beginPacket(PC_HOST, PC_PORT);
    udp.write(pkt, sizeof(PktHeader) + 4 * n);
    udp.endPacket();
  }
}

// ================= Setup =================
void setup() {
  Serial.begin(115200);
  pinMode(LED_PIN, OUTPUT); digitalWrite(LED_PIN, LED_OFF);
  pinMode(PIN_CS, OUTPUT);  digitalWrite(PIN_CS, HIGH);
  pinMode(PIN_DRDY, INPUT);
  SPI.begin(PIN_SCK, PIN_MISO, PIN_MOSI);

  adcCommand(CMD_RESET); delay(1);
  adcWriteConfig();      delay(1);
  adcCommand(CMD_START);
  delay(5);                                          // erste Wandlung verwerfen lassen

  sampleQ = xQueueCreate(2048, sizeof(Sample));      // grosszuegiger Puffer
  xTaskCreatePinnedToCore(acqTask, "acq", 4096, NULL, 3, &acqHandle, 1);  // Core 1
  xTaskCreatePinnedToCore(netTask, "net", 8192, NULL, 2, NULL,       0);  // Core 0
  attachInterrupt(digitalPinToInterrupt(PIN_DRDY), drdyISR, FALLING);
}

// ================= Status-LED (laeuft im loopTask, Core 1) =================
void loop() {
  uint32_t now = millis();
  bool led;
  if (!g_wifiOk) {
    led = true;                            // Dauerleuchten bei WLAN-Suche
  } else {
    uint32_t ph = now % 1000;
    if (dropped == 0) led = (ph < 60);                // 1 Blitz/s = ok
    else              led = (ph < 60) || (ph >= 150 && ph < 210);  // 2 Blitze/s = Verlust
  }
  digitalWrite(LED_PIN, led ? LED_ON : LED_OFF);
  vTaskDelay(pdMS_TO_TICKS(5));
}
