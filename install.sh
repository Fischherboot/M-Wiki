#!/usr/bin/env bash
# =============================================================================
# M-WIKI Installer
# Installiert M-WIKI nach /opt/mwiki und startet es als systemd-Service
# `m-wiki-service.service`.
#
# Verwendung:
#   sudo ./install.sh                      # frische Installation oder Update
#   sudo ./install.sh --uninstall          # Service & Dateien entfernen
#
# Konfigurierbar via ENV-Variablen:
#   INSTALL_DIR=/opt/mwiki    SERVICE_NAME=m-wiki-service
#   SERVICE_USER=mwiki        SERVICE_GROUP=mwiki
#   PORT=3503                 HOST=0.0.0.0
#   PYTHON=python3
# =============================================================================

set -euo pipefail

# ---- Defaults --------------------------------------------------------------
INSTALL_DIR="${INSTALL_DIR:-/opt/mwiki}"
SERVICE_NAME="${SERVICE_NAME:-m-wiki-service}"
SERVICE_USER="${SERVICE_USER:-mwiki}"
SERVICE_GROUP="${SERVICE_GROUP:-mwiki}"
PORT="${PORT:-3553}"
HOST="${HOST:-0.0.0.0}"
PYTHON="${PYTHON:-python3}"

UNIT_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

# ---- Colors ----------------------------------------------------------------
if [ -t 1 ]; then
    RED='\033[0;31m'; GRN='\033[0;32m'; YLW='\033[1;33m'
    BLU='\033[0;36m'; BLD='\033[1m'; RST='\033[0m'
else
    RED=''; GRN=''; YLW=''; BLU=''; BLD=''; RST=''
fi

log()   { echo -e "${BLU}[*]${RST} $*"; }
ok()    { echo -e "${GRN}[+]${RST} $*"; }
warn()  { echo -e "${YLW}[!]${RST} $*"; }
err()   { echo -e "${RED}[x]${RST} $*" >&2; }

# ---- Sanity checks ---------------------------------------------------------
require_root() {
    if [ "$(id -u)" -ne 0 ]; then
        err "Bitte als root ausführen (sudo $0)"
        exit 1
    fi
}

require_systemd() {
    if ! command -v systemctl &>/dev/null; then
        err "systemctl nicht gefunden – braucht ein systemd-System."
        exit 1
    fi
}

# ---- Uninstall -------------------------------------------------------------
do_uninstall() {
    require_root
    require_systemd

    log "Deinstalliere M-WIKI…"

    if systemctl list-unit-files | grep -q "^${SERVICE_NAME}.service"; then
        systemctl stop "${SERVICE_NAME}.service" 2>/dev/null || true
        systemctl disable "${SERVICE_NAME}.service" 2>/dev/null || true
        ok "Service gestoppt und disabled"
    fi

    if [ -f "$UNIT_FILE" ]; then
        rm -f "$UNIT_FILE"
        systemctl daemon-reload
        ok "Unit-Datei entfernt: $UNIT_FILE"
    fi

    if [ -d "$INSTALL_DIR" ]; then
        echo
        warn "Verzeichnis $INSTALL_DIR enthält ggf. Daten (wiki.db, uploads/, daten.json)."
        read -rp "    Verzeichnis komplett löschen? [y/N] " ans
        if [[ "$ans" =~ ^[Yy]$ ]]; then
            rm -rf "$INSTALL_DIR"
            ok "Verzeichnis entfernt: $INSTALL_DIR"
        else
            log "Verzeichnis bleibt: $INSTALL_DIR"
        fi
    fi

    if id "$SERVICE_USER" &>/dev/null; then
        read -rp "    System-User '$SERVICE_USER' löschen? [y/N] " ans
        if [[ "$ans" =~ ^[Yy]$ ]]; then
            userdel "$SERVICE_USER" 2>/dev/null || true
            ok "User entfernt: $SERVICE_USER"
        fi
    fi

    ok "Deinstallation abgeschlossen."
    exit 0
}

