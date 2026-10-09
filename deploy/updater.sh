#!/usr/bin/env bash
# Werkt de declaratietool bij op verzoek van de knop "Bijwerken" in het portaal.
#
# Draait op de server zelf (als root, via systemd), niet in een container. De app kan
# alleen een verzoek neerleggen in update/requests/; dit script voert het uit en schrijft
# de uitkomst naar update/status/, dat de app alleen kan lezen. Zo hoeft de app geen
# toegang tot Docker te hebben.
#
# Verzoeken (inhoud van update/requests/request):
#   check   kijk op GitHub of er een nieuwe versie is (ook elk uur via de timer)
#   update  haal de nieuwste versie op en herstart de tool
#
# Handmatig draaien kan ook:  sudo /opt/declaratietool/deploy/updater.sh [check|update]

set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
BRANCH="${BRANCH:-main}"
REQUEST_DIR="$INSTALL_DIR/update/requests"
STATUS_DIR="$INSTALL_DIR/update/status"
STATUS_FILE="$STATUS_DIR/status.json"
LOG_FILE="$STATUS_DIR/update.log"
APP_UID=1000  # gebruiker 'declaratie' in de container

# Alles staat in functies en wordt pas onderaan gestart: bash leest het hele bestand
# dan vooraf in, zodat 'git pull' dit script veilig kan vervangen terwijl het draait.

prepare_dirs() {
  mkdir -p "$REQUEST_DIR" "$STATUS_DIR"
  chown "$APP_UID:$APP_UID" "$REQUEST_DIR"
  chmod 700 "$REQUEST_DIR"
  chown root:root "$STATUS_DIR"
  chmod 755 "$STATUS_DIR"
}

take_request() {
  # Lees en verwijder het verzoek van de app. De inhoud is niet te vertrouwen: alleen
  # een bekend woord telt, en een symlink wordt niet gevolgd.
  local file="$REQUEST_DIR/request" word=""
  if [[ -f $file && ! -L $file ]]; then
    word=$(head -c 16 "$file" | tr -cd 'a-z')
  fi
  rm -f "$file"
  case $word in
    update) echo update ;;
    *) echo check ;;
  esac
}

commit_info() {  # commit_info REF -> "sha<TAB>datum<TAB>onderwerp"
  git -C "$INSTALL_DIR" log -1 --format='%H%x09%cI%x09%s' "$1" 2>/dev/null || true
}

write_status() {  # write_status STATE MESSAGE
  local state=$1 message=$2 tmp
  tmp=$(mktemp "$STATUS_DIR/.status.XXXXXX")
  STATE=$state MESSAGE=$message \
  CURRENT=$(commit_info HEAD) \
  LATEST=$(commit_info "origin/$BRANCH") \
  NEW_COMMITS=$(git -C "$INSTALL_DIR" log --format='%h%x09%s' "HEAD..origin/$BRANCH" 2>/dev/null | head -n 30 || true) \
  STARTED_AT=${STARTED_AT:-} \
  python3 - >"$tmp" <<'PY'
import json, os
from datetime import datetime, timezone

def commit(line):
    parts = line.split("\t", 2)
    if len(parts) != 3:
        return None
    return {"sha": parts[0], "date": parts[1], "subject": parts[2]}

new = [dict(zip(("sha", "subject"), l.split("\t", 1))) for l in os.environ["NEW_COMMITS"].splitlines() if "\t" in l]
print(json.dumps({
    "state": os.environ["STATE"],
    "message": os.environ["MESSAGE"],
    "current": commit(os.environ["CURRENT"]),
    "latest": commit(os.environ["LATEST"]),
    "new_commits": new,
    "started_at": os.environ["STARTED_AT"] or None,
    "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
}, indent=2))
PY
  chmod 644 "$tmp"
  mv -f "$tmp" "$STATUS_FILE"
}

compose() {
  # Met IMAGE in .env: het kant-en-klare image van GitHub; anders zelf bouwen.
  local image
  image=$(grep -E '^IMAGE=' "$INSTALL_DIR/.env" 2>/dev/null | cut -d= -f2- || true)
  if [[ -n $image ]]; then
    docker compose -f docker-compose.yml -f docker-compose.ghcr.yml "$@"
  else
    docker compose "$@"
  fi
}

do_check() {
  if git -C "$INSTALL_DIR" fetch --quiet origin "$BRANCH"; then
    write_status idle ""
  else
    write_status idle "fetch_failed"
  fi
}

do_update() {
  {
    echo "== Bijwerken gestart $(date '+%Y-%m-%d %H:%M:%S')"
    cd "$INSTALL_DIR"
    git fetch origin "$BRANCH"
    git merge --ff-only "origin/$BRANCH"
    export GIT_COMMIT
    GIT_COMMIT=$(git rev-parse HEAD)
    if grep -qE '^IMAGE=.+' .env 2>/dev/null; then
      compose pull
    else
      # Bouw met de nieuwste Python-basis; haal ook nieuwe versies van PostgreSQL en Caddy op.
      compose build --pull app
      compose pull --ignore-pull-failures db caddy
    fi
    compose up -d
    docker image prune -f
    echo "== Klaar $(date '+%Y-%m-%d %H:%M:%S')"
  } >"$LOG_FILE" 2>&1
}

main() {
  local action=${1:-}
  [[ $EUID -eq 0 ]] || { echo "Start dit script als root (sudo)." >&2; exit 1; }
  prepare_dirs
  exec 9>"$STATUS_DIR/.lock"
  flock -n 9 || { echo "Er loopt al een update." >&2; exit 0; }
  [[ -n $action ]] || action=$(take_request)
  case $action in
    check) do_check ;;
    update)
      STARTED_AT=$(date -u +%Y-%m-%dT%H:%M:%S+00:00)
      write_status running ""
      # In een subshell zodat 'set -e' werkt: elke mislukte stap breekt de update af.
      local rc=0
      set +e
      ( set -e; do_update )
      rc=$?
      set -e
      if [[ $rc -eq 0 ]]; then
        write_status ok ""
      else
        write_status failed "update_failed"
        exit 1
      fi
      ;;
    *) echo "Gebruik: $0 [check|update]" >&2; exit 2 ;;
  esac
}

main "$@"
exit
