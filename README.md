# Pi Display Lab

Pi Display Lab er et lite læringsprosjekt for Raspberry Pi 2B+. Python samler
status fra Pi-en, gjør den om til én ryddig JSON-melding og viser meldingen som
en emulert **480 × 320 TFT-skjerm** i nettleseren.

Første versjon bruker enkel polling hvert sekund. Det er bevisst valgt i stedet
for WebSocket: løsningen blir mindre, lettere å forstå og stabil på en eldre Pi.
Senere kan samme JSON-state sendes til en fysisk ESP32-S3 uten å skrive om
målinger eller beregningslogikk.

## Dette får du

- **Home:** klokke, CPU-bruk, CPU-temperatur, RAM og nettverksstatus.
- **Cluster:** fire nodeplasser med load-bars. Første node er Pi-en; resten er
  eksempeldata så lenge du bare har én maskin.
- **Nerd:** Monte Carlo-estimat av pi med fremdrift, runtime og resultat.
- **Developer controls:** bytt skjerm, velg jobbens størrelse og start demoen.
- **Mock-modus:** test hele prosjektet på Windows uten Raspberry Pi.
- **Transportlag:** `BrowserTransport` virker nå, mens `Esp32Transport` er en
  trygg stub for neste etappe.

## Slik henger delene sammen

```text
SystemMonitor + MonteCarloDemo
             │
             ▼
       DashboardState       (én felles state)
             │
             ▼
         TransportHub
          ┌──┴───────────────┐
          ▼                  ▼
 BrowserTransport    Esp32Transport (senere MQTT)
          │
          ▼
  Flask API → nettleser → TFT-renderer
```

Kort forklart:

- **Backend** er Python-programmet som måler, beregner og svarer nettleseren.
- **Frontend** er HTML, CSS og JavaScript som tegner det du ser.
- **API** er avtalte nettadresser der frontend henter eller endrer state.
- **Transportlag** er adapteren som leverer den samme state-meldingen til en
  nettleser nå og en ESP32 senere.

Forretningslogikken ligger derfor ikke i HTML-en. Nettleseren er bare en
renderer som mottar state og tegner riktig skjerm.

## Start på Raspberry Pi OS Lite

Disse stegene gjøres én gang etter at mappen `pi-display-lab` er kopiert til
Pi-en, for eksempel til `/home/pi/pi-display-lab`.

1. Logg inn på Pi-en via tastatur/skjerm eller SSH.

2. Installer Python og støtte for virtuelle miljøer:

   ```bash
   sudo apt update
   sudo apt install -y python3 python3-venv
   ```

3. Gå til prosjektmappen:

   ```bash
   cd ~/pi-display-lab
   ```

4. Lag et isolert Python-miljø. Dette holder prosjektets pakker adskilt fra
   resten av Raspberry Pi OS:

   ```bash
   python3 -m venv .venv
   ```

5. Aktiver miljøet og installer Flask:

   ```bash
   source .venv/bin/activate
   python -m pip install -r requirements.txt
   ```

6. Start appen:

   ```bash
   python app.py
   ```

Det er hele startkommandoen etter oppsettet. La terminalvinduet stå åpent mens
appen kjører. Stopp den senere med `Ctrl+C`.

Neste gang holder dette:

```bash
cd ~/pi-display-lab
source .venv/bin/activate
python app.py
```

## Finn Pi-ens IP og åpne fra Windows

Mens appen kjører, åpner du en ny SSH-økt/terminal på Pi-en og skriver:

```bash
hostname -I
```

Resultatet kan for eksempel se ut som `192.0.2.42` (adressen her er bare en
plassholder). På Windows-PC-en, som må være på samme nettverk, åpner du da:

```text
http://192.0.2.42:5000
```

Bruk din faktiske adresse. `127.0.0.1` virker bare på maskinen der appen kjører.

Prosjektet har ikke innlogging. Bruk det på et hjemmenett/labnett du stoler på,
og ikke åpne port 5000 direkte mot internett.

## Før repoet gjøres offentlig

Repoet er laget for å kunne være offentlig, men ikke legg inn passord, tokens,
private nøkler, Wi-Fi-oppsett, ekte `.env`-filer eller private logger og
skjermbilder. Kontroller alltid `git status` og `git diff --staged` før push.

Se [SECURITY.md](SECURITY.md) for sjekklisten, regler for lokale
hemmeligheter og hva du må gjøre hvis noe sensitivt blir committet ved et uhell.

## Test på Windows med mock-data

Åpne PowerShell i prosjektmappen og kjør:

```powershell
py -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe app.py --mock
```

