# Analýza prihlásenia do Discordu (QR login bez prehliadača)

Dátum pozorovania: 2026-11-03, 12:22 – 12:30 UTC. Klient: `discord.com/login` vo vstavanom prehliadači
Claude desktop appky, **neprihlásený** stav. Build `660103`, `RELEASE_CHANNEL=stable`, API `v9`.

**Legenda:** **[OVERENÉ]** = pozorované počas tejto analýzy (zdroj je uvedený: *prevádzka* = zachytené
WebSocket rámce alebo HTTP odpovede, *JS* = zdrojový kód klienta, ktorý stránka načítala, *stav* = stav
stránky alebo DOM). **[PREDPOKLAD]** = všeobecná znalosť, tu neoverená.

**Metodika:**
- Stránku som otvoril, pred SPA navigáciou som do nej nainštaloval pasívny observer (obal nad
  `window.WebSocket`, iba záznam rámcov). QR tok som znova spustil navigáciou login → register → login.
  Potom som počkal na vypršanie QR a zachytil aj jeho automatickú obnovu.
- Telá HTTP odpovedí som čítal z network logu prehliadača.
- JS assety, ktoré stránka už načítala (~630 súborov, ~20 MB), som si stiahol z cache stránky
  (`fetch` s `credentials:"omit"`) a prehľadal. Kľúčové súbory: `web.48946ead1e279bd2.js` (tabuľka
  endpointov, HTTP klient, login akcie), `541cc3384b699976.js` (QR/remote-auth klient),
  `9efedacca22a4bc6.js` (MFA dialóg), `564784e2787ee0c8.js` (WebAuthn).
- Nič som neodoslal: žiadny formulár, žiadna správa cez socket, žiadne vlastné API volanie. Klávesnicu som
  nepoužil. Cookies ani token som nečítal.
- Všetky živé hodnoty (kľúče, nonce, fingerprinty, tickety, challenge) sú v texte nahradené
  zástupnými symbolmi `<...>`.

---

## 1. Súhrnná tabuľka

| Téma | Zistenie | Stav |
|---|---|---|
| QR gateway | `wss://remote-auth-gateway.discord.gg/?v=2`, JSON text rámce, bez subprotokolu a bez kompresie | [OVERENÉ] prevádzka + JS |
| Kryptografia | RSA-OAEP, 2048 bit, e=65537, hash SHA-256. Verejný kľúč = SPKI DER v štandardnom base64 | [OVERENÉ] JS + dĺžky v prevádzke |
| Dôkaz (proof) | `nonce` = base64url (bez `=`) z **dešifrovaného** nonce. Žiadne hashovanie (protokol v2) | [OVERENÉ] JS + prevádzka |
| Obsah QR | `https://discord.com/ra/<fingerprint>`, fingerprint = base64url(SHA-256(SPKI)), 43 znakov. ECC level **M** | [OVERENÉ] JS + stav (props QR komponentu) |
| Platnosť QR | `timeout_ms` z `hello` (~250 – 275 s, náhodné). Potom server zavrie socket kódom **4003 "Handshake Timeout"** a klient sám otvorí nový | [OVERENÉ] prevádzka |
| Heartbeat | `heartbeat_interval` 41 250 ms, klient posiela `{"op":"heartbeat"}`, server odpovedá `heartbeat_ack` | [OVERENÉ] prevádzka |
| Po naskenovaní | `pending_ticket` so `encrypted_user_payload` → `id:discriminator:avatar:username` | [OVERENÉ] JS + prototyp (sekcia 7) |
| Po potvrdení na telefóne | `pending_login` s `ticket` → `POST /api/v9/users/@me/remote-auth/login {ticket}` → `encrypted_token` → RSA dešifrovanie → token | [OVERENÉ] JS |
| Captcha | Globálny interceptor HTTP klienta: `400` + `captcha_key` → captcha → retry s `X-Captcha-Key` (+ `X-Captcha-Rqtoken`, `X-Captcha-Session-Id`). Platí aj pre `remote-auth/login` | [OVERENÉ] JS. Pri prvom reálnom QR logine z terminálu ju Discord **nepýtal** (prototyp) |
| Email/heslo | `POST /auth/login` → token, alebo `mfa:true` + `ticket` → `POST /auth/mfa/{totp\|sms\|backup\|webauthn}` | [OVERENÉ] JS |
| Pred loginom stránka volá | `experiments` (→ `X-Fingerprint`), `apex/experiments`, `auth/location-metadata`, `auth/conditional/start`, `science` | [OVERENÉ] prevádzka |
| Passkey | Pri **každom** zobrazení login formulára stránka sama volá `POST /auth/conditional/start` a `navigator.credentials.get` (conditional mediation) | [OVERENÉ] JS + prevádzka. Toto vyvolalo okno Windows Security (sekcia 8) |
| QR bez prehliadača | Áno, technicky. Treba WebSocket klient, RSA-OAEP-SHA256, HTTP klient a QR v termináli | Záver z [OVERENÉ] faktov. Kontrolu `Origin` treba overiť prototypom |

