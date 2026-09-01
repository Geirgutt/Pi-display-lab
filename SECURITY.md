# Sikkerhet og offentlig publisering

Dette repoet er offentlig. Kildekode, dokumentasjon og eksempeldata må derfor
behandles som offentlig informasjon fra det øyeblikket de committes.

## Nettverksmodell

Pi Display Lab er laget for et **betrodd hjemmenett eller labnett**:

- port **5000** viser dashboardet og appens API. Dashboardet har ikke
  brukerinnlogging, og en klient på nettverket kan blant annet starte en
  avgrenset primtallsjobb via appen
- port **5001** er cluster coordinator. `/health` er åpen, mens worker- og
  admin-endepunktene krever Bearer-token
- port 5000 og 5001 skal aldri videresendes direkte fra ruteren til Internett
- firewall- og routerregler endres ikke automatisk av installasjonen

Workerne har hvert sitt tilfeldige token. Det tokenet gir bare adgang til å
hente jobb og sende resultat for workerens eget hostname. Pi Display Lab bruker
et separat admin/controller-token for å lese coordinator-status og opprette
jobber. Worker-token kan ikke opprette jobber eller lese coordinator-status.

Clusteret bruker foreløpig vanlig HTTP. Autentisering hindrer at en ukjent node
enkelt kan melde seg inn, men Bearer-tokenene er **ikke kryptert under transport**.
En angriper som kan avlytte lokalnettet, kan derfor se og gjenbruke dem. Bruk et
separat/betrodd LAN; legg eventuelt HTTPS, TLS-terminering eller VPN foran senere
hvis trusselmodellen krever det.

## Lokale credentials

Installasjonen lager tokens lokalt med Python-modulen `secrets`. Standardfilen
er `/etc/pi-display-lab/cluster-credentials.json` med modus `0600`, eid av den
vanlige tjenestebrukeren:

- controlleren har admin-token og koblingen mellom worker-hostname og token
- hver worker har bare sin egen worker-identitet og sitt eget token
- workerne får aldri admin-token eller andre workeres token

Den valgfrie heartbeat-beskyttelsen bruker
`/etc/pi-display-lab/node-heartbeat.env`, også med modus `0600`. Den eksisterende
manuelle mekanismen med `/etc/default/pi-display-lab` og
`/etc/default/pi-display-lab-agent` støttes fortsatt.

Credential-filene ligger utenfor repoet. Midlertidige installerfiler opprettes i
en privat temp-mappe og slettes når scriptet avsluttes. Ansible skjuler oppgaver
som behandler tokeninnhold med `no_log: true`.

`.gitignore` reduserer faren for feil, men er ikke en sikkerhetsgrense. Kontroller
filrettigheter og Git-status selv.

## Dette skal aldri committes

- passord, PIN-koder, API-nøkler, tokens eller GitHub-legitimasjon
- private SSH-nøkler, sertifikatnøkler eller gjenopprettingskoder
- Wi-Fi-navn og Wi-Fi-passord, for eksempel i `wpa_supplicant.conf`
- ekte `.env`-filer, `config.local.json` eller genererte credential-filer
- private IP-oppsett, private vertsnavn, e-postadresser eller unødvendige
  personopplysninger
- lokale Ansible-inventories med de virkelige labmaskinene
- logger og skjermbilder før de er kontrollert for sensitiv informasjon

Bruk dokumentasjonsadresser som `192.0.2.42` og generiske navn som
`controller.example`, `worker-01.example` og `labuser` i offentlige eksempler.

## Før hver commit og push

1. Kjør `git status` og kontroller alle filer som skal bli med.
2. Kjør `git diff --staged` og les hele endringen.
3. Søk etter `password`, `secret`, `token`, `api_key`, `BEGIN PRIVATE KEY` og
   egne lokale adresser/vertsnavn.
4. Kontroller spesielt config, inventory, logger, bilder og skjermbilder.
5. Hold lokale credentials utenfor prosjektmappen når det er praktisk.

En fil som allerede er lagt til i Git, beskyttes ikke av en senere
`.gitignore`-regel.

## Hvis en hemmelighet blir committet

Ikke stol på at det holder å slette filen i en ny commit. Anta at hemmeligheten
er kopiert: deaktiver eller roter den først. Rens Git-historikken bare etter en
bevisst, manuell vurdering; installasjons- og oppdateringsscriptet omskriver aldri
Git-historikk automatisk.

## Andre avgrensninger

- Jobbkø og resultater ligger bare i minnet og forsvinner ved coordinator-restart.
- Det finnes foreløpig ikke lease/requeue, failover, rate limiting eller TLS.
- Dashboardets API på port 5000 har ressursgrenser, men ikke brukerinnlogging.
- Oppdateringer skjer bare når brukeren kjører `scripts/update.sh` over SSH.
  Nettleseren kan sjekke versjon, men aldri installere en oppdatering.