# ---- Argument parsing ------------------------------------------------------
if [ "${1:-}" = "--uninstall" ] || [ "${1:-}" = "-u" ]; then
    do_uninstall
fi
if [ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ]; then
    sed -n '2,16p' "$0" | sed 's/^# \?//'
    exit 0
fi

# ---- Install ---------------------------------------------------------------
require_root
require_systemd

if ! command -v "$PYTHON" &>/dev/null; then
    err "$PYTHON nicht gefunden. Bitte installieren."
    exit 1
fi

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Idiotensicherheit: gleicher Pfad?
if [ "$(readlink -f "$SRC_DIR")" = "$(readlink -f "$INSTALL_DIR" 2>/dev/null || echo "")" ]; then
    err "Source und Install-Verzeichnis sind identisch ($INSTALL_DIR)."
    err "Kopiere das Repo woanders hin oder setze INSTALL_DIR auf einen anderen Pfad."
    exit 1
fi

if [ ! -f "$SRC_DIR/main.py" ] || [ ! -f "$SRC_DIR/requirements.txt" ]; then
    err "Source-Verzeichnis enthält nicht main.py + requirements.txt:"
    err "  $SRC_DIR"
    exit 1
fi

IS_UPDATE=false
if [ -f "$UNIT_FILE" ] || [ -d "$INSTALL_DIR/venv" ]; then
    IS_UPDATE=true
fi

echo
echo -e "${BLD}M-WIKI Installer${RST}"
echo "  Source:        $SRC_DIR"
echo "  Install dir:   $INSTALL_DIR"
echo "  Service:       ${SERVICE_NAME}.service"
echo "  User/Group:    $SERVICE_USER:$SERVICE_GROUP"
echo "  Listen:        $HOST:$PORT"
echo "  Modus:         $([ "$IS_UPDATE" = true ] && echo "UPDATE" || echo "FRESH INSTALL")"
echo

# --- 1. python3-venv ggf. nachinstallieren
log "Prüfe System-Abhängigkeiten…"
if ! "$PYTHON" -m venv --help &>/dev/null 2>&1; then
    warn "python3-venv fehlt – versuche zu installieren…"
    if command -v apt-get &>/dev/null; then
        apt-get update -qq
        apt-get install -y python3-venv python3-pip
    elif command -v dnf &>/dev/null; then
        dnf install -y python3-virtualenv python3-pip
    elif command -v pacman &>/dev/null; then
        pacman -S --noconfirm python python-pip
    else
        err "Kein bekannter Paketmanager. Installiere python3-venv manuell."
        exit 1
    fi
fi
ok "python3-venv verfügbar"

# --- 2. System-User
if ! id "$SERVICE_USER" &>/dev/null; then
    log "Lege System-User '$SERVICE_USER' an…"
    useradd --system --no-create-home --shell /usr/sbin/nologin \
        --home-dir "$INSTALL_DIR" "$SERVICE_USER"
    ok "User angelegt: $SERVICE_USER"
else
    ok "User existiert: $SERVICE_USER"
fi

# --- 3. Service stoppen falls läuft
if systemctl is-active --quiet "${SERVICE_NAME}.service" 2>/dev/null; then
    log "Stoppe laufenden Service…"
    systemctl stop "${SERVICE_NAME}.service"
fi
# Alten "mwiki.service" (ohne Bindestrich) auch deaktivieren falls aus früherem Setup
if systemctl list-unit-files | grep -q "^mwiki.service" && [ "$SERVICE_NAME" != "mwiki" ]; then
    warn "Alter 'mwiki.service' gefunden – wird gestoppt & disabled"
    systemctl stop mwiki.service 2>/dev/null || true
    systemctl disable mwiki.service 2>/dev/null || true
fi

# --- 4. Dateien kopieren (Daten erhalten)
log "Kopiere Anwendungsdateien nach $INSTALL_DIR…"
mkdir -p "$INSTALL_DIR"