---

## 2. QR login (remote auth gateway)

### 2.1 Pripojenie

- **URL:** `wss://remote-auth-gateway.discord.gg/?v=2` **[OVERENÉ]** (prevádzka + JS: `${GLOBAL_ENV.REMOTE_AUTH_ENDPOINT}/?v=2`,
  `REMOTE_AUTH_ENDPOINT = "wss://remote-auth-gateway.discord.gg"` v `window.GLOBAL_ENV`).
- Klient volá obyčajné `new WebSocket(url)` bez subprotokolov **[OVERENÉ]** (JS, modul `createWebSocket`).
  Server nedojednal žiadne rozšírenie (`extensions = ""`, teda ani `permessage-deflate`). Rámce sú čistý JSON text **[OVERENÉ]** (prevádzka).
- **Hlavičky:** prehliadač nevie k WebSocketu pridať vlastné hlavičky, posiela teda iba štandardné:
  `Origin: https://discord.com`, `User-Agent`, `Sec-WebSocket-*`. Iné hlavičky klient nenastavuje **[OVERENÉ]** (JS).
  Či server **vyžaduje** `Origin: https://discord.com`, sa nedalo overiť bez vlastného spojenia.
  Komunitné implementácie ho posielajú a bez neho vraj server spojenie odmietne **[PREDPOKLAD]**.

### 2.2 Sekvencia správ (pozorovaná)

Časy sú relatívne k otvoreniu socketu. Hodnoty sú nahradené.

| # | Smer | Správa | Poznámka |
|---|---|---|---|
| 1 | server → klient | `{"op":"hello","heartbeat_interval":41250,"timeout_ms":272373}` | prišla hneď po `open` (+1 ms) |
| 2 | klient → server | `{"op":"init","encoded_public_key":"<SPKI DER, base64, 392 znakov>"}` | +92 ms (generovanie RSA kľúča) |
| 3 | server → klient | `{"op":"nonce_proof","encrypted_nonce":"<base64 s paddingom, 344 znakov = 256 B>"}` | |
| 4 | klient → server | `{"op":"nonce_proof","nonce":"<base64url bez '=', 254 znakov = 190 B>"}` | +1 ms po 3 |
| 5 | server → klient | `{"op":"pending_remote_init","fingerprint":"<base64url, 43 znakov>"}` | klient overí, že sa zhoduje s jeho vlastným, a zobrazí QR |
| 6 | klient → server | `{"op":"heartbeat"}` | prvý po náhodnom čase `0 .. heartbeat_interval` (tu +6,2 s), potom každých 41,25 s |
| 7 | server → klient | `{"op":"heartbeat_ack"}` | ~115 ms po heartbeate |
| … | | (6 a 7 sa opakujú) | |
| n | server | `close 4003 "Handshake Timeout"`, `wasClean=true` | presne `timeout_ms` po otvorení (12:23:14,93 + 272,37 s = 12:27:47,30) |

Všetko vyššie je **[OVERENÉ]** (prevádzka, dve kompletné relácie).

Správy, ktoré prichádzajú až po naskenovaní, som nezachytil (QR som neskenoval). Ich tvar je z JS **[OVERENÉ]** (JS):

| Smer | Správa | Čo klient spraví |
|---|---|---|
| server → klient | `{"op":"pending_ticket","encrypted_user_payload":"<base64>"}` | dešifruje RSA-OAEP → UTF-8 reťazec, ukáže avatar + „Logging in as <username>“ |
| server → klient | `{"op":"pending_login","ticket":"<ticket>"}` | `POST /users/@me/remote-auth/login` (sekcia 2.6). Ak `ticket == null`, reštartuje reláciu |
| server → klient | `{"op":"cancel"}` | používateľ zrušil na telefóne → klient zahodí reláciu a otvorí novú (nový QR) |
| server → klient | iný `op` | iba `warn("received unsupported message")` |

Klient nikdy neposiela iné `op` ako `init`, `nonce_proof` a `heartbeat` **[OVERENÉ]** (JS).
Pri zrušení alebo odchode zo stránky iba zavrie socket kódom `1000` **[OVERENÉ]** (JS).

> Starší protokol (v1) mal namiesto `nonce` pole `proof = base64url(SHA-256(nonce))` a token posielal priamo
> cez socket (`pending_finish`/`finish`). Verzia `v=2` to nahradila `pending_ticket` + `pending_login` + REST
> volaním **[PREDPOKLAD]**. Staršie návody na internete preto nemusia sedieť.

