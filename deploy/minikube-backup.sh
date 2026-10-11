#!/usr/bin/env bash
# Copy the pod's database out of minikube. Run from the repository.
#   deploy/minikube-backup.sh                 -> data/backups/jobs-<UTC time>.db
#   deploy/minikube-backup.sh --update-local  ... and replace data/jobs.db with it, so the local
#                                             CLI and DB Browser see the pod's data (the old
#                                             local file is kept as data/backups/local-<time>.db)
# The snapshot is taken inside the pod with SQLite's backup API: consistent even while the
# app crawls or labels. Stop any local `jobseeker serve` before --update-local.
set -euo pipefail
cd "$(dirname "$0")/.."

ns=jobseeker
update_local=${1:-}
python=${PYTHON:-.venv/bin/python}
stamp=$(date -u +%Y%m%dT%H%M%SZ)
backup=data/backups/jobs-$stamp.db
mkdir -p data/backups

pod=$(kubectl -n "$ns" get pod -l app=jobseeker -o jsonpath='{.items[0].metadata.name}')
kubectl -n "$ns" exec "$pod" -- python -c "
import sqlite3
src = sqlite3.connect('/app/data/jobs.db', timeout=30)
dst = sqlite3.connect('/tmp/jobs-snapshot.db')
src.backup(dst)
dst.close()"
kubectl -n "$ns" cp "$pod:/tmp/jobs-snapshot.db" "$backup" 2>&1 | { grep -v "Removing leading" || true; }
kubectl -n "$ns" exec "$pod" -- rm -f /tmp/jobs-snapshot.db

"$python" - "$backup" <<'EOF'
import sqlite3, sys
db = sqlite3.connect(sys.argv[1])
ok = db.execute("PRAGMA integrity_check").fetchone()[0]
jobs = db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
runs = db.execute("SELECT COUNT(*) FROM label_runs").fetchone()[0]
print(f"{sys.argv[1]}: integrity {ok}, {jobs} jobs, {runs} label runs")
sys.exit(ok != "ok")
EOF

if [[ $update_local == --update-local ]]; then
  if [[ -f data/jobs.db ]]; then
    cp data/jobs.db "data/backups/local-$stamp.db"
    echo "kept the old local database as data/backups/local-$stamp.db"
  fi
  rm -f data/jobs.db-wal data/jobs.db-shm
  cp "$backup" data/jobs.db
  echo "data/jobs.db now holds the pod's data"
fi
