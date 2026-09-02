# Pi Display Lab

Pi Display Lab er et lite læringsprosjekt for Raspberry Pi 2B+. Python samler
status fra Pi-en, gjør den om til én ryddig JSON-melding og viser meldingen som
en emulert **480 × 320 TFT-skjerm** i nettleseren.

Første versjon bruker enkel polling hvert sekund. Det er bevisst valgt i stedet
for WebSocket: løsningen blir mindre, lettere å forstå og stabil på en eldre Pi.
Senere kan samme JSON-state sendes til en fysisk ESP32-S3 uten å skrive om
målinger eller beregningslogikk.

## Dette får du

- **Home:** klokke, CPU-bruk, CPU-temperatur, RAM, CPU-frekvens, strupestatus
  og nettverksstatus.
- **Cluster:** ekte Pi-noder samt kø, aktive primtalls- og Monte Carlo-jobber,
  workers og resultathistorikk fra den separate coordinator-tjenesten.
- **Nerd:** Monte Carlo-estimat av pi med levende sirkelgrafikk for treff og bom.
- **Developer controls:** permanent nodestatus, valg av clusterkapasitet og
  oppstart av Monte Carlo- og primtallsbatcher på workerne.
- **Mock-modus:** test hele prosjektet på Windows uten Raspberry Pi.
- **Transportlag:** `BrowserTransport` virker nå, mens `Esp32Transport` er en
  trygg stub for neste etappe.

## Slik henger delene sammen