### 2.3 Kľúč a parametre

Zo JS **[OVERENÉ]**:
```js
crypto.subtle.generateKey({name:"RSA-OAEP", modulusLength:2048,
  publicExponent:new Uint8Array([1,0,1]), hash:"SHA-256"}, true, ["decrypt"])
encoded_public_key = btoa(exportKey("spki", publicKey))          // štandardný base64
decrypt = crypto.subtle.decrypt({name:"RSA-OAEP", hash:"SHA-256"}, privateKey, atob(x))
```
- RSA 2048 bit, verejný exponent 65537, OAEP s SHA-256 **[OVERENÉ]** (JS).
- WebCrypto RSA-OAEP používa MGF1 s tým istým hashom (SHA-256) a prázdny label **[PREDPOKLAD]** (špecifikácia WebCrypto).
  V Pythone `cryptography` je to `padding.OAEP(mgf=MGF1(SHA256()), algorithm=SHA256(), label=None)`.
- Dĺžky v prevádzke sedia: SPKI 294 B → 392 znakov base64 a šifrový text 256 B → 344 znakov **[OVERENÉ]** (prevádzka).
- Nový pár kľúčov sa generuje pre **každé** spojenie **[OVERENÉ]** (JS).

### 2.4 Výpočet dôkazu (nonce proof)

```
nonce_bytes = RSA_OAEP_SHA256_decrypt(private_key, base64decode(encrypted_nonce))
nonce       = base64url(nonce_bytes) bez koncových '='     // '+'→'-', '/'→'_'
```
**[OVERENÉ]** (JS `decryptNonce` → funkcia `O`). Dešifrovaný nonce mal v oboch reláciách 190 B (254 znakov).
To je maximum pre RSA-2048 s OAEP-SHA256 **[OVERENÉ]** (prevádzka).

### 2.5 Obsah QR a platnosť

- **Fingerprint** = `base64url(SHA-256(SPKI DER verejného kľúča))` bez paddingu, 43 znakov **[OVERENÉ]** (JS + prevádzka).
  Klient porovná svoj fingerprint s tým zo `pending_remote_init`. Pri nezhode vyhodí chybu `bad fingerprint` **[OVERENÉ]** (JS).
- **Text QR:** `https://discord.com/ra/<fingerprint>` **[OVERENÉ]**. Stav: props QR komponentu sa zhodovali s posledným
  `pending_remote_init.fingerprint`. Route `/ra/:remoteAuthFingerprint` existuje aj na webe **[OVERENÉ]** (JS).
- Vykreslenie: knižnica `qrcode.react`, `level:"M"`, čierna na bielej, 160 px, v strede logo Discordu (iba
  overlay, nie súčasť dát) **[OVERENÉ]** (JS).
- Dĺžka textu je 66 znakov. Pri ECC M to vychádza na QR verziu 5 (37 × 37 modulov, s tichou zónou 45 × 45) **[PREDPOKLAD]** (výpočet podľa QR štandardu).
- **Platnosť:** `timeout_ms` z `hello`. Pozorované hodnoty boli 272 373 ms a 253 736 ms, čiže ~4,2 – 4,5 min, náhodne **[OVERENÉ]** (prevádzka).
  Klient túto hodnotu iba zaloguje a nepoužíva ju na časovač **[OVERENÉ]** (JS).
- **Pri vypršaní:** server zavrie socket (`4003 Handshake Timeout`). Klient zaloguje chybu a podľa backoffu
  (min 1,5 s, max 30 s, s jitterom) otvorí nové spojenie s novým kľúčom, teda aj s novým QR **[OVERENÉ]**.
  Prevádzka: nový socket o 2,4 s, nový `hello` a celý handshake. JS: `new Backoff(1500, 30000)`.
  Ak je karta skrytá, obnovu odloží, kým sa nezobrazí **[OVERENÉ]** (JS). Pri obnove QR stránka **nevolala** žiadny REST endpoint **[OVERENÉ]** (network log).
- Ak nepríde `heartbeat_ack` pred ďalším heartbeatom, klient zavrie socket a reštartuje reláciu **[OVERENÉ]** (JS).

### 2.6 Posledný krok po potvrdení na telefóne

Zo JS **[OVERENÉ]**:
```
POST https://discord.com/api/v9/users/@me/remote-auth/login
Content-Type: application/json
{"ticket": "<ticket z pending_login>"}

→ 200 {"encrypted_token": "<base64, RSA-OAEP-SHA256 šifrový text>"}
token = UTF-8( RSA_OAEP_SHA256_decrypt(private_key, base64decode(encrypted_token)) )
```
- Request ide cez spoločný HTTP klient s globálnymi hlavičkami (sekcia 4.2) a bez `Authorization`,
  keďže používateľ nie je prihlásený **[OVERENÉ]** (JS).
