# Discord Login Analysis (Browserless QR Login)

Observation date: 2026-11-03, 12:22 – 12:30 UTC. Client: `discord.com/login` in the built-in browser
of the Claude desktop app, **unauthenticated** state. Build `660103`, `RELEASE_CHANNEL=stable`, API `v9`.

**Legend:** **[VERIFIED]** = observed during this analysis (source noted: *traffic* = captured
WebSocket frames or HTTP responses, *JS* = client source code loaded by the page, *state* = page or DOM
state). **[ASSUMPTION]** = general knowledge, unverified here.

**Methodology:**
- Opened the page; before SPA navigation, installed a passive observer into it (wrapper around
  `window.WebSocket`, recording frames only). Retriggered the QR flow via navigation: login → register → login.
  Then waited for QR expiration and captured its automatic refresh as well.
- Read HTTP response bodies from the browser network log.
- Downloaded and searched JS assets already loaded by the page (~630 files, ~20 MB) from page cache
  (`fetch` with `credentials:"omit"`). Key files: `web.48946ead1e279bd2.js` (endpoint table,
  HTTP client, login actions), `541cc3384b699976.js` (QR/remote-auth client),
  `9efedacca22a4bc6.js` (MFA dialog), `564784e2787ee0c8.js` (WebAuthn).
- Sent nothing: no forms, no socket messages, no custom API calls. Did not use the keyboard.
  Did not read cookies or token.
- All live values (keys, nonces, fingerprints, tickets, challenges) are replaced with
  placeholders `<...>` in the text.

---

## 1. Summary Table

| Topic | Finding | Status |
|---|---|---|
| QR gateway | `wss://remote-auth-gateway.discord.gg/?v=2`, JSON text frames, no subprotocol and no compression | [VERIFIED] traffic + JS |
| Cryptography | RSA-OAEP, 2048-bit, e=65537, SHA-256 hash. Public key = SPKI DER in standard base64 | [VERIFIED] JS + lengths in traffic |
| Proof | `nonce` = base64url (without `=`) of the **decrypted** nonce. No hashing (protocol v2) | [VERIFIED] JS + traffic |
| QR content | `https://discord.com/ra/<fingerprint>`, fingerprint = base64url(SHA-256(SPKI)), 43 characters. ECC level **M** | [VERIFIED] JS + state (props of QR component) |
| QR validity | `timeout_ms` from `hello` (~250 – 275 s, randomised). Server then closes socket with code **4003 "Handshake Timeout"** and client opens a new one automatically | [VERIFIED] traffic |
| Heartbeat | `heartbeat_interval` 41,250 ms, client sends `{"op":"heartbeat"}`, server responds with `heartbeat_ack` | [VERIFIED] traffic |
| After scanning | `pending_ticket` with `encrypted_user_payload` → `id:discriminator:avatar:username` | [VERIFIED] JS + prototype (Section 7) |
| After confirmation on phone | `pending_login` with `ticket` → `POST /api/v9/users/@me/remote-auth/login {ticket}` → `encrypted_token` → RSA decryption → token | [VERIFIED] JS |
| Captcha | Global HTTP client interceptor: `400` + `captcha_key` → captcha → retry with `X-Captcha-Key` (+ `X-Captcha-Rqtoken`, `X-Captcha-Session-Id`). Applies to `remote-auth/login` as well | [VERIFIED] JS. During first real QR login from terminal Discord **did not prompt** for it (prototype) |
| Email/password | `POST /auth/login` → token, or `mfa:true` + `ticket` → `POST /auth/mfa/{totp\|sms\|backup\|webauthn}` | [VERIFIED] JS |
| Before login page calls | `experiments` (→ `X-Fingerprint`), `apex/experiments`, `auth/location-metadata`, `auth/conditional/start`, `science` | [VERIFIED] traffic |
| Passkey | On **every** display of login form, page automatically calls `POST /auth/conditional/start` and `navigator.credentials.get` (conditional mediation) | [VERIFIED] JS + traffic. This triggered the Windows Security prompt (Section 8) |
| Browserless QR | Yes, technically. Requires WebSocket client, RSA-OAEP-SHA256, HTTP client, and terminal QR | Conclusion from [VERIFIED] facts. `Origin` check to be verified via prototype |

