#!/usr/bin/env bash
# Copy export/jobs/post for a slug into output/archive (safe backup; does not rename source).
#
#   bash scripts/linux/backup_case_slug.sh SLUG [TAG]
#   bash scripts/linux/backup_case_slug.sh q05_c10m_s06r3_el_s45 pre_restart_20260702
set -euo pipefail

SLUG="${1:?usage: backup_case_slug.sh SLUG [TAG]}"
TAG="${2:-backup_$(date +%Y%m%d_%H%M%S)}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

DEST="output/archive/${SLUG}_${TAG}"
mkdir -p "$DEST"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

copy_tree() {
  local base="$1"
  local src="$ROOT/output/$base/$SLUG"
  if [[ ! -d "$src" ]]; then
    log "[WARN] missing output/$base/$SLUG"
    return 1
  fi
  log "copy output/$base/$SLUG -> $DEST/$base/"
  mkdir -p "$DEST/$base"
  rsync -a --info=progress2 "$src/" "$DEST/$base/$SLUG/"
}

log "=== backup $SLUG tag=$TAG -> $DEST ==="
moved=0
for base in export jobs post; do
  if copy_tree "$base"; then
    moved=$((moved + 1))
  fi
done

if [[ "$moved" -eq 0 ]]; then
  echo "ERROR: nothing copied for $SLUG" >&2
  exit 1
fi

python3 - <<'PY' "$DEST" "$SLUG" "$TAG"
import json, os, sys, time
dest, slug, tag = sys.argv[1:4]
manifest = {
    "slug": slug,
    "tag": tag,
    "created_unix": time.time(),
    "dest": dest,
    "trees": [],
}
for base in ("export", "jobs", "post"):
    p = os.path.join(dest, base, slug)
    if not os.path.isdir(p):
        continue
    nbytes = 0
    nfiles = 0
    for root, _, files in os.walk(p):
        for fn in files:
            nbytes += os.path.getsize(os.path.join(root, fn))
            nfiles += 1
    manifest["trees"].append({"base": base, "files": nfiles, "bytes": nbytes})
out = os.path.join(dest, "manifest.json")
with open(out, "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=2, ensure_ascii=False)
print("Wrote", out)
PY

log "backup done: $DEST"
du -sh "$DEST"