- Ide aj cez **globálny captcha interceptor**: ak by server vrátil `400` s `captcha_key`, web ukáže captchu a
  request zopakuje s hlavičkami `X-Captcha-Key`, `X-Captcha-Rqtoken` a `X-Captcha-Session-Id` **[OVERENÉ]** (JS).
  Či Discord pri QR login captchu reálne pýta, je neoverené. Bežne nie **[PREDPOKLAD]**.
- Pri akejkoľvek chybe tohto requestu web reláciu zahodí a začne odznova (nový QR) **[OVERENÉ]** (JS).
- Po úspechu web zavolá `loginToken(token)` (dispatch `LOGIN_SUCCESS`) a pripojí sa na bežný gateway **[OVERENÉ]** (JS).
- Endpointy pre stranu telefónu (prihlásený klient, ktorý skenuje): `POST /users/@me/remote-auth`,
  `/users/@me/remote-auth/finish`, `/users/@me/remote-auth/cancel` **[OVERENÉ]** (iba názvy v tabuľke endpointov, web ich nevolá).
  Ich telá CLI nepotrebuje **[PREDPOKLAD]**.

### 2.7 Čo klient zobrazí po naskenovaní

- `encrypted_user_payload` sa dešifruje rovnako ako token a výsledok musí sedieť na regex
  `^(\d+):(\d{1,4}):([a-zA-Z0-9_]+):(.*)$` **[OVERENÉ]** (JS):
  `"<user_id>:<discriminator>:<avatar_hash alebo 0>:<username>"`.
  `avatar == "0"` znamená bez avatara. Pri nových (pomelo) menách je `discriminator` `"0"` **[PREDPOKLAD]**.
- UI: avatar (120 px), nadpis „Check your phone!“, text „Logging in as <username>“ a tlačidlo
  „Not me, start over“. Tlačidlo iba lokálne zahodí reláciu a otvorí novú **[OVERENÉ]** (JS + lokalizačné reťazce).
- Pred naskenovaním: „Log in with QR Code“ / „Scan this with the Discord mobile app to log in instantly.“ **[OVERENÉ]** (stav).

### 2.8 Stavový automat klienta

`INITIALIZING → PENDING_REMOTE_INIT (QR) → PENDING_TICKET (meno) → PENDING_LOGIN (REST) → FINISH` **[OVERENÉ]** (JS, enum).
Každá chyba (close, chyba socketu, zlý fingerprint, chyba REST, chýbajúci ticket, `cancel`) vedie späť na `INITIALIZING` s backoffom.

---

## 3. Prihlásenie emailom a heslom (iba JS, nič neodoslané)

### 3.1 Login

```
POST /api/v9/auth/login
{"login": "<email alebo telefón>", "password": "<heslo>", "undelete": false,
 "login_source": null, "gift_code_sku_id": null}
```
**[OVERENÉ]** (JS `AuthenticationActionCreators.login`, `retries:2`). Pri telefóne klient pred `login` pridá predvoľbu krajiny **[OVERENÉ]** (JS).

**Odpovede** (polia, ktoré klient číta) **[OVERENÉ]** (JS):
- **Úspech:** `{ "token": "<token>", "user_id": "<id>", "required_actions": [...]? }`
- **Treba MFA:** `{ "mfa": true, "ticket": "<mfa ticket>", "totp": bool, "sms": bool, "backup": bool,
  "webauthn": "<JSON reťazec s WebAuthn challenge>" | null, "login_instance_id": "<id>", "user_id": "<id>" }`.
  Z toho klient poskladá ponuku metód v poradí `webauthn`, `totp`, `backup`, `sms`.
- **Captcha:** HTTP `400` s `captcha_key` (pole). Ďalšie polia, ktoré klient číta: `captcha_service`
  (`hcaptcha` | `recaptcha` | `recaptcha_enterprise` | `turnstile`), `captcha_sitekey`, `captcha_session_id`,
  `captcha_rqdata`, `captcha_rqtoken`, `should_serve_invisible`, `user_flow`. Retry posiela hlavičky
  `X-Captcha-Key: <riešenie>`, `X-Captcha-Rqtoken` a `X-Captcha-Session-Id` **[OVERENÉ]** (JS).
- **Chyby podľa `code`:** `20011` účet naplánovaný na zmazanie (umožní `undelete`), `20013` účet vypnutý,
  `70007` treba overiť telefón („IP authorization“), `suspended_user_token` znamená suspendovaný účet. Inak všeobecná chyba
  formulára (`50035` Invalid Form Body) **[OVERENÉ]** (JS, mapa kódov).
- Overenie novej lokality (email „Verify login location“) ide cez `POST /auth/authorize-ip {token}` **[OVERENÉ]** (názov endpointu a telo).
  Kedy ho server vyžaduje, je **[PREDPOKLAD]**.