---

## 2. QR Login (Remote Auth Gateway)

### 2.1 Connection

- **URL:** `wss://remote-auth-gateway.discord.gg/?v=2` **[VERIFIED]** (traffic + JS: `${GLOBAL_ENV.REMOTE_AUTH_ENDPOINT}/?v=2`,
  `REMOTE_AUTH_ENDPOINT = "wss://remote-auth-gateway.discord.gg"` in `window.GLOBAL_ENV`).
- Client calls standard `new WebSocket(url)` without subprotocols **[VERIFIED]** (JS, module `createWebSocket`).
  Server negotiated no extensions (`extensions = ""`, hence no `permessage-deflate`). Frames are plain JSON text **[VERIFIED]** (traffic).
- **Headers:** the browser cannot attach custom headers to WebSocket, so it sends standard ones only:
  `Origin: https://discord.com`, `User-Agent`, `Sec-WebSocket-*`. Client sets no other headers **[VERIFIED]** (JS).
  Whether the server **requires** `Origin: https://discord.com` could not be verified without an independent connection.
  Community implementations send it and report that without it the server rejects the connection **[ASSUMPTION]**.

### 2.2 Message Sequence (Observed)

Times are relative to socket opening. Values are replaced.

| # | Direction | Message | Note |
|---|---|---|---|
| 1 | server → client | `{"op":"hello","heartbeat_interval":41250,"timeout_ms":272373}` | arrived immediately after `open` (+1 ms) |
| 2 | client → server | `{"op":"init","encoded_public_key":"<SPKI DER, base64, 392 chars>"}` | +92 ms (RSA key generation) |
| 3 | server → client | `{"op":"nonce_proof","encrypted_nonce":"<base64 with padding, 344 chars = 256 B>"}` | |
| 4 | client → server | `{"op":"nonce_proof","nonce":"<base64url without '=', 254 chars = 190 B>"}` | +1 ms after 3 |
| 5 | server → client | `{"op":"pending_remote_init","fingerprint":"<base64url, 43 chars>"}` | client verifies match with own fingerprint and displays QR |
| 6 | client → server | `{"op":"heartbeat"}` | first after random delay `0 .. heartbeat_interval` (here +6.2 s), then every 41.25 s |
| 7 | server → client | `{"op":"heartbeat_ack"}` | ~115 ms after heartbeat |
| … | | (6 and 7 repeat) | |
| n | server | `close 4003 "Handshake Timeout"`, `wasClean=true` | exactly `timeout_ms` after open (12:23:14.93 + 272.37 s = 12:27:47.30) |

Everything above is **[VERIFIED]** (traffic, two complete sessions).

Messages arriving only after scanning were not captured (I did not scan the QR). Their shape is known from JS **[VERIFIED]** (JS):

| Direction | Message | Client action |
|---|---|---|
| server → client | `{"op":"pending_ticket","encrypted_user_payload":"<base64>"}` | decrypts RSA-OAEP → UTF-8 string, displays avatar + "Logging in as <username>" |
| server → client | `{"op":"pending_login","ticket":"<ticket>"}` | `POST /users/@me/remote-auth/login` (Section 2.6). If `ticket == null`, restarts session |
| server → client | `{"op":"cancel"}` | the user cancelled on phone → client discards session and opens new one (new QR) |
| server → client | other `op` | only `warn("received unsupported message")` |

The client never sends any `op` other than `init`, `nonce_proof`, and `heartbeat` **[VERIFIED]** (JS).
Upon cancellation or leaving the page, it simply closes the socket with code `1000` **[VERIFIED]** (JS).

> The older protocol (v1) had a `proof = base64url(SHA-256(nonce))` field instead of `nonce` and sent the token directly
> over the socket (`pending_finish`/`finish`). Version `v=2` replaced this with `pending_ticket` + `pending_login` + REST
> call **[ASSUMPTION]**. Older guides online may therefore be inaccurate.