PRESERVE_DATEN=false
PRESERVE_UPLOADS=false
PRESERVE_DB=false
[ -f "$INSTALL_DIR/daten.json" ] && PRESERVE_DATEN=true
[ -d "$INSTALL_DIR/uploads" ] && \
    [ -n "$(find "$INSTALL_DIR/uploads" -type f ! -name '.gitkeep' -print -quit 2>/dev/null)" ] && \
    PRESERVE_UPLOADS=true
[ -f "$INSTALL_DIR/wiki.db" ] && PRESERVE_DB=true

EXCLUDES=(
    --exclude='venv/'
    --exclude='__pycache__'
    --exclude='*.pyc'
    --exclude='install.sh'
    --exclude='wiki.db'
    --exclude='wiki.db-wal'
    --exclude='wiki.db-shm'
    --exclude='.git/'
)
$PRESERVE_DATEN   && EXCLUDES+=(--exclude='daten.json')
$PRESERVE_UPLOADS && EXCLUDES+=(--exclude='uploads/')

if command -v rsync &>/dev/null; then
    rsync -a "${EXCLUDES[@]}" "$SRC_DIR/" "$INSTALL_DIR/"
else
    # Fallback ohne rsync
    warn "rsync fehlt – benutze cp (langsamer, weniger granular)"
    BACKUP_TMP="$(mktemp -d)"
    $PRESERVE_DATEN   && cp -a "$INSTALL_DIR/daten.json" "$BACKUP_TMP/"
    $PRESERVE_UPLOADS && cp -a "$INSTALL_DIR/uploads"    "$BACKUP_TMP/"
    $PRESERVE_DB      && cp -a "$INSTALL_DIR/wiki.db"*   "$BACKUP_TMP/" 2>/dev/null || true
    # nur Code-Dateien aus dem Install-Dir wegwerfen
    rm -rf "$INSTALL_DIR/main.py" "$INSTALL_DIR/static" "$INSTALL_DIR/templates" \
           "$INSTALL_DIR/requirements.txt" "$INSTALL_DIR/start.sh" \
           "$INSTALL_DIR/README.md" "$INSTALL_DIR/__pycache__" \
           "$INSTALL_DIR/mwiki.service" "$INSTALL_DIR/.gitignore"
    cp -a "$SRC_DIR/." "$INSTALL_DIR/"
    rm -rf "$INSTALL_DIR/venv" "$INSTALL_DIR/__pycache__" "$INSTALL_DIR/install.sh"
    $PRESERVE_DATEN   && cp -a "$BACKUP_TMP/daten.json" "$INSTALL_DIR/"
    $PRESERVE_UPLOADS && cp -a "$BACKUP_TMP/uploads"    "$INSTALL_DIR/"
    $PRESERVE_DB      && cp -a "$BACKUP_TMP/wiki.db"*   "$INSTALL_DIR/" 2>/dev/null || true
    rm -rf "$BACKUP_TMP"
fi

mkdir -p "$INSTALL_DIR/uploads"
touch "$INSTALL_DIR/uploads/.gitkeep"

$PRESERVE_DATEN   && ok "daten.json erhalten"
$PRESERVE_UPLOADS && ok "uploads/ erhalten"
$PRESERVE_DB      && ok "wiki.db erhalten"
ok "Code-Dateien kopiert"

# --- 5. venv & pip install
log "Erstelle/aktualisiere venv und installiere Pakete…"
if [ ! -d "$INSTALL_DIR/venv" ]; then
    "$PYTHON" -m venv "$INSTALL_DIR/venv"
fi
"$INSTALL_DIR/venv/bin/pip" install --quiet --upgrade pip wheel
"$INSTALL_DIR/venv/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"
ok "Python-Pakete installiert"

