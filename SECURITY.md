# Sikkerhet og offentlig publisering

Dette repoet skal kunne være offentlig. Kildekode, dokumentasjon og eksempeldata
må derfor behandles som offentlig informasjon fra det øyeblikket de committes.

## Dette skal aldri committes

- passord, PIN-koder, API-nøkler, tokens eller GitHub-legitimasjon
- private SSH-nøkler, sertifikatnøkler eller gjenopprettingskoder
- Wi-Fi-navn og Wi-Fi-passord, for eksempel i `wpa_supplicant.conf`
- ekte `.env`-filer eller lokale konfigurasjonsfiler med hemmeligheter
- private IP-oppsett, domenenavn, e-postadresser eller andre personopplysninger som
  ikke er ment å være offentlige
- logger, skjermbilder eller feilmeldinger før de er kontrollert for sensitiv info

Bruk tydelige eksempelverdier i dokumentasjonen, som `192.0.2.42`,
`example-token` og `wifi-name-here`. En eventuell `.env.example` skal bare
inneholde variabelnavn og ufarlige plassholdere.

## Før hver commit og push

1. Kjør `git status` og kontroller alle filer som skal bli med.
2. Kjør `git diff --staged` og les hele endringen.
3. Søk etter ord som `password`, `secret`, `token`, `api_key`, `BEGIN PRIVATE KEY`
   og eget Wi-Fi-navn.
4. Kontroller spesielt nye konfigurasjonsfiler, logger, bilder og skjermbilder.
5. Legg lokale hemmeligheter i en ignorert fil, aldri direkte i kildekoden.

`.gitignore` reduserer risikoen for vanlige feil, men er ikke en sikkerhetsgrense.
En fil som allerede er lagt til i Git, blir ikke beskyttet av en senere
`.gitignore`-regel.

## Hvis en hemmelighet blir committet

Ikke stol på at det holder å slette filen i en ny commit. Anta at hemmeligheten
er kopiert: deaktiver eller roter den først, og rens deretter Git-historikken før
repoet publiseres videre.

## Nettverk

Flask-appen lytter på alle nettverksgrensesnitt og har ikke innlogging. Kjør den
bare på et betrodd hjemmenett eller labnett. Ikke videresend port 5000 fra
ruteren og ikke eksponer appen direkte mot internett.

Heartbeat-endepunktet for andre noder er åpent på labnettet som standard. Hvis
andre enn betrodde enheter har tilgang til nettet, sett samme
`PI_DISPLAY_NODE_TOKEN` i de lokale systemd-miljøfilene på hoved-Pi og agenter.
Tokenet skal aldri legges i repoet eller skrives direkte inn i servicefilene.

Oppdateringskontrollen i nettleseren er bare lesende. Den henter Git-status fra
konfigurert `origin/main` og kan vise en lenke til en nyere GitHub-commit, men den
kan ikke installere kode eller starte tjenesten på nytt. Selve oppdateringen må
kjøres uttrykkelig over SSH med `scripts/update.sh`. Port 5000 skal fortsatt aldri
eksponeres direkte mot internett.
