#!/usr/bin/env bash
# Versleutelde back-up van de declaratietool naar Google Drive (zie docs/backup.md).
#
#   sudo deploy/backup.sh setup             eenmalig: sleutel maken, Google Drive koppelen, nachtelijke back-up aanzetten
#   sudo deploy/backup.sh                   nu een back-up maken en uploaden (dit doet de timer elke nacht)
#   sudo deploy/backup.sh list              back-ups op Google Drive tonen
#   sudo deploy/backup.sh restore BESTAND   een back-up terugzetten (vervangt alle huidige gegevens)
#
# Een back-up bevat de database, alle bijlagen en de .env. Hij wordt op de server met
# gpg (AES-256) versleuteld voordat hij naar Google Drive gaat; Google ziet alleen
# onleesbare bestanden. Zonder de sleutel (/etc/declaratietool/backup.key) is een
# back-up niet terug te zetten: bewaar die sleutel dus ook ergens anders.

set -Eeuo pipefail

INSTALL_DIR="${INSTALL_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
CONF_DIR=/etc/declaratietool
KEY_FILE=$CONF_DIR/backup.key
RCLONE_CONF=$CONF_DIR/rclone.conf
REMOTE="gdrive:declaratietool-backup"
LOCAL_DIR=/var/backups/declaratietool
KEEP_LOCAL_DAYS="${KEEP_LOCAL_DAYS:-7}"
KEEP_REMOTE_DAYS="${KEEP_REMOTE_DAYS:-90}"
STATUS_DIR=$INSTALL_DIR/update/status
STATUS_FILE=$STATUS_DIR/backup.json
# Laat rclone authorize de toegang beperken tot bestanden die rclone zelf maakt (scope drive.file).
AUTHORIZE_CONFIG="eyJzY29wZSI6ImRyaXZlLmZpbGUifQ"

say() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
fail() { echo "Fout: $*" >&2; exit 1; }
rc() { rclone --config "$RCLONE_CONF" "$@"; }

write_status() {  # write_status STATE MESSAGE [BESTAND] [BYTES]
  mkdir -p "$STATUS_DIR"
  local tmp
  tmp=$(mktemp "$STATUS_DIR/.backup.XXXXXX")
  printf '{"state": "%s", "message": "%s", "at": "%s", "file": "%s", "size": %s}\n' \
    "$1" "$2" "$(date -Iseconds)" "${3:-}" "${4:-0}" >"$tmp"
  chmod 644 "$tmp"
  mv "$tmp" "$STATUS_FILE"
}

run_backup() {
  [[ -f $KEY_FILE && -f $RCLONE_CONF ]] || { write_status failed not_configured; fail "nog niet ingesteld. Draai eerst:  sudo $0 setup"; }
  mkdir -p "$LOCAL_DIR"
  chmod 700 "$LOCAL_DIR"
  local name out size
  work=$(mktemp -d)
  # Bij elke fout: status 'failed' voor het portaal en de tijdelijke map opruimen.
  trap 'code=$?; rm -rf "${work:-}"; if [[ $code -ne 0 ]]; then write_status failed error; echo "Back-up mislukt; zie  journalctl -u declaratietool-backup" >&2; fi' EXIT
  name="declaratietool-$(date +%Y-%m-%d_%H%M).tar.gz.gpg"
  out=$LOCAL_DIR/$name

  cd "$INSTALL_DIR"
  echo "Database exporteren"
  docker compose exec -T db pg_dump -U declaratie -d declaratie --clean --if-exists --no-owner >"$work/database.sql"
  grep -q 'PostgreSQL database dump complete' "$work/database.sql" || fail "database-export is onvolledig"
  echo "Bijlagen inpakken"
  docker compose exec -T app tar czf - -C /data/uploads . >"$work/uploads.tar.gz"
  cp .env "$work/env"
  git rev-parse HEAD >"$work/versie.txt" 2>/dev/null || true

  echo "Versleutelen"
  tar czf - -C "$work" . | gpg --batch --yes --quiet --pinentry-mode loopback \
    --passphrase-file "$KEY_FILE" --symmetric --cipher-algo AES256 -o "$out"
  chmod 600 "$out"
  size=$(stat -c %s "$out")

  echo "Uploaden naar Google Drive"
  rc copy "$out" "$REMOTE"
  rc delete --min-age "${KEEP_REMOTE_DAYS}d" --include 'declaratietool-*.gpg' "$REMOTE"
  find "$LOCAL_DIR" -name 'declaratietool-*.gpg' -mtime +"$KEEP_LOCAL_DAYS" -delete

  write_status ok "" "$name" "$size"
  echo "Klaar: $name ($((size / 1024)) kB)"
}