### 3.2 MFA endpointy

```
POST /api/v9/auth/mfa/{totp|sms|backup|webauthn}
{"code": "<kód>", "ticket": "<mfa ticket>", "login_source": null,
 "gift_code_sku_id": null, "login_instance_id": "<z login odpovede>"}
→ {"token": "<token>"}
```
**[OVERENÉ]** (JS `loginMFAv2`, `retries:2`). Chyba `60008` = nesprávny kód **[OVERENÉ]** (JS).
- `totp`: 6 číslic **[OVERENÉ]** (JS, konštanta 6).
- `sms`: najprv `POST /auth/mfa/sms/send {"ticket"}` → `{"phone":"<maskované číslo>"}`, potom kód (6 číslic) **[OVERENÉ]** (JS).
- `backup`: záložný kód bez pomlčiek, 8 až 11 znakov **[OVERENÉ]** (JS, konštanty 8 a 11, `replace(/-/g,"")`).
- `webauthn`: `code` je JSON reťazec s WebAuthn assertion (`id`, `rawId`, `response.{authenticatorData,
  clientDataJSON, signature, userHandle}`, všetko base64url) **[OVERENÉ]** (JS). V termináli to nie je praktické.
- Mimo loginu: `POST /mfa/finish {ticket, mfa_type, data}` → hlavička `X-Discord-MFA-Authorization` pre citlivé
  akcie v prihlásenom stave **[OVERENÉ]** (JS). Pre CLI to nie je potrebné.

---

## 4. Čo stránka volá pred prihlásením

### 4.1 Requesty (pozorované)

| Request | Odpoveď (štruktúra) | Načo |
|---|---|---|
| `GET /api/v9/experiments?with_guild_experiments=true` | `{"fingerprint":"<snowflake>.<~27 znakov>","assignments":[...],"guild_experiments":[...]}` | **zdroj `X-Fingerprint`** |
| `GET /api/v9/apex/experiments?surface=2` | `{"assignments":{"1":{"<id>":{"evaluation_id":"…","assignments":[...]}}}}` | experimenty |
| `GET /api/v9/auth/location-metadata` | `{"consent_required":bool,"country_code":"<2 písmená>","minimum_age":null,"promotional_email_opt_in":{"required":bool,"pre_checked":bool}}` | GDPR/vekové pravidlá pre registráciu |
| `POST /api/v9/auth/conditional/start` | `{"challenge":"<JSON reťazec: {publicKey:{challenge, timeout:300000, rpId:'discord.com', allowCredentials:[], userVerification:'required', extensions:{uvm:true}}, mediation:'conditional'}>","ticket":"<uuid>"}` | passkey autofill (sekcia 5) |
| `POST /api/v9/science` → `204` | – | analytika (`LOGIN_VIEWED`, `REGISTER_VIEWED`, …) |
| `wss://remote-auth-gateway.discord.gg/?v=2` | sekcia 2 | QR |

Všetko **[OVERENÉ]** (prevádzka). Výhrada: network buffer držal iba posledných 500 requestov, takže úplne prvé
requesty pri načítaní stránky (pred `experiments`) mohli vypadnúť.

### 4.2 Hlavičky requestov (iba mená, z JS)

HTTP klient ich pridáva ku každému requestu na `/api/...` **[OVERENÉ]** (JS `prepareRequest`). Reálne hlavičky
v prevádzke som nevidel, nástroj ich neukazuje.
- `Authorization` (iba ak existuje token)
- `X-Super-Properties`: base64 JSON s kľúčmi `os`, `browser`, `device`, `system_locale`, `has_client_mods`,
  `browser_user_agent`, `browser_version`, `os_version`, `referrer`, `referring_domain`, `*_current`,
  `release_channel`, `client_build_number`, `client_event_source`, `client_launch_id`, `client_heartbeat_session_id`, `client_app_state`
- `X-Fingerprint`: hodnota `fingerprint` z `/experiments`. Pri ďalších načítaniach sa berie z lokálneho úložiska
- `X-Installation-ID` (ak ho server pridelil, v tejto odpovedi chýbal)
- `X-Discord-Locale`, `X-Discord-Timezone`
- `X-Debug-Options`, `X-Routing-Key`, `x-client-trace-id` (iba v debug/tracing režime)
- `Accept-Language` (iba desktop appka)
- `Content-Type: application/json` pri telách
- pri retry po captche `X-Captcha-Key`, `X-Captcha-Rqtoken`, `X-Captcha-Session-Id`
- pri pozvánkach `X-Context-Properties`