### 2.3 Key and Parameters

From JS **[VERIFIED]**:
```js
crypto.subtle.generateKey({name:"RSA-OAEP", modulusLength:2048,
  publicExponent:new Uint8Array([1,0,1]), hash:"SHA-256"}, true, ["decrypt"])
encoded_public_key = btoa(exportKey("spki", publicKey))          // standard base64
decrypt = crypto.subtle.decrypt({name:"RSA-OAEP", hash:"SHA-256"}, privateKey, atob(x))
```
- RSA 2048-bit, public exponent 65537, OAEP with SHA-256 **[VERIFIED]** (JS).
- WebCrypto RSA-OAEP uses MGF1 with the same hash (SHA-256) and an empty label **[ASSUMPTION]** (WebCrypto specification).
  In Python `cryptography`, this corresponds to `padding.OAEP(mgf=MGF1(SHA256()), algorithm=SHA256(), label=None)`.
- Lengths in traffic match: SPKI 294 B → 392 base64 characters, and ciphertext 256 B → 344 characters **[VERIFIED]** (traffic).
- A fresh keypair is generated for **every** connection **[VERIFIED]** (JS).

### 2.4 Proof Calculation (Nonce Proof)

```
nonce_bytes = RSA_OAEP_SHA256_decrypt(private_key, base64decode(encrypted_nonce))
nonce       = base64url(nonce_bytes) without trailing '='     // '+'→'-', '/'→'_'
```
**[VERIFIED]** (JS `decryptNonce` → function `O`). The decrypted nonce was 190 B (254 characters) in both sessions.
That is the maximum for RSA-2048 with OAEP-SHA256 **[VERIFIED]** (traffic).

### 2.5 QR Content and Validity

- **Fingerprint** = `base64url(SHA-256(SPKI DER public key))` without padding, 43 characters **[VERIFIED]** (JS + traffic).
  Client compares its fingerprint with that from `pending_remote_init`. On mismatch, throws error `bad fingerprint` **[VERIFIED]** (JS).
- **QR text:** `https://discord.com/ra/<fingerprint>` **[VERIFIED]**. State: props of QR component matched the last
  `pending_remote_init.fingerprint`. Route `/ra/:remoteAuthFingerprint` exists on web as well **[VERIFIED]** (JS).
- Rendering: library `qrcode.react`, `level:"M"`, black on white, 160 px, Discord logo in center (overlay only, not
  part of data) **[VERIFIED]** (JS).
- Text length is 66 characters. At ECC M this yields QR version 5 (37 × 37 modules, with quiet zone 45 × 45) **[ASSUMPTION]** (calculation per QR standard).
- **Validity:** `timeout_ms` from `hello`. Observed values were 272,373 ms and 253,736 ms, i.e. ~4.2 – 4.5 min, randomised **[VERIFIED]** (traffic).
  Client logs this value only and does not use it for a timer **[VERIFIED]** (JS).
- **On expiration:** server closes socket (`4003 Handshake Timeout`). Client logs error and following backoff
  (min 1.5 s, max 30 s, with jitter) opens a new connection with a new key, thus generating a new QR **[VERIFIED]**.
  Traffic: new socket in 2.4 s, new `hello` and full handshake. JS: `new Backoff(1500, 30000)`.
  If tab is hidden, refresh is deferred until visible **[VERIFIED]** (JS). During QR refresh the page **did not call** any REST endpoint **[VERIFIED]** (network log).
- If `heartbeat_ack` does not arrive before next heartbeat, client closes socket and restarts session **[VERIFIED]** (JS).

### 2.6 Final Step After Confirmation on Phone

