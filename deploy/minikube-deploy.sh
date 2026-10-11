#!/usr/bin/env bash
# Build the image, load it into minikube and (re)deploy jobseeker. Run from the repository.
#   deploy/minikube-deploy.sh          deploy; on first deploy, seed the volume from data/
#   deploy/minikube-deploy.sh --seed   also replace the pod's database with a copy of data/jobs.db
# Seeding copies data/jobs.db (a consistent snapshot, safe while the local app runs) and the
# swisstopo locality register into the volume.
set -euo pipefail
cd "$(dirname "$0")/.."

ns=jobseeker
image=jobseeker:dev
force_seed=${1:-}
python=${PYTHON:-.venv/bin/python}

docker build -t "$image" .
minikube image load --overwrite=true "$image"
kubectl apply -f deploy/k8s/jobseeker.yaml

volume_has_db() {
  kubectl -n "$ns" exec seed -- test -f /app/data/jobs.db 2>/dev/null
}

seed() {
  echo "Checking the data volume"
  kubectl -n "$ns" scale deployment/jobseeker --replicas=0
  kubectl -n "$ns" wait --for=delete pod -l app=jobseeker --timeout=120s || true
  # a throwaway pod with the volume; our own image, since the node can't pull others
  kubectl -n "$ns" run seed --image="$image" --image-pull-policy=Never --restart=Never \
    --overrides='{"spec":{"securityContext":{"fsGroup":1000},"containers":[{"name":"seed","image":"'"$image"'","imagePullPolicy":"Never","command":["sleep","600"],"volumeMounts":[{"name":"data","mountPath":"/app/data"}]}],"volumes":[{"name":"data","persistentVolumeClaim":{"claimName":"jobseeker-data"}}]}}'
  kubectl -n "$ns" wait --for=condition=Ready pod/seed --timeout=120s
  if [[ $force_seed == --seed ]] || ! volume_has_db; then
    snapshot=$(mktemp -d)/jobs.db
    "$python" -c "import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close()" \
      data/jobs.db "$snapshot"
    kubectl -n "$ns" exec seed -- rm -f /app/data/jobs.db-wal /app/data/jobs.db-shm
    kubectl -n "$ns" cp "$snapshot" seed:/app/data/jobs.db
    kubectl -n "$ns" cp data/AMTOVZ_CSV_LV95.csv seed:/app/data/AMTOVZ_CSV_LV95.csv
    echo "Copied $(du -h "$snapshot" | cut -f1) database and the locality register"
  else
    echo "The volume already has a database; kept it (--seed replaces it)"
  fi
  kubectl -n "$ns" delete pod seed --wait=true
  kubectl -n "$ns" scale deployment/jobseeker --replicas=1
}

seed
kubectl -n "$ns" rollout restart deployment/jobseeker   # pick up the image just loaded
kubectl -n "$ns" rollout status deployment/jobseeker --timeout=180s
echo
echo "Reachable on sandbox port 8090 once deploy/minikube-network.sh has run;"
echo "on the host:  sbx ports $(hostname) --publish 8090:8090   ->  http://localhost:8090"