Čo z toho login reálne potrebuje: pravdepodobne nič okrem JSON tela. `X-Super-Properties` a `X-Fingerprint` však
môžu ovplyvniť, či server pýta captchu **[PREDPOKLAD]**. Discord pri odpovediach nastavuje Cloudflare/anti-bot
cookies (`__dcfduid`, `__sdcfduid`, `__cfruid`, `_cfuvid`) **[PREDPOKLAD]** (cookies som podľa pravidiel nečítal).

---

## 5. Iné spôsoby prihlásenia

Názvy endpointov sú z tabuľky endpointov v JS **[OVERENÉ]**:
- **Passkey, conditional UI (autofill):** `POST /auth/conditional/start` → `navigator.credentials.get({mediation:"conditional"})`
  → `POST /auth/conditional/finish {credential, ticket, source, giftCodeSKUId}` → `{token, user_id, required_actions}`.
  Spúšťa sa **automaticky** pri každom zobrazení login formulára, ak prehliadač hlási
  `isConditionalMediationAvailable()` alebo `getClientCapabilities().conditionalGet` **[OVERENÉ]** (JS + prevádzka: 3× `conditional/start`).
- **Passkey, tlačidlo „Or sign in with a passkey“:** `POST /auth/passwordless/start` → `navigator.credentials.get` → `POST /auth/conditional/finish` **[OVERENÉ]** (JS).
- **SSO:** login stránka nemá Google/Apple/SSO tlačidlá **[OVERENÉ]** (stav). `GET /sso` a `/sso-token` slúžia na to, aby
  sa Discord účtom prihlásilo do iných služieb (parameter `service`). Nie je to login do Discordu **[OVERENÉ]** (JS).
- **Ďalšie toky s tokenom:** `POST /auth/one-time-login {ticket}` → `{token}`; handoff z desktop appky
  `POST /auth/handoff {key}` → `{handoff_token}` a `POST /auth/handoff/exchange {key, handoff_token}` → `{token, user}`;
  `POST /auth/verify {token}` (overenie emailu, vráti token) **[OVERENÉ]** (JS). Pre CLI nie sú použiteľné bez prehliadača alebo appky **[PREDPOKLAD]**.
- **OAuth2 device flow:** `/oauth2/device/verify` a `/oauth2/device/finish` existujú **[OVERENÉ]** (názvy).
  Ide o prepojenie konzol a aplikácií. Užívateľský token nevracia **[PREDPOKLAD]**.

---

## 6. Dôsledky pre CLI nástroj

### 6.1 Dá sa QR login spraviť úplne bez prehliadača?

**Áno.** Celý protokol je obyčajný WebSocket s JSON správami, RSA-OAEP-SHA256 a jeden REST POST. Klient
nepoužíva nič, čo vie iba prehliadač: žiadnu captchu v QR toku, žiadny podpis zariadenia, žiadne cookies vo WebSocket
handshaku (zistenia sú z [OVERENÉ] JS a prevádzky). Neoverené ostáva, či server toleruje ne-prehliadačového klienta (sekcia 7).

**Čo treba (Python, cross-platform Windows/Linux/macOS):**

| Časť | Knižnica | Poznámka |
|---|---|---|
| WebSocket | `websockets` (asyncio) | nastaviť hlavičku `Origin: https://discord.com` a rozumný `User-Agent` |
| Krypto | `cryptography` | `rsa.generate_private_key(65537, 2048)`, SPKI DER (`PublicFormat.SubjectPublicKeyInfo`), `OAEP(MGF1(SHA256), SHA256, None)` |
| REST | `httpx` (už v návrhu) | `POST /api/v9/users/@me/remote-auth/login`, potom `GET /users/@me` na overenie |
| QR v termináli | `segno` alebo `qrcode` | ECC **M**, tmavé moduly na svetlom pozadí, tichá zóna 4 moduly, vykreslenie cez polovičné bloky (`▀▄█`, ~45 stĺpcov × 23 riadkov) |
| Uloženie tokenu | `keyring` | Windows Credential Manager, macOS Keychain, Linux Secret Service. Na headless Linuxe môže backend chýbať, treba fallback (súbor s právami `0600`) |

**Navrhovaný tok `discoop login`:**
1. Pripojiť sa na `wss://remote-auth-gateway.discord.gg/?v=2` (s `Origin`).
2. Prijať `hello`, spustiť heartbeat (prvý po `random() * interval`, potom každý `interval`). Bez `heartbeat_ack` reconnect.
3. Vygenerovať RSA-2048 a poslať `init`.
4. Na `nonce_proof` dešifrovať nonce a poslať `{"op":"nonce_proof","nonce":base64url(nonce)}`.
5. Na `pending_remote_init` overiť fingerprint a vykresliť QR `https://discord.com/ra/<fingerprint>`.
   K tomu vypísať text „naskenuj v Discord appke (Settings → Scan QR Code)“ a odpočet z `timeout_ms`.
