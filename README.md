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

Oppsettet har tre roller: **controlleren** er maskinen du starter veiviseren på,
**coordinatoren** er tjenesten som fordeler jobber, og **workerne** utfører dem.
Controlleren kjører dashboard og coordinator, men blir ikke selv compute-worker.

Clusteret kan ha **1–100 workers**. Antallet oppgis ved klargjøring; IP-adresser
eller vertsnavn kan skrives enkeltvis eller limes inn som en liste. Antall og
unikhet kontrolleres før nodene kontaktes. Inntil ti noder klargjøres eller
installeres samtidig, uavhengig av clusterets totale størrelse.

### Operativsystem og første tilgang

Controller og workers kan blande Raspberry Pi OS/Debian, Ubuntu og Fedora,
på ARM (aarch64/armv7l) og x86-64. De trenger systemd og henholdsvis apt eller
dnf. Controlleren trenger Python 3.11–3.14; workerne trenger Python 3.10–3.14
etter pakkeoppsettet. Workers med Python 3.14 krever Python 3.12–3.14 på
controlleren, slik at den kan kjøre Ansible 2.20/2.21. Kombinasjonen kontrolleres
før utrulling. Se også [Ansible sin støttematrise](https://docs.ansible.com/projects/ansible/latest/reference_appendices/release_and_maintenance.html#ansible-core-support-matrix).
Bruk for eksempel Debian 13, Ubuntu 24.04 eller Fedora som controller for et
blandet cluster med nyere Fedora-workers. Eldre systemer kan kreve OS-oppgradering.

Hver node må ha nettverk, SSH aktivert og en vanlig bruker med sudo-tilgang.
Brukernavnet skal være det samme på workerne; passordene kan være forskjellige.
For helt nye workers må enten passordinnlogging over SSH være tillatt eller
koordinatorens SSH-nøkkel allerede være installert. Worker-adressene må være
stabile, for eksempel med DHCP-reservasjoner. Ingen grafisk skjerm kreves.

Alt skal være på et betrodd labnett. SSH-nøkler brukes til administrasjon;
separate API-tokens og HTTPS brukes mellom tjenestene.

### Normal installasjon: én norsk veiviser

Hent repoet på controlleren. Installer Git først hvis det mangler (`sudo apt
install git` på Debian/Ubuntu/Pi OS eller `sudo dnf install git` på Fedora):

```bash
cd ~
git clone https://github.com/Geirgutt/Pi-display-lab.git
cd Pi-display-lab
bash scripts/setup-cluster.sh
```

Startskriptet oppdager operativsystem og arkitektur, viser manglende verktøy og
tilbyr å installere dem. Ansible får et eget `.ansible-venv`. Ansible og Core
oppdateres som et kompatibelt par, mens ferdigbygde systembiblioteker gjenbrukes
for å unngå tung kompilering på Raspberry Pi. Den tidligere
kommandoen `python3 scripts/setup-cluster.py` starter også denne flyten.

Veiviseren hjelper deretter med:

1. Controller-adresse, SSH-bruker, antall workers og adresseliste.
2. Godkjenning av nye SSH-nøkkelavtrykk. Kjente endrede nøkler overskrives aldri.
3. Gjenbruk/opprettelse av SSH-nøkkel og installasjon av den offentlige nøkkelen
   på workerne. Eksisterende private nøkler og andre autoriserte nøkler beholdes.
   Automatisk opprettede clusternøkler har ingen passfrase og beskyttes med 0600.
4. Samlet innsamling av innloggingspassord og sudo-passord. Felles passord kan
   brukes, og veiviseren spør om innloggingspassordene også skal prøves til sudo.
5. Kontroll av OS, arkitektur og nodeidentitet, og installasjon av manglende
   worker-pakker over SSH, også når Python ennå ikke finnes på workeren.
6. Forslag til unike vertsnavn ved kollisjoner. Bruk IPv4-adresser for noder som
   skal få nytt vertsnavn, slik at SSH-adressen overlever navnebyttet.
7. Oppsummering og installasjon av tjenester, tokens og TLS-sertifikater.
   Aktiv firewalld/UFW på controlleren får et eget spørsmål om konkrete porter.
8. Kontroll av versjon, tjenester, TLS og kontakt med alle registrerte workers.

Klargjøring av verktøy, SSH og worker-pakker har egne bekreftelser før den
avsluttende tjenesteinstallasjonen. Ved avbrudd beholdes ferdige pakker og
SSH-nøkler, så veiviseren kan kjøres igjen. Eksisterende tokens og gyldig CA
bevares. Konfigurasjonen ligger i Git-ignorert `config.local.json`.

Controllerens sudo-tilgang holdes aktiv under oppsett og oppdatering. Passord
beholdes bare i minnet; SSH mottar dem via private pipes, og Ansible henter
sudo-passord fra en privat lokal socket som fjernes etter kjøringen. Passord
skrives ikke til config, miljøvariabler eller kommandolinjeargumenter.

### Legge til worker nummer tre – eller flere senere

Kjør samme veiviser på controlleren:

```bash
cd ~/Pi-display-lab
bash scripts/setup-cluster.sh
```

Velg **3. Legg til workers**, oppgi antall **nye** workers og adressene deres.
Med to eksisterende workers og én ny oppgir du `1` og bare den nye adressen.
De eksisterende nodene og innstillingene beholdes; du skal ikke registrere dem
på nytt. SSH og pakker klargjøres på de valgte nodene, og normalt installeres
bare de nye workerne. Hvis en eksisterende worker har en eldre kodeversjon,
spør veiviseren om også den skal oppdateres til controllerens versjon.
Etterpå kontrolleres hele clusteret. Samlet grense er fortsatt 100 workers.

Andre valg er verifisering, reinstallasjon, nettverksendringer og **6. Fjern
workers**. Velg nodene fra den nummererte listen og bekreft fjerningen. Minst
én worker må beholdes. Tilgangen til jobbkøen tilbakekalles, og statusmeldinger
fra de fjernede nodeidentitetene avvises. Du kan også velge å stoppe og deaktivere
worker- og node-agent-tjenestene på de fjernede maskinene. Utilgjengelige noder
kan fortsatt fjernes fra clusteret; tjenestene deres må da stoppes senere.
Prosjektfiler og andre tjenester slettes ikke. En node som legges til på nytt,
får nytt worker-token, og nodeidentiteten tillates igjen.
Ved mislykket tjenesteinstallasjon beholdes configen. Kjør veiviseren igjen og
velg reinstallasjon; eksisterende nøkler, pakker og sikkerhetsmateriale gjenbrukes.

Vanlige oppdateringer gjøres fortsatt med `bash scripts/update.sh`, som henter
siste Git-versjon selv. Gamle prototypefiler slettes aldri automatisk. En kjent
gammel coordinator på opptatt port tilbys stoppet etter egen bekreftelse;
ukjente prosesser stoppes ikke.

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