From JS **[VERIFIED]**:
```
POST https://discord.com/api/v9/users/@me/remote-auth/login
Content-Type: application/json
{"ticket": "<ticket from pending_login>"}

→ 200 {"encrypted_token": "<base64, RSA-OAEP-SHA256 ciphertext>"}
token = UTF-8( RSA_OAEP_SHA256_decrypt(private_key, base64decode(encrypted_token)) )
```
- Request uses shared HTTP client with global headers (Section 4.2) and no `Authorization`,
  as the user is unauthenticated **[VERIFIED]** (JS).
- Passes through **global captcha interceptor**: if server returns `400` with `captcha_key`, web displays captcha and
  retries request with headers `X-Captcha-Key`, `X-Captcha-Rqtoken`, and `X-Captcha-Session-Id` **[VERIFIED]** (JS).
  Whether Discord actually prompts for captcha on QR login is unverified. Typically not **[ASSUMPTION]**.
- On any error in this request, web discards session and starts over (new QR) **[VERIFIED]** (JS).
- On success, web calls `loginToken(token)` (dispatch `LOGIN_SUCCESS`) and connects to regular gateway **[VERIFIED]** (JS).
- Phone-side endpoints (authenticated scanning client): `POST /users/@me/remote-auth`,
  `/users/@me/remote-auth/finish`, `/users/@me/remote-auth/cancel` **[VERIFIED]** (names in endpoint table only, web does not call them).
  CLI does not need their request bodies **[ASSUMPTION]**.

### 2.7 What the Client Displays After Scanning

- `encrypted_user_payload` is decrypted identically to the token and the result must match regex
  `^(\d+):(\d{1,4}):([a-zA-Z0-9_]+):(.*)$` **[VERIFIED]** (JS):
  `"<user_id>:<discriminator>:<avatar_hash or 0>:<username>"`.
  `avatar == "0"` indicates no avatar. For new (pomelo) usernames, `discriminator` is `"0"` **[ASSUMPTION]**.
- UI: avatar (120 px), heading "Check your phone!", text "Logging in as <username>", and button
  "Not me, start over". Button locally discards session and opens a new one **[VERIFIED]** (JS + localization strings).
- Before scanning: "Log in with QR Code" / "Scan this with the Discord mobile app to log in instantly." **[VERIFIED]** (state).

### 2.8 Client State Machine

`INITIALIZING → PENDING_REMOTE_INIT (QR) → PENDING_TICKET (username) → PENDING_LOGIN (REST) → FINISH` **[VERIFIED]** (JS, enum).
Any error (close, socket error, bad fingerprint, REST error, missing ticket, `cancel`) transitions back to `INITIALIZING` with backoff.

---

## 3. Email and Password Login (JS Only, Nothing Sent)

### 3.1 Login

```
POST /api/v9/auth/login
{"login": "<email or phone>", "password": "<password>", "undelete": false,
 "login_source": null, "gift_code_sku_id": null}
```
**[VERIFIED]** (JS `AuthenticationActionCreators.login`, `retries:2`). For phone login, client prepends country dialing code before `login` **[VERIFIED]** (JS).

**Responses** (fields read by client) **[VERIFIED]** (JS):
- **Success:** `{ "token": "<token>", "user_id": "<id>", "required_actions": [...]? }`
- **MFA required:** `{ "mfa": true, "ticket": "<mfa ticket>", "totp": bool, "sms": bool, "backup": bool,
  "webauthn": "<JSON string with WebAuthn challenge>" | null, "login_instance_id": "<id>", "user_id": "<id>" }`.
  From this client constructs method options in order `webauthn`, `totp`, `backup`, `sms`.
- **Captcha:** HTTP `400` with `captcha_key` (array). Other fields read by client: `captcha_service`
  (`hcaptcha` | `recaptcha` | `recaptcha_enterprise` | `turnstile`), `captcha_sitekey`, `captcha_session_id`,
  `captcha_rqdata`, `captcha_rqtoken`, `should_serve_invisible`, `user_flow`. Retry sends headers
  `X-Captcha-Key: <solution>`, `X-Captcha-Rqtoken`, and `X-Captcha-Session-Id` **[VERIFIED]** (JS).