# --- 6. Permissions
log "Setze Permissions…"
chown -R "$SERVICE_USER:$SERVICE_GROUP" "$INSTALL_DIR"
chmod 750 "$INSTALL_DIR"
[ -f "$INSTALL_DIR/daten.json" ] && chmod 640 "$INSTALL_DIR/daten.json"
[ -f "$INSTALL_DIR/wiki.db" ]   && chmod 640 "$INSTALL_DIR/wiki.db"
ok "Permissions: 750 dir, 640 daten.json+wiki.db, owner=$SERVICE_USER"

# --- 7. systemd unit schreiben
log "Schreibe systemd-Unit: $UNIT_FILE"
cat > "$UNIT_FILE" << EOF
[Unit]
Description=M-WIKI (Moritzsoft internes Wiki)
Documentation=https://343.im/MWIKI
After=network.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_GROUP
WorkingDirectory=$INSTALL_DIR
Environment="PYTHONUNBUFFERED=1"
Environment="HOST=$HOST"
Environment="PORT=$PORT"
ExecStart=$INSTALL_DIR/venv/bin/uvicorn main:app \\
    --host \${HOST} \\
    --port \${PORT} \\
    --proxy-headers \\
    --forwarded-allow-ips=*
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal
SyslogIdentifier=$SERVICE_NAME

# --- Security hardening --------------------------------------------------
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
PrivateDevices=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectKernelLogs=true
ProtectControlGroups=true
ProtectHostname=true
ProtectClock=true
RestrictNamespaces=true
RestrictRealtime=true
RestrictSUIDSGID=true
LockPersonality=true
MemoryDenyWriteExecute=true
SystemCallArchitectures=native
SystemCallFilter=@system-service
SystemCallFilter=~@privileged @resources

ReadWritePaths=$INSTALL_DIR

[Install]
WantedBy=multi-user.target
EOF
ok "Unit-Datei geschrieben"

# --- 8. systemd reload, enable, start
log "Lade systemd neu und starte Service…"
systemctl daemon-reload
systemctl enable "${SERVICE_NAME}.service" >/dev/null 2>&1
systemctl restart "${SERVICE_NAME}.service"

# --- 9. Status check
sleep 2
if systemctl is-active --quiet "${SERVICE_NAME}.service"; then
    ok "Service läuft: ${SERVICE_NAME}.service"
else
    err "Service startet nicht!"
    echo
    journalctl -u "${SERVICE_NAME}.service" -n 40 --no-pager
    exit 1
fi

# --- 10. Healthcheck
log "Healthcheck…"
sleep 1
HEALTHY=false
if command -v curl &>/dev/null; then
    if curl -sf --max-time 5 "http://127.0.0.1:$PORT/healthz" >/dev/null; then
        HEALTHY=true
    fi
elif command -v wget &>/dev/null; then
    if wget -q --timeout=5 -O /dev/null "http://127.0.0.1:$PORT/healthz"; then
        HEALTHY=true
    fi
fi
if $HEALTHY; then
    ok "HTTP antwortet auf Port $PORT"
else
    warn "HTTP-Healthcheck nicht möglich oder fehlgeschlagen"
fi

# --- 11. Zusammenfassung
LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo
echo -e "${GRN}${BLD}✓ M-WIKI Installation abgeschlossen.${RST}"
echo
echo "  Status:        systemctl status ${SERVICE_NAME}"
echo "  Logs (live):   journalctl -u ${SERVICE_NAME} -f"
echo "  Restart:       systemctl restart ${SERVICE_NAME}"
echo "  Stop:          systemctl stop ${SERVICE_NAME}"
echo "  Deinstall:     sudo $0 --uninstall"
echo
echo "  Anwendung:     http://${LAN_IP:-localhost}:$PORT"
echo "  Mobile App:    http://${LAN_IP:-localhost}:$PORT/app/"
echo "  Default-Login: moritz / 123"
echo
echo "  Konfig:        $INSTALL_DIR/daten.json"
echo "                 (Passwort/Titel ändern und 'systemctl restart ${SERVICE_NAME}')"
echo