6. Na `pending_ticket` dešifrovať payload a vypísať „Prihlasuje sa <username>, potvrď na telefóne“.
7. Na `pending_login` zavolať REST, dešifrovať `encrypted_token`, overiť ho cez `GET /users/@me`, uložiť do keyringu a zavrieť socket.
8. Na `cancel` alebo `4003` vygenerovať nový QR. Po N pokusoch (napr. 3, teda ~13 min) skončiť s exit kódom.
9. V `--agent` režime vypísať aj samotný text QR (URL) a čakať. Človek ho môže naskenovať z iného miesta.

### 6.2 Riziká

- **Kontrola `Origin`:** bez správnej hlavičky môže gateway spojenie odmietnuť **[PREDPOKLAD]**. Rieši sa jednou hlavičkou.
- **Captcha na `remote-auth/login`:** HTTP klient je na ňu pripravený **[OVERENÉ]** (JS). Ak ju server začne vyžadovať,
  v termináli sa vyriešiť nedá a treba fallback (6.3).
- **Zmena protokolu:** `v=2` je už druhá verzia. Discord ho môže kedykoľvek zmeniť alebo pridať kontrolu klienta.
  Nástroj by mal pri neznámom `op` alebo zatvorení s neznámym kódom vypísať zrozumiteľnú chybu a ponúknuť fallback.
- **Detekcia ne-prehliadačového klienta:** Cloudflare/TLS fingerprint pri REST volaní, chýbajúce `X-Super-Properties`.
  Môže to viesť k captche alebo zablokovaniu requestu **[PREDPOKLAD]**.
- **ToS a účet:** token z QR je plnohodnotný používateľský token. Discord eviduje novú reláciu v zozname zariadení
  **[PREDPOKLAD]**. Automatizované používanie user tokenu porušuje ToS, používateľ to akceptuje.
- **Bezpečnosť:** QR je de facto prihlasovací odkaz. Nesmie sa dostať do logov, histórie ani výstupu pre agenta,
  ktorý by ho mohol preposlať ďalej. Token ani fingerprint nikdy nelogovať.

### 6.3 Fallbacky (v poradí, ako ich odporúčam)

1. **Ručné vloženie tokenu** (`discoop login --token`, vstup cez skrytý prompt alebo stdin, nie ako argument v histórii).
   Funguje vždy a všade a je najjednoduchší. Nevýhoda: používateľ musí vedieť token získať z DevTools.
2. **Prihlásenie cez prehliadač** (pôvodný návod v `design.md` 4.1, Playwright).
   Zvládne captchu, 2FA aj passkey. Na Linuxe/macOS treba nainštalovaný Chrome alebo Chromium, takže je to ťažšia závislosť.
   Pozor: na Windows môže prehliadač pri otvorení `/login` sám vyvolať passkey dialóg (sekcia 8).
3. **Email/heslo + TOTP cez API** (`/auth/login` → `/auth/mfa/totp`). Technicky jednoduché, ale ne-prehliadačový klient
   pravdepodobne často dostane captchu **[PREDPOKLAD]**. Nástroj by navyše musel pracovať s heslom. Neodporúčam ako
   hlavnú cestu, nanajvýš ako experimentálnu.

### 6.4 Dopad na návrh (`design.md` som needitoval)

- Sekcia 3 („Login: Playwright + nainštalovaný Chrome“) a sekcia 4.1 by sa pri novej požiadavke zmenili na QR login cez
  `websockets` + `cryptography`. Playwright by ostal ako voliteľný fallback.
- Tabuľka technológií: `keyring` nie je iba „Windows Credential Manager“. Na Linuxe treba riešiť chýbajúci Secret Service.
- Nové závislosti: `websockets`, `cryptography`, `segno` (alebo `qrcode`).

---

## 7. Neoverené / otvorené otázky

> **Doplnené 2026-11-03, prototyp** (`discoop login --handshake-only --trace`, bez prihlásenia):
> - Gateway **prijal klienta mimo prehliadača** (Python `websockets`, `Origin: https://discord.com`,
>   `User-Agent: discoop/0.1.0`) a prešiel celý handshake po `pending_remote_init` **[OVERENÉ]** (prototyp).
> - Dĺžky polí sedia s analýzou: `encoded_public_key` 392, `encrypted_nonce` 344, `nonce` 254, `fingerprint` 43 znakov.
> - `heartbeat_interval` 41 250 ms, `timeout_ms` 245 280 ms (v rozsahu ~4 – 4,5 min).
>
> **Doplnené 2026-11-03, prvý reálny login** (`discoop login --trace`, používateľ naskenoval QR) **[OVERENÉ]** (prototyp):
> - **Celý tok prešiel bez prehliadača a bez captchy:**
>   `pending_remote_init` → (sken po ~52 s) `pending_ticket` → (potvrdenie po ~16 s) `pending_login`
>   → `POST /users/@me/remote-auth/login` `200` → token overený cez `GET /users/@me`.
> - **Tvary sedia s JS:**
>   - `pending_ticket.encrypted_user_payload` 344 znakov (256 B RSA),
>   - `pending_login.ticket` 70 znakov,
>   - odpoveď `{"encrypted_token": <344 znakov>}`.
> - **Heartbeaty** počas čakania na sken a potvrdenie prebiehali normálne (`heartbeat` → `heartbeat_ack` ~110 ms).
> - **`timeout_ms` bol 344 035 ms (~5,7 min).** Platnosť QR teda kolíše viac, než ukázala analýza (~4 – 5,7 min).