read_token() {
  # rclone authorize geeft de sleutel als JSON, in sommige versies base64-gecodeerd.
  local line decoded token=""
  while [[ -z $token ]]; do
    read -r -p "Plak hier de regel die met { begint (of de lange code): " line </dev/tty
    line=$(printf '%s' "$line" | tr -d '[:space:]')
    if [[ $line == \{* ]]; then
      token=$line
    elif decoded=$(printf '%s' "$line" | base64 -d 2>/dev/null) && [[ $decoded == \{* ]]; then
      token=$decoded
    else
      echo "Dat lijkt geen sleutel van rclone te zijn; probeer opnieuw." >&2
    fi
  done
  printf '%s' "$token"
}

setup() {
  say "Programma's installeren (rclone, gpg)"
  export DEBIAN_FRONTEND=noninteractive
  apt-get install -y -q rclone gnupg openssl >/dev/null

  mkdir -p "$CONF_DIR"
  chmod 700 "$CONF_DIR"

  if [[ ! -f $KEY_FILE ]]; then
    say "Sleutel voor de versleuteling maken"
    (umask 077; openssl rand -base64 33 | tr -d '\n' >"$KEY_FILE")
    cat <<EOF

    Sleutel:  $(cat "$KEY_FILE")

    BEWAAR DEZE SLEUTEL NU, bijvoorbeeld in een wachtwoordmanager of op papier in de kluis.
    Zonder de sleutel is een back-up niet terug te zetten, ook niet als de server weg is.

EOF
    read -r -p "Druk op Enter als je de sleutel hebt bewaard... " _ </dev/tty
  else
    say "Bestaande sleutel in $KEY_FILE blijft in gebruik"
  fi

  if ! rc listremotes 2>/dev/null | grep -qx 'gdrive:'; then
    say "Google Drive koppelen"
    cat <<EOF
Doe dit op je eigen computer (met een webbrowser):

  1. Installeer rclone: https://rclone.org/downloads/ (Windows: pak de zip uit;
     Mac: brew install rclone).
  2. Open een terminal (Windows: PowerShell in de map met rclone.exe) en typ:

       rclone authorize "drive" "$AUTHORIZE_CONFIG"

     (Windows: .\\rclone.exe authorize "drive" "$AUTHORIZE_CONFIG")
  3. Log in de browser in met het Google-account van de boekhouder en geef toestemming.
     rclone krijgt alleen toegang tot de bestanden die het zelf maakt, niet tot de rest
     van de Drive.
  4. Kopieer wat rclone daarna toont tussen "Paste the following" en "End paste".

EOF
    token=$(read_token)
    (umask 077; rc config create gdrive drive scope=drive.file config_refresh_token=false \
      token="$token" --non-interactive >/dev/null)
  else
    say "Google Drive is al gekoppeld"
  fi
  chmod 600 "$RCLONE_CONF"
  rc mkdir "$REMOTE"
  rc lsd gdrive: >/dev/null || fail "Google Drive reageert niet; controleer de koppeling"

  say "Nachtelijke back-up aanzetten"
  for unit in declaratietool-backup.service declaratietool-backup.timer; do
    sed "s|/opt/declaratietool|$INSTALL_DIR|g" "$INSTALL_DIR/deploy/systemd/$unit" >"/etc/systemd/system/$unit"
  done
  systemctl daemon-reload
  systemctl enable --now declaratietool-backup.timer >/dev/null

  say "Eerste back-up maken"
  run_backup
  echo
  echo "Elke nacht wordt nu automatisch een back-up gemaakt. Op Google Drive staan ze in de map"
  echo "declaratietool-backup. Bekijk ze met:  sudo $0 list"
}

list() {
  echo "Op Google Drive ($REMOTE):"
  rc lsl "$REMOTE" | sort -k2,3
  echo
  echo "Op deze server ($LOCAL_DIR):"
  ls -lh "$LOCAL_DIR" 2>/dev/null | tail -n +2 || true
}

set_env() {  # set_env KEY waarde  (in .env)
  local value=$2
  value=${value//\\/\\\\}; value=${value//&/\\&}; value=${value//|/\\|}
  sed -i "s|^$1=.*|$1=$value|" "$INSTALL_DIR/.env"
}

restore() {
  local file=${1:-}
  [[ -n $file ]] || fail "geef het bestand op, bijvoorbeeld:  sudo $0 restore declaratietool-2026-10-12_0330.tar.gz.gpg"
  [[ -f $KEY_FILE ]] || fail "sleutel ontbreekt. Zet de bewaarde sleutel in $KEY_FILE (chmod 600)."
  [[ -f $INSTALL_DIR/.env ]] || fail "installeer eerst de tool met deploy/install-vps.sh"

  if [[ ! -f $file ]]; then
    [[ -f $LOCAL_DIR/$file ]] && file=$LOCAL_DIR/$file
  fi
  if [[ ! -f $file ]]; then
    say "Ophalen van Google Drive"
    mkdir -p "$LOCAL_DIR"
    rc copy "$REMOTE/$(basename "$file")" "$LOCAL_DIR"
    file=$LOCAL_DIR/$(basename "$file")
    chmod 600 "$file"
  fi

  local old_key
  work=$(mktemp -d)
  trap 'rm -rf "${work:-}"' EXIT
  gpg --batch --quiet --pinentry-mode loopback --passphrase-file "$KEY_FILE" -d "$file" | tar xzf - -C "$work"
  [[ -f $work/database.sql && -f $work/uploads.tar.gz ]] || fail "dit lijkt geen back-up van de declaratietool"

  echo
  echo "Dit vervangt ALLE huidige declaraties, gebruikers en bijlagen door die uit"
  echo "$(basename "$file")."
  read -r -p "Typ JA om door te gaan: " answer </dev/tty
  [[ $answer == JA ]] || fail "afgebroken"

  cd "$INSTALL_DIR"
  say "Tool stilzetten"
  docker compose stop app worker
  docker compose up -d db
  for _ in $(seq 1 30); do docker compose exec -T db pg_isready -U declaratie -q && break; sleep 2; done

  say "Database terugzetten"
  docker compose exec -T db psql -q -U declaratie -d declaratie -v ON_ERROR_STOP=1 <"$work/database.sql" >/dev/null

  say "Bijlagen terugzetten"
  docker compose run --rm --no-deps -T --entrypoint sh app \
    -c 'find /data/uploads -mindepth 1 -delete && tar xzf - -C /data/uploads' <"$work/uploads.tar.gz"

  # Met de SECRET_KEY uit de back-up blijven opgeslagen mailwachtwoorden leesbaar.
  # Het databasewachtwoord van deze server blijft staan; het hoort bij deze database.
  old_key=$(grep '^SECRET_KEY=' "$work/env" | cut -d= -f2- || true)
  if [[ -n $old_key ]] && ! grep -qxF "SECRET_KEY=$old_key" .env; then
    set_env SECRET_KEY "$old_key"
    echo "SECRET_KEY overgenomen uit de back-up."
  fi
  cp "$work/env" "$CONF_DIR/env-uit-backup"
  chmod 600 "$CONF_DIR/env-uit-backup"

  say "Tool weer starten"
  docker compose up -d
  echo "Klaar. De volledige .env uit de back-up staat ter vergelijking in $CONF_DIR/env-uit-backup."
}

[[ $EUID -eq 0 ]] || fail "start dit script met sudo"

case ${1:-backup} in
  backup) run_backup ;;
  setup) setup ;;
  list) list ;;
  restore) restore "${2:-}" ;;
  *) fail "onbekende opdracht '$1'. Gebruik: setup, backup, list of restore BESTAND" ;;
esac
