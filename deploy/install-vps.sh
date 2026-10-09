#!/usr/bin/env bash
# Installeert de declaratietool op een verse Ubuntu- of Debian-VPS (bijvoorbeeld bij OVH).
#
# Gebruik (als de standaardgebruiker, met sudo):
#   curl -fsSL https://raw.githubusercontent.com/jip67/declaratietool/main/deploy/install-vps.sh -o install-vps.sh
#   sudo bash install-vps.sh
#
# Het script:
#   - werkt het systeem bij en zet automatische beveiligingsupdates aan
#   - zet een firewall aan (alleen SSH, http en https open)
#   - installeert fail2ban, dat IP-adressen blokkeert die SSH-wachtwoorden proberen te raden
#   - installeert Docker
#   - haalt de code op naar /opt/declaratietool
#   - maakt een .env met veilige willekeurige wachtwoorden en vraagt je domein en mailgegevens
#   - start alles en maakt je eerste account aan
#
# Je kunt het script veilig opnieuw draaien; een bestaande .env wordt niet overschreven.

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/jip67/declaratietool.git}"
INSTALL_DIR="${INSTALL_DIR:-/opt/declaratietool}"

if [[ $EUID -ne 0 ]]; then
  echo "Start dit script met sudo:  sudo bash $0" >&2
  exit 1
fi

say() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }

ask() {  # ask VAR "vraag" "standaard"
  local var=$1 prompt=$2 default=${3:-} answer
  if [[ -n $default ]]; then
    read -r -p "$prompt [$default]: " answer </dev/tty
    answer=${answer:-$default}
  else
    while [[ -z ${answer:-} ]]; do read -r -p "$prompt: " answer </dev/tty; done
  fi
  printf -v "$var" '%s' "$answer"
}

ask_secret() {  # ask_secret VAR "vraag"
  local var=$1 prompt=$2 answer=""
  read -r -s -p "$prompt: " answer </dev/tty
  echo
  printf -v "$var" '%s' "$answer"
}

say "Systeem bijwerken"
export DEBIAN_FRONTEND=noninteractive
apt-get update -q
apt-get upgrade -y -q
apt-get install -y -q ca-certificates curl git ufw unattended-upgrades openssl fail2ban python3-systemd
dpkg-reconfigure -f noninteractive unattended-upgrades

say "Firewall instellen (SSH, http, https)"
ufw allow OpenSSH >/dev/null
ufw allow 80/tcp >/dev/null
ufw allow 443/tcp >/dev/null
ufw --force enable >/dev/null
ufw status | sed 's/^/    /'

say "fail2ban instellen (blokkeert wachtwoord-raders op SSH)"
cat >/etc/fail2ban/jail.d/declaratietool.local <<'JAIL'
[sshd]
enabled  = true
backend  = systemd
maxretry = 5
findtime = 10m
bantime  = 1h
JAIL
systemctl enable fail2ban >/dev/null
systemctl restart fail2ban

if ! command -v docker >/dev/null; then
  say "Docker installeren"
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker >/dev/null

# De gewone gebruiker (die sudo deed) mag ook docker-opdrachten geven.
if [[ -n ${SUDO_USER:-} && $SUDO_USER != root ]]; then
  usermod -aG docker "$SUDO_USER"
fi

say "Code ophalen naar $INSTALL_DIR"
if [[ -d $INSTALL_DIR/.git ]]; then
  git -C "$INSTALL_DIR" pull --ff-only
else
  git clone "$REPO_URL" "$INSTALL_DIR"
fi
cd "$INSTALL_DIR"