- **Errors by `code`:** `20011` account scheduled for deletion (allows `undelete`), `20013` account disabled,
  `70007` phone verification required ("IP authorization"), `suspended_user_token` indicates suspended account. Otherwise generic form
  error (`50035` Invalid Form Body) **[VERIFIED]** (JS, code map).
- New location verification (email "Verify login location") uses `POST /auth/authorize-ip {token}` **[VERIFIED]** (endpoint name and body).
  Under what conditions the server requires it is an **[ASSUMPTION]**.

### 3.2 MFA Endpoints

```
POST /api/v9/auth/mfa/{totp|sms|backup|webauthn}
{"code": "<code>", "ticket": "<mfa ticket>", "login_source": null,
 "gift_code_sku_id": null, "login_instance_id": "<from login response>"}
→ {"token": "<token>"}
```
**[VERIFIED]** (JS `loginMFAv2`, `retries:2`). Error `60008` = invalid code **[VERIFIED]** (JS).
- `totp`: 6 digits **[VERIFIED]** (JS, constant 6).
- `sms`: first `POST /auth/mfa/sms/send {"ticket"}` → `{"phone":"<masked number>"}`, then code (6 digits) **[VERIFIED]** (JS).
- `backup`: backup code without hyphens, 8 to 11 characters **[VERIFIED]** (JS, constants 8 and 11, `replace(/-/g,"")`).
- `webauthn`: `code` is a JSON string with WebAuthn assertion (`id`, `rawId`, `response.{authenticatorData,
  clientDataJSON, signature, userHandle}`, all base64url) **[VERIFIED]** (JS). Impractical in a terminal.
- Outside login: `POST /mfa/finish {ticket, mfa_type, data}` → header `X-Discord-MFA-Authorization` for sensitive
  actions in authenticated state **[VERIFIED]** (JS). Not needed for CLI.

---

## 4. What the Page Calls Prior to Login

### 4.1 Requests (Observed)

| Request | Response (structure) | Purpose |
|---|---|---|
| `GET /api/v9/experiments?with_guild_experiments=true` | `{"fingerprint":"<snowflake>.<~27 chars>","assignments":[...],"guild_experiments":[...]}` | **source of `X-Fingerprint`** |
| `GET /api/v9/apex/experiments?surface=2` | `{"assignments":{"1":{"<id>":{"evaluation_id":"…","assignments":[...]}}}}` | experiments |
| `GET /api/v9/auth/location-metadata` | `{"consent_required":bool,"country_code":"<2 letters>","minimum_age":null,"promotional_email_opt_in":{"required":bool,"pre_checked":bool}}` | GDPR/age rules for registration |
| `POST /api/v9/auth/conditional/start` | `{"challenge":"<JSON string: {publicKey:{challenge, timeout:300000, rpId:'discord.com', allowCredentials:[], userVerification:'required', extensions:{uvm:true}}, mediation:'conditional'}>","ticket":"<uuid>"}` | passkey autofill (Section 5) |
| `POST /api/v9/science` → `204` | – | analytics (`LOGIN_VIEWED`, `REGISTER_VIEWED`, …) |
| `wss://remote-auth-gateway.discord.gg/?v=2` | Section 2 | QR |

All **[VERIFIED]** (traffic). Caveat: network buffer held only the last 500 requests, so the very first
requests upon page load (prior to `experiments`) may have dropped out.

### 4.2 Request Headers (Names Only, from JS)

HTTP client adds them to every request to `/api/...` **[VERIFIED]** (JS `prepareRequest`). Real headers
in traffic were not visible; the tool does not expose them.
- `Authorization` (only if token exists)
- `X-Super-Properties`: base64 JSON with keys `os`, `browser`, `device`, `system_locale`, `has_client_mods`,
  `browser_user_agent`, `browser_version`, `os_version`, `referrer`, `referring_domain`, `*_current`,
  `release_channel`, `client_build_number`, `client_event_source`, `client_launch_id`, `client_heartbeat_session_id`, `client_app_state`
