<p align="center">
  <img src="https://raw.githubusercontent.com/Fischherboot/M-Wiki/refs/heads/main/img/logo.png" alt="M-WIKI" width="700">
</p>

<p align="center">
  <strong>Selbst gehostetes Wiki für interne Doku.</strong><br>
  Klassisches Darkmode-Layout · Markdown · Wikilinks · Mobile-SPA 
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Lizenz-MSOL-blue" alt="Lizenz">
  <img src="https://img.shields.io/badge/Backend-FastAPI-009688" alt="FastAPI">
  <img src="https://img.shields.io/badge/Datenbank-SQLite-003B57" alt="SQLite">
  <img src="https://img.shields.io/badge/Templates-Jinja2-B41717" alt="Jinja2">
  <img src="https://img.shields.io/badge/Frontend-Vanilla_JS-f7df1e" alt="JS">
</p>

---

## Was ist M-WIKI?

M-WIKI ist ein leichtgewichtiges, selbst gehostetes Wiki für Homelabs, kleine Teams und interne Doku. **FastAPI + SQLite + Jinja2**, eine `daten.json` mit Klartext-Login, ein Port, ein systemd Service. Topics mit Markdown, **Wikilinks** im klassischen `[[Titel]]`-Stil, hierarchische Kategorien, Drag&Drop-Bilder, Volltextsuche und eine separate **Mobile-SPA** unter `/app/`. Keine Cloud. Keine Accounts bei Dritten. Kein Schnickschnack — schlichtes Schwarz/Anthrazit mit dem Moritzsoft-Gradient nur auf den Titeln.

---

## Screenshots

### Login