Åpne deretter [http://127.0.0.1:5000](http://127.0.0.1:5000). Mock-modusen viser
bevegelige, men falske sensorverdier. Du kan også bruke mock-modus på Pi:

```bash
python app.py --mock
```

## API og meldingsformat

Nyttige adresser:

| Metode | Adresse | Hva den gjør |
|---|---|---|
| `GET` | `/api/health` | Sjekker at backend lever |
| `GET` | `/api/state` | Returnerer hele gjeldende display-state |
| `POST` | `/api/screen` | Bytter skjerm med f.eks. `{"screen":"cluster"}` |
| `POST` | `/api/demo/start` | Starter beregning med f.eks. `{"iterations":1000000}` |
| `GET` | `/api/protocol/example` | Gir en kort eksempelmelding for ESP32-testing |

Kjernen i protokollen er liten og versjonert:

```json
{
  "protocol_version": 1,
  "screen": "home",
  "time": "12:34:56",
  "nodes": [
    {
      "name": "Pi2",
      "cpu": 42.0,
      "temp": 51.2,
      "ram": 48.0,
      "online": true
    }
  ],
  "network": {
    "online": true,
    "ip": "192.0.2.42"
  },
  "message": "Ready"
}
```

Backend sender en komplett state hver gang, ikke bare små endringer. Det bruker
litt flere bytes, men gjør mottakeren mye enklere og mer robust. En ESP32 kan
alltid tegne siste melding uten å måtte huske en lang historikk.

## Filene og hvorfor de finnes

| Fil | Rolle |
|---|---|
| `app.py` | Starter Flask og definerer API-adressene |
| `display_state.py` | Leser sensorer, holder valgt skjerm og kjører pi-demoen |
| `transports.py` | Felles `DeviceTransport`, nettlesertransport og ESP32-stub |
| `templates/index.html` | Selve nettsidens struktur |
| `static/app.js` | Henter state og tegner de tre skjermbildene |
| `static/style.css` | Farger, TFT-ramme, layout og responsiv skalering |
| `tests/` | Små kontroller av API, beregningsjobb og transportlag |
| `requirements.txt` | Den eneste Python-avhengigheten: Flask |

## Enkle steder å eksperimentere

Ta én liten endring av gangen, lagre filen og oppdater nettleseren:

- **Bytt farger:** øverst i `static/style.css` finner du `--cyan`, `--amber`,
  `--violet` og bakgrunnsfargene.
- **Endre overskrifter:** `templates/index.html` inneholder teksten rundt den
  emulerte skjermen. Tekst inni TFT-en ligger i renderer-funksjonene i
  `static/app.js`.
- **Flytt elementer:** søk etter `.metrics-grid`, `.cluster-grid` eller
  `.nerd-layout` i `static/style.css`.
- **Endre polling:** `POLL_INTERVAL_MS` øverst i `static/app.js`. `1000` betyr
  1000 millisekunder, altså ett sekund.
- **Legg til sensor:** les verdien i `SystemMonitor`, legg den i
  `DashboardState.snapshot()`, og vis den til slutt i ønsket renderer i
  `static/app.js`.
- **Endre mock-noder:** listen `nodes` i `DashboardState.snapshot()` i
  `display_state.py`.
- **Gjør demoen tyngre/lettere:** alternativene i `templates/index.html`.

Den rekkefølgen ved en ny sensor er viktig: **mål → legg i JSON → tegn**. Det er
samme mønster en fysisk skjerm skal bruke.

## Plan for ekte ESP32-S3

Anbefalt hovedretning er **MQTT** med Mosquitto på Pi-en.

Hvorfor MQTT passer godt her:

- ESP32-biblioteker har god støtte for MQTT og automatisk reconnect.
- Pi og ESP32 blir løst koblet; nettleseren fortsetter selv om ESP32 er av.
- En `retained` melding gjør at ESP32 får siste state straks den kobler til.
- Meldingen er liten, og MQTT gir lite ekstra arbeid for en Pi 2B+.

Foreslått topic:

```text
pilab/display/state
```

`Esp32Transport` i `transports.py` kan allerede kode payloaden som kompakt JSON,
men den er deaktivert og sender ingenting i denne versjonen.

TODO for neste etappe:

1. Installer Mosquitto på Pi og opprett en lokal bruker/passord.
2. Legg til det lette Python-biblioteket `paho-mqtt`.
3. Koble en MQTT-publish-funksjon til `Esp32Transport` og bruk retained message.
4. Test først meldingen med en MQTT-klient på PC.
5. Lag ESP32-S3-firmware som kobler til Wi-Fi og abonnerer på topicet.
6. Parse `protocol_version`, `screen`, `nodes`, `network`, `demo` og `message`.
7. Lag tre ESP32-renderere som tilsvarer nettleserens tre renderere.
8. Legg til reconnect, «ingen data»-skjerm og tidsstempelkontroll.

Andre muligheter er WebSocket, rå TCP eller USB-serial. WebSocket er fint for
direkte kontakt, og serial er fint ved skrivebordet, men MQTT er mest fleksibelt
når skjermen senere skal stå trådløst et annet sted i huset.

## Kjør testene

Med det virtuelle miljøet aktivt:

```bash
python -m unittest discover -s tests -v
```

Testene sjekker startsiden, protokollfeltene, skjermbytte, feil skjermnavn,
transportlaget og at Monte Carlo-jobben faktisk fullføres med et fornuftig
estimat.

## Vanlige problemer

- **`python: command not found`:** prøv `python3 app.py` på Pi.
- **Port 5000 er opptatt:** start med `python app.py --port 5050` og åpne port
  5050 i nettleseren.
- **Temperaturen viser `—`:** systemet fant ikke Linux-filen for temperatur.
  Resten av appen skal fortsatt fungere.
- **Windows finner ikke `py`:** installer Python fra python.org og huk av for
  «Add Python to PATH» under installasjonen.
- **PC-en finner ikke Pi:** sjekk at begge er på samme nettverk, og kontroller
  IP-adressen på nytt med `hostname -I`.