- Či gateway **vyžaduje** `Origin: https://discord.com`: s ním funguje (pozri vyššie). Bez neho sa neskúšalo.
  Close kódy pri odmietnutí sú neznáme.
- Tvar a obsah `pending_ticket`, `pending_login`, `cancel` a odpovede `remote-auth/login` je iba zo zdrojového kódu.
  Reálne rámce som nevidel (QR som neskenoval).
- Či `POST /users/@me/remote-auth/login` pri ne-prehliadačovom klientovi vracia captchu a či potrebuje
  `X-Super-Properties`, `X-Fingerprint` alebo Cloudflare cookies.
- Ďalšie close kódy gateway okrem `4003 Handshake Timeout`.
- Či token z QR loginu má nejaké obmedzenie oproti tokenu z bežného loginu.
- Reálne hlavičky requestov (vidno iba v JS, nie v prevádzke).
- Reálne odpovede `/auth/login` a `/auth/mfa/*` (iba JS, nič neodoslané).
- Či je dĺžka nonce (190 B) pevná, alebo iba náhodou rovnaká v dvoch reláciách.
- Úplne prvé requesty pri načítaní stránky (vypadli z network bufferu).

---

## 8. Vedľajšie účinky analýzy

1. **Okno Windows Security pre passkey („Making sure it's you… Insert your security key“).**
   - **Príčina:** login stránka pri **každom** zobrazení login formulára automaticky volá
     `POST /api/v9/auth/conditional/start` a hneď potom `navigator.credentials.get({publicKey, mediation:"conditional"})`
     **[OVERENÉ]** (JS: modul `ConditionalMediation` v `541cc3384b699976.js` sa volá v `useMount` login stránky).
     V bežnom Chrome ide iba o tichý autofill. Vstavaný prehliadač na Windows to zjavne poslal do Windows WebAuthn ako modálne okno.
   - **Akcie, ktoré to spustili:**
     - otvorenie `https://discord.com/login` cez `preview_start` (12:22:20 UTC). Pri načítaní prebehli **2×** `conditional/start`.
     - môj klik na „Already have an account? Log in“ na `/register` (~12:23:14 UTC). Znova sa pripojil login formulár a prebehol **3.** `conditional/start`.
     - **Poslednou mojou akciou pred hlásením okna bol tento klik.** Presný čas zobrazenia okna nepoznám, takže okno mohlo
       vzniknúť už pri prvom načítaní.
   - Na nič súvisiace s passkey som neklikol, polia email/heslo som nefokusoval a `navigator.credentials` som nevolal ani neobaľoval.
     Po hlásení som už nenavigoval a stránku som nenačítal znova.
   - Server vydal 3 conditional challenge s `ticket`, platnosť `timeout: 300000` ms. Nepoužité vypršia.
2. **Remote-auth relácie:** gateway videla 3 QR relácie (1 pri načítaní, 1 po mojej navigácii, 1 automatická obnova
   po vypršaní). Karta ostala otvorená na `/login` (karty nezatváram), takže stránka bude každé ~4,5 min generovať nový QR,
   kým je karta viditeľná. Nikto nič neskenoval, nijaký login nevznikol.
3. **Analytika:** stránka sama poslala `POST /api/v9/science` (zobrazenie login a register stránky) z neprihláseného prehliadača.
4. **Stiahnutie JS:** ~630 verejných JS súborov cez `fetch` z kontextu stránky (`force-cache`, bez cookies), aby sa
   dali prehľadať. Väčšina išla z cache.
5. **Observer v stránke:** obal nad `window.WebSocket` ostáva v karte do jej ďalšieho načítania. Na konci som ho prepol
   na no-op (nič už neukladá), zmazal zaznamenané rámce aj stiahnuté JS z pamäte stránky. Na disk som živé hodnoty neukladal.
6. Žiadny vstup z klávesnice, žiadny formulár, žiadna správa cez socket, žiadne vlastné API volanie, žiadne čítanie cookies ani tokenu.