```text
Andre Pi-er → node_agent.py → heartbeat-API → NodeRegistry ─┐
                                                            │
Workers ← HTTPS GET /job ─ Cluster coordinator ─ statuscache ┤
    └─ prime_count / monte_carlo ─ POST /result              ▼
SystemMonitor ─────────────────────────────────────── DashboardState
                                                       (én felles state)
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

Disse stegene gjøres én gang etter at mappen `Pi-display-lab` er kopiert til
Pi-en, for eksempel til `/home/pi/Pi-display-lab`.

1. Logg inn på Pi-en via tastatur/skjerm eller SSH.

2. Installer Python og støtte for virtuelle miljøer:

   ```bash
   sudo apt update
   sudo apt install -y python3 python3-venv
   ```

3. Gå til prosjektmappen:

   ```bash
   cd ~/Pi-display-lab
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
cd ~/Pi-display-lab
source .venv/bin/activate
python app.py
```

## Kjør automatisk og oppdater senere

Når `.venv` og pakkene er installert, kan systemd-tjenesten opprettes automatisk:

```bash
cd ~/Pi-display-lab
bash scripts/install-service.sh
```

Skriptet bruker brukeren og prosjektstien du faktisk kjører det fra. Det starter
appen nå og ved hver senere oppstart av Raspberry Pi-en.

Kontrollpanelet sjekker automatisk GitHub ved åpning og deretter hver halvtime
mens siden står åpen. Hvis en nyere commit finnes på `origin/main`, vises lokal
og ny versjon samt en lenke der du kan kontrollere endringen på GitHub. Sjekken
er bare lesende: nettleseren kan ikke installere kode eller starte tjenesten på
nytt.

Etter at vi har pushet en ny versjon til GitHub, oppdaterer du Pi-en med:

```bash
cd ~/Pi-display-lab
bash scripts/update.sh
```

Oppdateringsskriptet:

1. stopper hvis prosjektmappen har lokale endringer
2. henter siste versjon med fast-forward-only, uten å omskrive Git-historikk
3. oppretter `.venv` hvis den mangler og oppdaterer Python-pakkene
4. starter Pi Display Lab og coordinatoren på nytt
5. oppdaterer konfigurerte workers til nøyaktig samme commit som controlleren
6. starter worker- og node-agenttjenestene på nytt og verifiserer hele clusteret

Dette er den eneste oppdateringsveien. Du bestemmer dermed selv når en kontrollert
GitHub-versjon skal installeres på Pi-en, og kommandoen må kjøres over SSH.
Hvis en eldre lokal config trenger TLS-migrering, stopper oppdateringen etter
trygg Git-oppdatering og ber deg kjøre `python3 scripts/setup-cluster.py`.

## Fra blank Raspberry Pi til fungerende cluster

Oppsettet har tre enkle roller:

- **Controller** er Raspberry Pi-en du arbeider på. Den kjører dashboardet på
  port 5000 og coordinatoren på port 5001. Den regner ikke clusterjobber i denne
  versjonen.
- **Coordinator** er den lille Flask-tjenesten på controlleren som holder køen,
  deler ut neste deljobb og tar imot resultater.
- **Worker** er en annen Raspberry Pi som spør coordinatoren etter arbeid,
  regner primtall og sender resultatet tilbake. Den sender også maskinstatus via
  node-agenten.

Alle maskinene bør kjøre Raspberry Pi OS og være på samme betrodde lokalnett.
Installasjonen bruker **SSH-nøkler** for administrasjon og Ansible. Clusterets
**API-tokens er separate credentials** som tjenestene bruker mens clusteret
kjører. HTTPS krypterer tokenene på port 5001; SSH-nøklene erstatter ikke
API-tokenene og omvendt.

Lag og kopier SSH-nøkkelen til hver worker først:

```bash
ssh-copy-id labuser@worker-01.example
ssh labuser@worker-01.example
```

Kontroller fingerprint og svar `yes` første gang. Gjenta for hver worker.
Veiviseren skrur aldri av host-key-kontrollen.

### Normal installasjon: én norsk veiviser

På controlleren:

```bash
sudo apt update
sudo apt install -y git
cd ~
git clone https://github.com/Geirgutt/Pi-display-lab.git
cd Pi-display-lab
python3 scripts/setup-cluster.py
```

Veiviseren oppdager og viser bruker, hostname, sannsynlig LAN-adresse,
prosjektmappe, Git-branch/commit, eksisterende config/tjenester og brukte porter.
Den spør bare om:

- controller-adressen workerne faktisk kan nå
- SSH-brukeren på workerne
- worker-adresse/hostname, én om gangen
- om heartbeat-token skal aktiveres (standard: ja)
- om et gammelt serversertifikat skal fornyes når adressen har endret seg
- en endelig bekreftelse før noe installeres eller endres

Før bekreftelsen utføres bare lesende kontroller av DNS/IP, godkjent SSH host
key, SSH-nøkkel, remote hostname, Python, sudo, apt-get og controller-oppslag.
Hvis host key mangler, ber veiviseren deg kjøre `ssh user@worker`. Hvis
nøkkelinnlogging mangler, bruker du `ssh-copy-id user@worker`.

Veiviseren lager den Git-ignorerte `config.local.json`, installerer avhengigheter,
lager/bevarer credentials og privat CA, installerer systemd-tjenestene og ruller
ut nøyaktig controllerens Git-commit til hver worker. Controlleren kjører bare
Pi Display Lab og coordinatoren; den blir ikke compute-worker.

Controllerens `sudo -v` spør normalt én gang. Workerne behandles sekvensielt.
Har de forskjellige sudo-passord, får hver worker sitt eget interaktive
Ansible `--ask-become-pass`-spørsmål. Passord lagres aldri i filer, miljø,
kommandolinjevariabler eller logger.

### Eksisterende installasjon og trygg migrering

```bash
cd ~/Pi-display-lab
bash scripts/update.sh
python3 scripts/setup-cluster.py
```

Når lokal config allerede finnes, tilbyr veiviseren å verifisere, reinstallere,
endre workers, endre controller/nettverk eller avbryte. Gyldige tokens og CA
bevares. En ny worker får bare sitt eget nye token. Fjerning vises og må
bekreftes før worker-tokenet trekkes tilbake.
Den fjernede maskinen slettes eller ryddes ikke automatisk; dens gamle worker-
tjeneste vil bare bli avvist av coordinatoren til du stopper den manuelt.

Gamle `~/coordinator.py` og `~/worker.py` slettes aldri automatisk. Hvis port
5001 er opptatt, vises PID, program og kommandolinje. Bare en prosess som tydelig
ser ut som den gamle manuelle `coordinator.py`, tilbys stoppet, og det krever en
egen bekreftelse. En ukjent prosess blir ikke drept.

### TLS og lokale hemmeligheter

Første installasjon oppretter en liten privat lab-CA og et coordinator-
serversertifikat med SAN for valgt controller-IP eller hostname:

```text
/etc/pi-display-lab/pki/ca.key              0600, bare controller
/etc/pi-display-lab/pki/ca.crt              offentlig CA-sertifikat
/etc/pi-display-lab/pki/coordinator.key     0600, bare controller
/etc/pi-display-lab/pki/coordinator.crt     serversertifikat
/etc/pi-display-lab/cluster-credentials.json 0600
/etc/pi-display-lab/node-heartbeat.env      0600, når aktivert
```

CA-privatnøkkelen forlater aldri controlleren. Hver worker får bare offentlig
`ca.crt`, sitt eget worker-token og eventuelt det delte heartbeat-tokenet. Pi
Display Lab beholder admin-tokenet lokalt. Klientene validerer både CA-kjeden og
at sertifikatets SAN matcher controller-adressen; det finnes ingen
`verify=False`-reserve. Ved adresseendring kan veiviseren lage bare et nytt
serversertifikat og beholde CA-en.

Dashboardet på port 5000 er fortsatt vanlig HTTP uten innlogging. Coordinator-
trafikken på port 5001 er HTTPS med Bearer-token. Begge portene er bare for et
betrodd hjem/lab-LAN og skal aldri videresendes direkte fra ruteren til
Internett.

### Verifisering og avansert installasjon

```bash
bash scripts/verify-cluster.sh
```

Verifiseringen sjekker tjenester, HTTPS-handshake, CA-kjede, hostname/IP,
health, autentisert status, appens cluster-API, SSH, worker-identitet og at alle
noder kjører samme commit. Tokens skrives ikke ut.

Avanserte brukere kan fortsatt kopiere `config.example.json` til
`config.local.json`, fylle inn lokale verdier og sette `cluster.enabled` til
`true`, og så kjøre `bash scripts/install-cluster.sh`. De lavere
preflight-, PKI-, secret-, systemd-, Ansible- og verify-verktøyene er beholdt.

### Slik kjører clusterjobben

Åpne dashboardet, fyll inn start, slutt og størrelse per deljobb under
**Primtalls-cluster**, og trykk **Start cluster-jobb**. Det tilsvarer:

```bash
curl -X POST http://127.0.0.1:5000/api/cluster/start \
  -H 'Content-Type: application/json' \
  -d '{"start":1,"end":1000000,"chunk_size":100000,"slot_limit":6,"reserve_one":true}'