if [[ ! -f .env ]]; then
  say "Instellingen"
  echo "Het domein moet al naar het IP-adres van deze server wijzen (A-record)."
  ask DOMAIN "Domein voor de tool (zonder https://), bijv. declaraties.mijnvereniging.nl"
  ask ORG "Naam van je vereniging" "Mijn vereniging"
  echo
  echo "Mailbox waar declaraties naartoe gestuurd worden."
  echo "Bij een OVH-mailbox (MX Plan) is de server meestal ssl0.ovh.net; controleer dit in je OVH-klantpaneel."
  MAIL_DOMAIN=$DOMAIN
  [[ $DOMAIN == *.*.* ]] && MAIL_DOMAIN=${DOMAIN#*.}
  ask MAIL "E-mailadres" "declaraties@$MAIL_DOMAIN"
  ask MAIL_HOST "Mailserver (IMAP en SMTP)" "ssl0.ovh.net"
  ask_secret MAIL_PASSWORD "Wachtwoord van de mailbox (leeg = later invullen)"

  SECRET_KEY=$(openssl rand -hex 32)
  POSTGRES_PASSWORD=$(openssl rand -hex 24)

  cp .env.example .env
  set_env() {  # set_env KEY waarde
    local key=$1 value=$2
    value=${value//\\/\\\\}; value=${value//&/\\&}; value=${value//|/\\|}
    sed -i "s|^$key=.*|$key=$value|" .env
  }
  set_env DOMAIN "$DOMAIN"
  set_env BASE_URL "https://$DOMAIN"
  set_env ORGANISATION_NAME "$ORG"
  set_env SECRET_KEY "$SECRET_KEY"
  set_env POSTGRES_PASSWORD "$POSTGRES_PASSWORD"
  set_env MAIL_FROM "$MAIL"
  set_env IMAP_USER "$MAIL"
  set_env SMTP_USER "$MAIL"
  if [[ -n $MAIL_PASSWORD ]]; then
    set_env IMAP_HOST "$MAIL_HOST"
    set_env SMTP_HOST "$MAIL_HOST"
    set_env IMAP_PASSWORD "$MAIL_PASSWORD"
    set_env SMTP_PASSWORD "$MAIL_PASSWORD"
    # OVH: SMTP via SSL op poort 465
    set_env SMTP_PORT 465
    set_env SMTP_SSL true
    set_env SMTP_STARTTLS false
  else
    # Zonder wachtwoord: mail uit, links verschijnen in de log
    set_env IMAP_HOST ""
    set_env SMTP_HOST ""
  fi
  chmod 600 .env
  echo "Instellingen opgeslagen in $INSTALL_DIR/.env"
else
  say "Bestaande .env gevonden, die blijft ongewijzigd"
fi

say "Bijwerkknop in het portaal instellen"
# De app legt alleen een verzoek neer; deze systemd-units voeren het uit op de server.
for unit in declaratietool-updater.service declaratietool-updater.path declaratietool-updater.timer; do
  sed "s|/opt/declaratietool|$INSTALL_DIR|g" "deploy/systemd/$unit" >"/etc/systemd/system/$unit"
done
systemctl daemon-reload
INSTALL_DIR=$INSTALL_DIR bash deploy/updater.sh check || true
systemctl enable --now declaratietool-updater.path declaratietool-updater.timer >/dev/null

say "Starten (de eerste keer duurt dit een paar minuten)"
GIT_COMMIT=$(git rev-parse HEAD) docker compose up -d --build

echo -n "Wachten tot de tool klaar is"
for _ in $(seq 1 60); do
  if docker compose exec -T app python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" >/dev/null 2>&1; then
    echo " klaar."
    break
  fi
  echo -n "."
  sleep 3
done

if [[ -z $(docker compose exec -T db psql -U declaratie -tAc "select 1 from users limit 1" 2>/dev/null) ]]; then
  say "Je eigen account aanmaken"
  ask ADMIN_EMAIL "Jouw e-mailadres"
  ask ADMIN_NAME "Jouw naam"
  docker compose exec app python -m app.cli create-user \
    --email "$ADMIN_EMAIL" --name "$ADMIN_NAME" --roles admin,treasurer </dev/tty
fi

DOMAIN_NOW=$(grep '^DOMAIN=' .env | cut -d= -f2)
say "Klaar"
cat <<EOF
Open https://$DOMAIN_NOW en log in. Voeg onder "Gebruikers" de voorzitter en secretaris toe.

Handige opdrachten (in $INSTALL_DIR):
  docker compose ps                          status
  docker compose logs -f app worker caddy    logboek
  sudo deploy/updater.sh update              bijwerken (of via Bijwerken in het portaal)
  nano .env && docker compose up -d          instellingen wijzigen

Log één keer uit en weer in, dan kun je docker zonder sudo gebruiken.

Beveiliging: log bij voorkeur in met een SSH-sleutel in plaats van een wachtwoord.
Zie docs/beveiliging.md voor de stappen.
EOF
