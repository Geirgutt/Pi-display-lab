# Spotify på DeskDisplay

Controlleren henter avspillingsstatus og utfører spill/pause, neste og forrige
gjennom Spotify Web API. ESP32-en mottar bare kompakt visningsdata over den
eksisterende PSK/TLS-forbindelsen. Tokenverdier sendes aldri til skjermen eller
status-API-et. For spor med et lite albumomslag viser displayet bildet sammen
med sporet og lenken til det i Spotify. Controlleren holder bare det sist
hentede omslaget i minnet.

## Engangsoppsett på Raspberry Pi-controlleren

Du trenger Spotify Premium og din egen app i
[Spotify Developer Dashboard](https://developer.spotify.com/dashboard).
Velg Web API, og legg til denne nøyaktige Redirect URI-en:

```text
http://127.0.0.1:8888/callback
```

Oppsettet bruker Authorization Code med PKCE. Bare Client ID trengs;
Client Secret skal ikke kopieres inn i prosjektet.

Installer først denne revisjonen av controlleren, gatewayen og secure-firmwaren
med prosjektets vanlige oppdateringsløp. Oppsettsskriptet bruker bare Pythons
standardbibliotek og trenger ingen ny pip-pakke.

Åpne en terminal på PC-en og koble til **controlleren**, med lokal portviderekobling.
Bytt ut `BRUKER` og `CONTROLLER` med samme bruker og adresse som du vanligvis
bruker til Pi-en:

```sh
ssh -o ExitOnForwardFailure=yes -L 8888:127.0.0.1:8888 BRUKER@CONTROLLER
```

Kjør deretter på Pi-en, som **samme bruker som pi-display-lab-tjenesten**, uten sudo:

```sh
cd ~/Pi-display-lab
python3 meny.py
```

Velg **Konfigurasjon → Koble til / fornye Spotify**.
Hvis prosjektet ligger et annet sted, bruk den faktiske prosjektmappen. Tast inn
Client ID når du blir spurt. Åpne lenken skriptet skriver ut i nettleseren på
PC-en og godkjenn tilgangen hos Spotify. Behold SSH-vinduet åpent til terminalen
bekrefter at tilgangen er lagret. Callback-serveren kjører på Pi-en og lytter kun
på 127.0.0.1; SSH-tunnelen fører nettleserens lokale returadresse dit.

Tokenene lagres atomisk med filmodus 0600 i:

```text
~/.local/state/pi-display-lab/spotify.credentials.json
```

Tjenesten oppdager filen automatisk; omstart er ikke nødvendig. Med en alternativ
fil må `--credentials /full/sti` til oppsettet og miljøvariabelen
`PI_DISPLAY_SPOTIFY_CREDENTIALS` i tjenesten peke på samme fil. Ikke legg
tokenfilen i Git eller del innholdet. Standardfilnavnet er også ignorert av Git.

Start musikk på mobil, PC eller en Spotify Connect-enhet, og åpne **Menu → Spotify**
på skjermen. Normal status hentes omtrent hvert tiende sekund.
Spotify-data sendes til skjermen ved hver gateway-runde, uavhengig av antall
cluster-sider. Etter en kommando hentes status på nytt; skjermen viser
`Updating playback...` og sperrer nye trykk til statusen er avklart. PC-en og
SSH-tunnelen kan lukkes når oppsettet er fullført.

## Utløp og feil

- Access-tokenet fornyes automatisk før det utløper.
- Refresh-tokenet varer 180 dager fra godkjenningen. Automatisk fornyelse
  forlenger ikke denne perioden. Skjermen viser `Reconnect Spotify on the Pi`
  når Spotify avviser refresh-tokenet. Kjør samme oppsett igjen.
- `Start Spotify on a device`: åpne Spotify og start avspilling på ønsket enhet.
- `Spotify access denied`: kontroller Premium, godkjente testbrukere i appens
  utviklermodus og tilgangen du godkjente. Kjør oppsettet på nytt ved behov.
- `Spotify request limit; waiting`: controlleren respekterer Spotifys Retry-After.
- `Controller disconnected`: knappene deaktiveres til forbindelsen er tilbake.
- Returadressen åpnes ikke: kontroller SSH-tunnelen, at lokal port 8888 er ledig,
  at Pi-skriptet fortsatt venter, og at Redirect URI-en er identisk i Spotify.

**+ Like** legger sporet som vises til i Likte sanger. Kjør Spotify-oppsettet på
nytt hvis det allerede var koblet til før likerknappen ble innført, slik at du
kan godkjenne den ekstra tillatelsen til å lagre spor i biblioteket.

Kommandoer er begrenset til navngitte handlinger, sendes over autentisert
TLS og får sekvenskontroll. Controllerens kommando-API godtar bare lokal JSON
fra gatewayen. Sporbytte blir aldri automatisk forsøkt på nytt etter nettverksfeil.
Funksjoner som avspillingsenheten begrenser, får inaktive knapper.

Referanser: [PKCE](https://developer.spotify.com/documentation/web-api/tutorials/code-pkce-flow),
[tokenfornyelse og levetid](https://developer.spotify.com/documentation/web-api/tutorials/refreshing-tokens),
[returadresser](https://developer.spotify.com/documentation/web-api/concepts/redirect_uri).

## Verifisering 2026-11-17

- Ti Spotify-tester består: PKCE/state, tokenrotasjon, utløpt tilgang,
  forespørselsgrenser, lokal kommandotilgang og sperring mens en kommando avklares.
- Linux-gatewayen er krysskompilert til objektfil med `-Wall -Wextra -Werror`.
- Firmwaredekoderen er kjørt mot gyldig melding, ventetilstand og feilformede meldinger.
- Secure-firmware er bygget: 61 384 byte statisk RAM og 1 004 805 byte programflash.
  På Windows krevde kontrollbygget en midlertidig wrapper for korte responsfilstier;
  firmwarekoden og kompilatorflaggene var ellers de samme.
- PlatformIO-konfigurasjonen er låst til de tidligere fysisk testede versjonene
  Espressif32 7.1.0 / Arduino 2.0.17 og LovyanGFX 1.2.28.
- Linux-testen som kobler controllerens HTTP-format, C-enkoder og firmwaredekoder
  kjøres på POSIX-maskiner med C/C++ og OpenSSL-utviklingsfiler. Den hoppes over på Windows.
- Den samlede Python-suiten traff også to Windows-avhengige feil utenfor Spotify:
  privat ICS-cache (`os.fchmod`) og oppstart av Git/MSYS OpenSSL for TLS-testene.
  De relevante controller-, visnings-, transport- og Spotify-testene består.

Spotify-kontoen er ikke koblet til i utviklingsmiljøet. Fysisk skjermtest og
verifisering mot ekte avspilling må gjøres etter installasjon og innlogging på Pi-en.