- `X-Fingerprint`: `fingerprint` value from `/experiments`. On subsequent loads retrieved from local storage
- `X-Installation-ID` (if allocated by server; absent in this response)
- `X-Discord-Locale`, `X-Discord-Timezone`
- `X-Debug-Options`, `X-Routing-Key`, `x-client-trace-id` (debug/tracing mode only)
- `Accept-Language` (desktop app only)
- `Content-Type: application/json` for request bodies
- on captcha retry: `X-Captcha-Key`, `X-Captcha-Rqtoken`, `X-Captcha-Session-Id`
- on invites: `X-Context-Properties`

What login actually requires from this: probably nothing beyond the JSON body. `X-Super-Properties` and `X-Fingerprint`
may, however, influence whether the server prompts for a captcha **[ASSUMPTION]**. Discord sets Cloudflare/anti-bot
cookies in responses (`__dcfduid`, `__sdcfduid`, `__cfruid`, `_cfuvid`) **[ASSUMPTION]** (cookies were not read, adhering to rules).

---

## 5. Other Login Methods

Endpoint names from JS endpoint table **[VERIFIED]**:
- **Passkey, conditional UI (autofill):** `POST /auth/conditional/start` → `navigator.credentials.get({mediation:"conditional"})`
  → `POST /auth/conditional/finish {credential, ticket, source, giftCodeSKUId}` → `{token, user_id, required_actions}`.
  Runs **automatically** on every display of login form if browser reports
  `isConditionalMediationAvailable()` or `getClientCapabilities().conditionalGet` **[VERIFIED]** (JS + traffic: 3× `conditional/start`).
- **Passkey, button "Or sign in with a passkey":** `POST /auth/passwordless/start` → `navigator.credentials.get` → `POST /auth/conditional/finish` **[VERIFIED]** (JS).
- **SSO:** login page has no Google/Apple/SSO buttons **[VERIFIED]** (state). `GET /sso` and `/sso-token` serve to
  log into third-party services using Discord account (parameter `service`). Not login into Discord **[VERIFIED]** (JS).
- **Other token flows:** `POST /auth/one-time-login {ticket}` → `{token}`; handoff from desktop app
  `POST /auth/handoff {key}` → `{handoff_token}` and `POST /auth/handoff/exchange {key, handoff_token}` → `{token, user}`;
  `POST /auth/verify {token}` (email verification, returns token) **[VERIFIED]** (JS). Unusable for CLI without browser or app **[ASSUMPTION]**.
- **OAuth2 device flow:** `/oauth2/device/verify` and `/oauth2/device/finish` exist **[VERIFIED]** (names).
  Used for linking consoles and applications. Does not return user token **[ASSUMPTION]**.

---

## 6. Consequences for the CLI Tool

### 6.1 Can QR Login Be Implemented Entirely Without a Browser?

**Yes.** The entire protocol consists of plain WebSocket with JSON messages, RSA-OAEP-SHA256, and a single REST POST. Client
uses nothing browser-exclusive: no captcha in QR flow, no device attestation, no cookies in WebSocket
handshake (findings from [VERIFIED] JS and traffic). Whether the server tolerates non-browser clients remains unverified (Section 7).

**Requirements (Python, cross-platform Windows/Linux/macOS):**

| Component | Library | Note |
|---|---|---|
| WebSocket | `websockets` (asyncio) | set header `Origin: https://discord.com` and reasonable `User-Agent` |
| Crypto | `cryptography` | `rsa.generate_private_key(65537, 2048)`, SPKI DER (`PublicFormat.SubjectPublicKeyInfo`), `OAEP(MGF1(SHA256), SHA256, None)` |
| REST | `httpx` (already planned) | `POST /api/v9/users/@me/remote-auth/login`, then `GET /users/@me` for verification |
| Terminal QR | `segno` or `qrcode` | ECC **M**, dark modules on light background, 4-module quiet zone, half-block rendering (`▀▄█`, ~45 columns × 23 rows) |
| Token storage | `keyring` | Windows Credential Manager, macOS Keychain, Linux Secret Service. Backend may be absent on headless Linux, requires fallback (file with `0600` permissions) |