```

Coordinatoren lager inkluderende intervaller, for eksempel `1–100000` og
`100001–200000`. Hver worker bruker hostname som navn og har som standard én
compute-slot per lokal CPU-kjerne. Slottene henter neste tillatte jobb med
`GET /job`, utfører CPU-arbeidet i separate prosesser og sender `POST /result`.
Workerens hostname og Bearer-token må tilhøre hverandre. Når køen er tom,
venter tjenesten med konfigurert backoff i stedet for å busy-loope.

Kø, aktive jobber og resultathistorikk ligger foreløpig bare i minnet. En omstart
av coordinatoren nullstiller dem. Det er bevisst for denne læringsversjonen.

Dashboardet henter status i bakgrunnen med kort timeout. Hvis coordinatoren er
nede, markeres Cluster-skjermen som offline uten at resten av Pi Display Lab
stopper eller blir hengende.

Coordinatorens worker- og admin-API er tokenbeskyttet, og port 5001 bruker HTTPS
med lab-CA-verifisering. Dashboardet på port 5000 har fortsatt ikke
brukerinnlogging og er ikke kryptert. Hold derfor begge portene på det betrodde
labnettet, og ikke videresend dem fra ruteren til Internett.

Status og logger kan sjekkes uten å starte Python manuelt:

```bash
systemctl status pi-display-lab
journalctl -u pi-display-lab -f
systemctl status cluster-coordinator
journalctl -u cluster-coordinator -f
ssh labuser@worker-01.example systemctl status cluster-worker
ssh labuser@worker-01.example journalctl -u cluster-worker -f
ssh labuser@worker-01.example systemctl status pi-display-node-agent
```

## Koble bare til en ekstra statusnode

Hvis en maskin bare skal vises med CPU, temperatur og RAM uten å være
cluster-worker, kan den eksisterende node-agenten fortsatt installeres manuelt.
Agenten bruker bare Python sitt standardbibliotek.

På en ekstra Raspberry Pi med vanlig Raspberry Pi OS:

```bash
sudo apt update
sudo apt install -y git python3 python3-venv
cd ~
git clone https://github.com/Geirgutt/Pi-display-lab.git
cd Pi-display-lab
python3 -m venv .venv
bash scripts/install-agent-service.sh http://HOVED-PI-IP:5000 pi3b-plus
```

Bytt `HOVED-PI-IP` med IP-adressen til Pi-en som viser dashboardet. Det siste
argumentet er nodenavnet på skjermen. Bruk 1–24 bokstaver, tall, punktum,
bindestrek eller understrek.

Agentstatus og logger:

```bash
systemctl status pi-display-node-agent
journalctl -u pi-display-node-agent -f
```

Hvis en agent ikke har sendt heartbeat på 20 sekunder, markeres noden som
offline. Etter omstart av hovedappen dukker noden opp igjen ved neste heartbeat.

## Monte Carlo og flere kjerner

Kontrollpanelet summerer kjernene på online workers. Controllerens kjerner vises
i nodestatus, men teller aldri som compute-slots. Med to firekjerners workers er
kapasiteten åtte slots. Valget **Hold én kjerne ledig per worker** reduserer den
til seks. `cluster.worker_slots` kan settes til `1`–`4` på en worker; `0` betyr
automatisk antall lokale CPU-kjerner og er den bakoverkompatible standarden.

Monte Carlo opprettes som én batch med mange `monte_carlo`-deljobber. Hver del
har samples, unik seed og batch-ID. Workerne returnerer samples og antall treff;
coordinatoren beregner `4 * total_inside / total_samples`. Nerd-skjermen viser
et lite utvalg ekte punkter: turkis betyr treff, lilla betyr bom. Alle punktene
teller, men maksimalt 720 visualiseringspunkter beholdes.

Primtall og Monte Carlo bruker samme pull-kø. En batch med slot-grense 4 kan ha
inntil fire deljobber aktive på tvers av alle workers, selv om clusteret har åtte
ledige slots. Dermed får raske slots mer arbeid uten statisk halvdeling mellom
maskinene, samtidig som hver batch respekterer valgt kapasitet.

Node-agenten rapporterer maskinstatus, mens `cluster_worker.py` henter og utfører
jobbchunks. De er separate, små tjenester og kan kjøre samtidig på samme Pi.

## CPU-frekvens og struping

Appen leser gjeldende CPU-frekvens fra Linux sitt `cpufreq`-grensesnitt og
bruker `vcgencmd` som reserve. Raspberry Pi sitt `get_throttled`-bitfelt dekodes
til en tydelig status på Home- og Nerd-skjermen:

- turkis: ingen registrert struping (`0x0`)
- gul: underspenning, struping eller temperaturgrense har forekommet tidligere
- rød: problemet er aktivt akkurat nå, for eksempel `0x50005`

Cluster-visningen viser også frekvens og et `THROTTLE`- eller `HISTORY`-merke
for oppdaterte nodeagenter. Gamle agenter fortsetter å virke, men viser status
som utilgjengelig frem til `node_agent.py` er oppdatert og tjenesten restartet:

```bash
sudo systemctl restart pi-display-node-agent
```

### Valgfritt delt token

På et betrodd labnett kan heartbeat-API-et brukes uten token. For ekstra vern
setter du dette i `config.local.json` før cluster-installasjonen:

```json
"node_heartbeat_auth": true
```

Installasjonen genererer da tokenet lokalt og legger det i
`/etc/pi-display-lab/node-heartbeat.env` på controller og workers med modus
`0600`. Tokenet hardkodes ikke i systemd-enheten. Ved en helt manuell
node-agentinstallasjon støttes fortsatt `PI_DISPLAY_NODE_TOKEN` i
`/etc/default/pi-display-lab` og `/etc/default/pi-display-lab-agent`. Disse
filene ligger utenfor repoet og skal aldri committes.

### Raspberry Pi med Home Assistant

Hvis Home Assistant kjører i Docker eller Supervised på vanlig Raspberry Pi OS,
kan agenten normalt kjøres på vertssystemet ved siden av Home Assistant. På
Home Assistant OS bør vi ikke installere dette skriptet direkte. Der lager vi
senere en liten Home Assistant-integrasjon, add-on eller MQTT/REST-automatisering
som sender de samme heartbeat-feltene. API-formatet er allerede klart for det.

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
| `POST` | `/api/demo/start` | Starter clusterberegning med f.eks. `{"samples":50000000,"slot_limit":6,"reserve_one":true}` |
| `POST` | `/api/nodes/heartbeat` | Registrerer status fra en ekstern Pi-agent |
| `GET` | `/api/cluster-jobs` | Henter jobbstatus fra konfigurert cluster coordinator |
| `POST` | `/api/cluster/start` | Deler et primtallsintervall i cluster-jobber |
| `POST` | `/api/cluster/cancel/<batch_id>` | Avbryter en aktiv clusterbatch |
| `GET` | `/api/update/status` | Viser lokal og eventuell tilgjengelig versjon |
| `POST` | `/api/update/check` | Henter oppdatert status fra `origin/main` |
| `GET` | `/api/protocol/example` | Gir en kort eksempelmelding for ESP32-testing |

Coordinator-tjenesten på porten fra lokal config har et lite API. Pi Display Lab
og workertjenestene legger credentials i HTTP-headere automatisk; nettleseren får
aldri admin-tokenet:

| Metode | Adresse | Credential | Hva den gjør |
|---|---|---|---|
| `GET` | `/health` | ingen | Sjekker at coordinatoren lever |
| `GET` | `/job` | worker | Tar neste jobb; tom kø gir HTTP 204 |
| `POST` | `/result` | worker | Registrerer jobbresultat for samme worker-identitet |
| `GET` | `/status` | admin | Viser kø, aktive jobber og resultathistorikk |
| `POST` | `/jobs` | admin | Oppretter chunks for ett primtallsintervall |
| `POST` | `/batches/<batch_id>/cancel` | admin | Fjerner ventende chunks og avbryter batchen |

Når en batch avbrytes, fjernes alle chunks som fortsatt venter i køen med én
gang. Chunks som allerede beregnes får fullføre lokalt; resultatene deres
registreres som avbrutt, og workeren går videre uten å prøve resultatet på nytt.

Ett startkall kan lage maksimalt 10 000 chunks. Det kan være maksimalt 20 000
ventende/aktive chunks samtidig. Et intervall kan dekke opptil 100 000 000 tall,
og høyeste tillatte sluttverdi er 1 000 000 000. Dette er romslig for lange
Raspberry Pi-forsøk, men stopper åpenbart feilaktige eller ekstreme verdier.

Kjernen i protokollen er liten og versjonert:

```json
{
  "protocol_version": 1,
  "screen": "home",
  "time": "12:34:56",
  "nodes": [
    {
      "id": "pi3-office",
      "name": "Pi2",
      "model": "Raspberry Pi 3 Model B Plus",
      "cpu": 42.0,
      "temp": 51.2,
      "ram": 48.0,
      "cores": 4,
      "online": true,
      "kind": "remote"
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
| `cluster_coordinator.py` | Separat Flask-app med `/job`, `/result` og `/status` |
| `cluster_jobs.py` | Trådsikker batchkø, slot-grenser og begge beregningstypene |
| `cluster_worker.py` | Fyller lokale prosess-slots og sender autentiserte resultater |
| `cluster_client.py` | Kort HTTPS-klient og bakgrunnscache for dashboardet |
| `cluster_tls.py` / `cluster_pki.py` | Verifisert TLS og privat lab-CA |
| `cluster_auth.py` | Leser lokale credentials og binder token til riktig rolle/worker |
| `config.py` | Validerer lokal config og gir sikre standardverdier |
| `display_state.py` | Leser sensorer, holder noderegister og bygger felles dashboard-state |
| `node_agent.py` | Sender systemmålinger fra en ekstra Raspberry Pi |
| `scripts/setup-cluster.py` | Norsk veiviser og normal installasjonsvei |
| `scripts/` | Lavnivåverktøy for installasjon, PKI, verifisering og oppdatering |
| `ansible/` | Ruller worker-kode og tjenester ut over eksisterende SSH-nøkler |
| `updates.py` | Sjekker `origin/main` og lager lenke til en tilgjengelig commit |
| `transports.py` | Felles `DeviceTransport`, nettlesertransport og ESP32-stub |
| `templates/index.html` | Selve nettsidens struktur |
| `static/app.js` | Henter state og tegner de tre skjermbildene |
| `static/style.css` | Farger, TFT-ramme, layout og responsiv skalering |
| `tests/` | Små kontroller av API, beregningsjobb og transportlag |
| `requirements.txt` | Den eneste Python-avhengigheten: Flask |

## Lisens

Prosjektet er tilgjengelig under [MIT-lisensen](LICENSE). Det betyr kort sagt
at andre kan bruke, endre og dele koden, også i kommersielle prosjekter, så
lenge lisens- og opphavsmerknaden følger med. Programvaren leveres uten garanti.

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
- **Legg til en Pi:** kjør `scripts/install-agent-service.sh` på den nye noden.
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

Testene sjekker blant annet jobbkø, tom kø, resultatregistrering, coordinator-
status, worker-beregning, lokal config, utilgjengelig coordinator, cluster-start,
heartbeat, kjernegrenser, transportlaget og Monte Carlo-jobben.

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