![BILD_LINK_HIER_—_Login-Seite_mit_zentrierter_Login-Karte,_dunkler_Hintergrund,_Moritzsoft-Gradient_auf_dem_Titel,_Username-_und_Passwort-Feld](https://raw.githubusercontent.com/Fischherboot/M-Wiki/refs/heads/main/img/login.png)

> Klassischer Session-Cookie-Login. Userdaten in `daten.json` (Klartext, beabsichtigt — Datei nicht extern erreichbar). Cookie ist signiert via `itsdangerous`, `httponly`, `samesite=lax`, 30 Tage.

### Hauptseite — Dashboard mit Kategorien-Baum

![BILD_LINK_HIER_—_Hauptseite_mit_Sidebar_links_(hierarchischer_Kategorien-Baum),_Topic-Liste_mittig,_Recent-Topics_rechts,_Wiki-Titel_mit_Gradient_in_der_Topbar](https://raw.githubusercontent.com/Fischherboot/M-Wiki/refs/heads/main/img/hauptbildschirm.png)

> Die Hauptansicht. Sidebar mit aufklappbarem Kategorien-Baum, Topic-Liste im Hauptbereich, "Recent" rechts. Wiki-Titel wird aus `daten.json` gelesen und erscheint mit Gradient in der Topbar.

### Neues Topic anlegen — Editor

![BILD_LINK_HIER_—_Editor-Seite_mit_Titel-Input,_großem_Markdown-Textarea,_Kategorie-Dropdown,_Live-Vorschau_rechts,_Upload-Button_und_Wikilink-Vorschlagsleiste_unten_rechts](https://raw.githubusercontent.com/Fischherboot/M-Wiki/refs/heads/main/img/newtopic.png)

> Markdown-Editor mit Live-Vorschau, Kategorie-Zuweisung und Drag&Drop für Bilder. Erkennt im Text erwähnte vorhandene Topics und schlägt unten rechts an, sie automatisch zu `[[Wikilinks]]` zu konvertieren — ein Klick und alle Vorkommen werden umgewandelt.

---

## Features

- **Topics mit Markdown** — Bilder per Drag&Drop, Paste aus der Zwischenablage oder Upload-Button
- **Wikilinks** — `[[Titel]]` oder `[[Titel|Anzeigetext]]`. Tote Links erscheinen rot und führen zu einem vorausgefüllten Neu-Anlegen-Formular
- **Auto-Vorschläge** — der Editor erkennt im Text erwähnte vorhandene Topics und bietet einen Klick zum Verlinken
- **Hierarchische Kategorien** — Kategorie → Unterkategorie → … beliebig tief
- **Kommentare** pro Topic — für schnelle Notizen ohne den Hauptinhalt zu verändern
- **Volltextsuche** über Titel und Inhalt mit Snippets — Desktop-Form _und_ saubere `/api/search`-API
- **Mobile-SPA** unter `/app/` mit Hash-Routing, eigenem CSS und eigenem JS-Bundle
- **Auto-Redirect** für Mobile-User-Agents auf `/app/`, mit "Desktop-Version"-Override per Cookie
- **Bild-Pipeline** — Pillow `verify()` gegen Mime-Fakes, Auto-Downscale auf 2000px, 10 MB Limit
- **Security-Headers** auf jeder Response: CSP, X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy
- **systemd-Hardening** — `ProtectSystem=strict`, `PrivateTmp`, `NoNewPrivileges`, `MemoryDenyWriteExecute`, `SystemCallFilter`
- **Ein-Befehl-Setup** — `sudo ./install.sh` macht User, Pfade, venv, systemd-Unit, Healthcheck

---

## Schnellstart

```bash
git clone <repo> mwiki
cd mwiki
sudo ./install.sh
```

Das war's. `install.sh` macht alles in einem Rutsch:

- legt System-User `mwiki` an
- kopiert nach `/opt/mwiki`
- erstellt venv & installiert `requirements.txt`
- generiert die systemd-Unit `m-wiki-service.service` (mit Hardening)
- enabled & startet den Service
- macht einen Healthcheck

**Idempotent:** beim zweiten Lauf wird _aktualisiert_ — `daten.json`, `wiki.db` und `uploads/` bleiben erhalten.

### Konfigurierbar via ENV

```bash
sudo INSTALL_DIR=/srv/wiki PORT=8080 SERVICE_NAME=m-wiki-service \
     SERVICE_USER=mwiki ./install.sh
```

### Deinstallieren

```bash
sudo ./install.sh --uninstall
```

Stoppt den Service, entfernt die Unit-Datei, fragt ob Verzeichnis & User mitgelöscht werden sollen.

---

## Manueller Start (zum Testen)

```bash
python3 -m venv venv
. venv/bin/activate
pip install -r requirements.txt
./start.sh
```

Default-Port: **3503**. Erster Start erzeugt `daten.json` mit Default-User `moritz` / `123` und einem zufälligen Session-Secret.

---

## Architektur

```
┌─────────────────────────────────────────────┐
│   Desktop-Browser              Mobile-UA    │
│        │                           │        │
│        ▼                           ▼        │
│   GET /                       GET / → /app/ │
└────────────┬────────────────────────┬───────┘
             │                        │
             │   HTTP + Session-Cookie│
┌────────────▼────────────────────────▼───────┐
│       FastAPI + uvicorn (Port 3503)         │
│  ┌────────────────┐  ┌──────────────────┐   │
│  │ Jinja2-Templates│  │ /api/* (JSON)    │   │
│  │ (Desktop-Build) │  │ für Mobile-SPA   │   │
│  └────────────────┘  └──────────────────┘   │
│  ┌────────────────────────────────────────┐ │
│  │ Markdown-Renderer + Wikilink-Parser   │ │
│  │ + Pillow Upload-Validation            │ │
│  └────────────────────────────────────────┘ │
│  ┌────────────────────────────────────────┐ │
│  │ SQLite (WAL-Mode) │ daten.json (Auth) │ │
│  └────────────────────────────────────────┘ │
└─────────────────────────────────────────────┘
            │                        │
       wiki.db                  uploads/
       (Topics, Kategorien,     (Bilder, validiert
        Kommentare)              via Pillow.verify)
```

---

## Konfiguration: `daten.json`

```json
{
  "wiki_title": "Moritzsoft Wiki",
  "session_secret": "<wird beim ersten Start generiert>",
  "users": [
    { "username": "moritz", "password": "123" }
  ]
}
```

- `wiki_title` erscheint groß auf der Startseite und in der Topbar
- `users` ist eine Liste, beliebig viele User möglich
- `session_secret` mit Prefix `BITTE…` wird beim Start automatisch durch ein zufälliges ersetzt
- Änderungen erfordern einen Neustart: `systemctl restart m-wiki-service`

---

## Wikilinks

Im Editor:

```
Auf [[Switch 12]] verbunden zur Wartung.
Siehe auch [[Redemption1|den großen Roten]].
```

Schreibt man stattdessen einfach den Topic-Namen ohne Klammern, schlägt der Editor unten rechts vor, das automatisch zu verlinken — ein Klick und alle Vorkommen werden umgewandelt.

Existiert das Ziel-Topic nicht, wird der Link rot dargestellt und der Klick führt zu einem vorausgefüllten Neu-Anlegen-Formular. In der Mobile-App funktioniert das genauso (`#/topic/new?title=…`).

---

## Mobile-Auto-Redirect

| Situation | Verhalten |
|---|---|
| Desktop-Browser auf `/` | Normaler Desktop-Build |
| Mobile-Browser auf `/` | Redirect zu `/app/` |
| "Desktop-Version" in der Mobile-App | Setzt Cookie `prefer_desktop=1` (1 Jahr), kein Auto-Redirect mehr |
| "Mobile App" Link in der Desktop-Sidebar | Löscht den Cookie wieder |

User-Agent-Match: `Mobi`, `Android`, `iPhone`, `iPod`, `BlackBerry`, `IEMobile`, `Opera Mini`, `webOS`.

---

## API

Alles auth-protected, gleicher Cookie wie das Frontend.

| Endpoint | Zweck |
|---|---|
| `GET /api/topics` | Liste aller Topics (id, title) — für Wikilink-Autocomplete |
| `GET /api/tree` | Kategorien-Baum mit Topics |
| `GET /api/topic/{id}` | Einzelnes Topic mit gerendertem HTML + Kommentaren |
| `GET /api/recent` | Letzte 20 Topics |
| `GET /api/search?q=…` | Suchergebnisse als JSON (für die Mobile-App) |
| `GET /healthz` | Healthcheck (kein Auth) |

---

## Backup

Alles Relevante steckt in drei Pfaden:

- `wiki.db` — SQLite-Datenbank (mit WAL: vor dem Sichern `wal_checkpoint(TRUNCATE)`)
- `uploads/` — hochgeladene Bilder
- `daten.json` — Login + Wiki-Titel

```bash
sqlite3 /opt/mwiki/wiki.db "PRAGMA wal_checkpoint(TRUNCATE);"
sudo tar czf mwiki-backup-$(date +%F).tar.gz \
    -C /opt/mwiki wiki.db uploads daten.json
```

---

## Verzeichnisstruktur

```
mwiki/
├── install.sh                  # Setup-Script (idempotent)
├── m-wiki-service.service      # Reference unit (install.sh schreibt das automatisch)
├── main.py                     # FastAPI App
├── daten.json                  # Konfiguration (Login + Titel)
├── requirements.txt
├── start.sh                    # lokales Testen ohne systemd
├── wiki.db                     # SQLite (wird beim ersten Start angelegt)
├── uploads/                    # Hochgeladene Bilder
├── static/
│   ├── style.css               # Desktop
│   ├── app.css                 # Mobile
│   ├── wiki.js                 # Desktop-Editor
│   └── app.js                  # Mobile-SPA
└── templates/
    ├── base.html
    ├── _cat_node.html
    ├── index.html
    ├── login.html
    ├── topic.html
    ├── edit.html
    ├── category.html
    ├── search.html
    ├── error.html
    └── app.html                # Mobile-SPA Shell
```

---

## Sicherheit

- **XSS in Wikilinks gefixt** — Display- und Target-Text werden HTML-escaped
- **Security-Headers** auf jeder Response: CSP, X-Content-Type-Options, X-Frame-Options, Referrer-Policy, Permissions-Policy
- **Open-Redirect-Schutz** auf `?next=…` (nur relative Pfade ohne `//` erlaubt)
- **Server-side Längen-Limits** für Titel, Inhalt, Kommentare, Kategorie-Namen — nicht nur HTML `maxlength`
- **Upload-Validierung** mit Pillow `verify()` — Datei wird auf echtes Bild geprüft, sonst gelöscht
- **Pfad-Traversal** in `/uploads/{filename}` blockiert
- **Session-Cookie** signiert (`itsdangerous`), `httponly`, `samesite=lax`, 30 Tage
- **SQLite WAL-Mode** für bessere Concurrency
- **systemd-Hardening**: `ProtectSystem=strict`, `PrivateTmp`, `NoNewPrivileges`, `MemoryDenyWriteExecute`, `SystemCallFilter` — installierter Service kann nichts außerhalb von `/opt/mwiki` schreiben
- **Login-Daten im Klartext** in `daten.json` — Datei wird auf `0640` gesetzt und ist nicht über HTTP erreichbar
- **Empfehlung**: Cloudflare Zero Trust Access vorschalten

---

## Service-Management nach Installation

```bash
sudo systemctl status m-wiki-service
sudo systemctl restart m-wiki-service
sudo systemctl stop m-wiki-service
sudo journalctl -u m-wiki-service -f      # Live-Logs
```

---

## Ressourcenverbrauch

Bewusst minimal gehalten. Keine externen Services, keine Caches, keine Hintergrund-Worker. SQLite + ein uvicorn-Prozess. Gesamter Footprint inklusive Python-venv unter **120 MB RAM** im Leerlauf, **wiki.db** bleibt unter wenigen MB selbst bei mehreren hundert Topics.

---

## Lizenz

<p align="center">
  <a href="https://moritzsoft.de/#license">Moritzsoft Open License (MSOL) v1.1</a>
</p>