**Proposed flow for `discoop login`:**
1. Connect to `wss://remote-auth-gateway.discord.gg/?v=2` (with `Origin`).
2. Receive `hello`, start heartbeat (first after `random() * interval`, then every `interval`). Reconnect if `heartbeat_ack` is missed.
3. Generate RSA-2048 and send `init`.
4. On `nonce_proof`, decrypt nonce and send `{"op":"nonce_proof","nonce":base64url(nonce)}`.
5. On `pending_remote_init`, verify fingerprint and render QR `https://discord.com/ra/<fingerprint>`.
   Print instructions "scan in Discord app (Settings → Scan QR Code)" and countdown from `timeout_ms`.
6. On `pending_ticket`, decrypt payload and print "Logging in as <username>, confirm on your phone".
7. On `pending_login`, call REST, decrypt `encrypted_token`, verify via `GET /users/@me`, save to keyring, and close socket.
8. On `cancel` or `4003`, generate new QR. After N attempts (e.g. 3, ~13 min), exit with non-zero exit code.
9. In `--agent` mode, also print raw QR text (URL) and wait. A human can scan it from another location.

### 6.2 Risks

- **`Origin` check:** without proper header gateway may reject connection **[ASSUMPTION]**. Solved with a single header.
- **Captcha on `remote-auth/login`:** HTTP client handles it **[VERIFIED]** (JS). If server starts requiring it,
  terminal cannot resolve it and fallback is required (6.3).
- **Protocol changes:** `v=2` is already the second version. Discord may change it or add client checks at any time.
  Tool should provide a clear error message on unknown `op` or unexpected close code, offering fallback.
- **Non-browser client detection:** Cloudflare/TLS fingerprint on REST call, missing `X-Super-Properties`.
  May lead to captcha or request blocking **[ASSUMPTION]**.
- **ToS and account safety:** token obtained via QR is a full user token. Discord registers a new session in device list
  **[ASSUMPTION]**. Automated use of a user token violates ToS; the user accepts this.
- **Security:** QR is effectively a login link. Must not enter logs, history, or agent output that
  could be forwarded. Never log token or fingerprint.

### 6.3 Fallbacks (Recommended Order)

1. **Manual token entry** (`discoop login --token`, input via hidden prompt or stdin, not command-line argument in shell history).
   Works everywhere and simplest. Drawback: the user must extract token from DevTools.
2. **Browser-based login** (original guide in `design.md` 4.1, Playwright).
   Handles captcha, 2FA, and passkeys. Requires Chrome/Chromium installed on Linux/macOS, heavier dependency.
   Warning: on Windows opening `/login` may trigger passkey prompt automatically (Section 8).
3. **Email/password + TOTP via API** (`/auth/login` → `/auth/mfa/totp`). Technically simple, but a non-browser client
   is likely to encounter captcha frequently **[ASSUMPTION]**. The tool would also have to handle passwords. Not recommended as
   primary path; experimental at most.

### 6.4 Impact on Design (`design.md` Was Not Edited)

- Section 3 ("Login: Playwright + installed Chrome") and Section 4.1 would change under new requirements to QR login via
  `websockets` + `cryptography`. Playwright would remain as optional fallback.
- Technology table: `keyring` is not just "Windows Credential Manager". On Linux, a missing Secret Service must be handled.
- New dependencies: `websockets`, `cryptography`, `segno` (or `qrcode`).

---

## 7. Unverified / Open Questions

> **Added 2026-11-03, prototype** (`discoop login --handshake-only --trace`, without login):
> - Gateway **accepted non-browser client** (Python `websockets`, `Origin: https://discord.com`,
>   `User-Agent: discoop/0.1.0`) and completed full handshake up to `pending_remote_init` **[VERIFIED]** (prototype).
> - Field lengths match analysis: `encoded_public_key` 392, `encrypted_nonce` 344, `nonce` 254, `fingerprint` 43 characters.
> - `heartbeat_interval` 41,250 ms, `timeout_ms` 245,280 ms (within ~4 – 4.5 min range).
>
> **Added 2026-11-03, first real login** (`discoop login --trace`, the user scanned QR) **[VERIFIED]** (prototype):
> - **Full flow succeeded without browser and without captcha:**
>   `pending_remote_init` → (scan after ~52 s) `pending_ticket` → (confirmation after ~16 s) `pending_login`
>   → `POST /users/@me/remote-auth/login` `200` → token verified via `GET /users/@me`.
> - **Shapes match JS:**
>   - `pending_ticket.encrypted_user_payload` 344 characters (256 B RSA),
>   - `pending_login.ticket` 70 characters,
>   - response `{"encrypted_token": <344 characters>}`.
> - **Heartbeats** while awaiting scan and confirmation operated normally (`heartbeat` → `heartbeat_ack` ~110 ms).
> - **`timeout_ms` was 344,035 ms (~5.7 min).** QR validity varies more than shown by initial analysis (~4 – 5.7 min).

- Whether gateway **requires** `Origin: https://discord.com`: works with it (see above). Untested without it.
  Close codes on rejection unknown.
- Shape and content of `pending_ticket`, `pending_login`, `cancel`, and `remote-auth/login` response was known only from source code.
  Real frames not inspected in initial run (QR was not scanned).
- Whether `POST /users/@me/remote-auth/login` triggers captcha for non-browser client and whether it needs
  `X-Super-Properties`, `X-Fingerprint`, or Cloudflare cookies.
- Other gateway close codes besides `4003 Handshake Timeout`.
- Whether token from QR login has restrictions compared to normal login token.
- Real request headers (visible in JS only, not in traffic).
- Real responses of `/auth/login` and `/auth/mfa/*` (JS only, nothing sent).
- Whether nonce length (190 B) is fixed or coincidentally identical across two sessions.
- Very first requests on page load (dropped from network buffer).

---

## 8. Side Effects of the Analysis

1. **Windows Security passkey prompt ("Making sure it's you… Insert your security key").**
   - **Cause:** login page automatically calls `POST /api/v9/auth/conditional/start` and immediately
     `navigator.credentials.get({publicKey, mediation:"conditional"})` on **every** render of login form
     **[VERIFIED]** (JS: module `ConditionalMediation` in `541cc3384b699976.js` called in `useMount` of login page).
     In regular Chrome this is silent autofill. Built-in browser on Windows forwarded it to Windows WebAuthn as a modal prompt.
   - **Actions that triggered it:**
     - opening `https://discord.com/login` via `preview_start` (12:22:20 UTC). During initial load, **2×** `conditional/start` occurred.
     - click on "Already have an account? Log in" on `/register` (~12:23:14 UTC). Remounted login form and triggered a **3rd** `conditional/start`.
     - **This click was my last action before the prompt appeared.** Exact time prompt appeared is unknown, so prompt may have
       originated on initial load.
   - Did not click anything passkey-related, did not focus email/password fields, and did not call or wrap `navigator.credentials`.
     Did not navigate or reload page after the prompt.
   - Server issued 3 conditional challenges with `ticket`, validity `timeout: 300000` ms. Unused challenges expire.
2. **Remote-auth sessions:** gateway observed 3 QR sessions (1 on initial load, 1 after navigation, 1 automatic refresh
   after expiry). Tab remained open on `/login` (I do not close tabs), so page will generate a new QR every ~4.5 min while tab is visible.
   Nobody scanned anything; no login occurred.
3. **Analytics:** page sent `POST /api/v9/science` (login and register page view) from unauthenticated browser.
4. **JS download:** ~630 public JS files fetched from page context (`force-cache`, no cookies) for inspection. Most served from cache.
5. **In-page observer:** wrapper around `window.WebSocket` remains in tab until reload. At the end switched to no-op (records nothing),
   deleted captured frames and downloaded JS from page memory. Did not store live values to disk.
6. No keyboard input, no forms submitted, no socket messages sent, no custom API calls, no reading cookies or tokens.
