# Kubernetes deployment

This directory contains the CronJob manifests used in production to
parallelize mining across a single-node k3s cluster. The manifests are
deliberately minimal: they reference a secret named `geonlp-env` for
database credentials, but the secret itself is not included (you create
your own).

## Deployment topology (Phase 1 pool segregation)

```
                            +---------------------------+
                            | geonlp-classifier         |
                            |  every 30 min             |
                            |  classifies pending rows  |
                            +---------------------------+
                                         |
                                         | writes term_class
                                         v
              +--------------------------+-------------------------+
              |                          |                         |
              v                          v                         v
+-------------+-------+    +-------------+--------+    +-----------+-----+
| pool=small-medium   |    | pool=large           |    | pool=oversized  |
|  25 pods x 1 GiB    |    |  5 pods x 4 GiB      |    |  auto-failed    |
|  --class small,med  |    |  --class large       |    |  by classifier  |
|  every 10 min       |    |  every 10 min        |    |                 |
+---------------------+    +----------------------+    +-----------------+

                            +---------------------------+
                            | geonlp-janitor            |
                            |  every hour               |
                            |  resets zombie rows       |
                            +---------------------------+
```

## Files

| File | Purpose |
|---|---|
| `geonlp-cronjob.yaml` | Small-medium pool worker (25 pods, 1 GiB each) |
| `geonlp-cronjob-large.yaml` | Large pool worker (5 pods, 4 GiB each) |
| `geonlp-classifier-cronjob.yaml` | Classifier (assigns term_class to pending rows) |
| `geonlp-janitor-cronjob.yaml` | Zombie reclamation (every hour) |
| `geonlp-stats-cronjob.yaml` | Daily full statistics refresh (defensive sweep) |
| `apply-migration-job.yaml` | One-shot migration runner |

## Prerequisites

1. A Kubernetes cluster (tested on k3s v1.30, single-node).
2. The `geonlp-portal:latest` container image, built from this repository's
   `Dockerfile`, available in the cluster's image store.
3. A PostgreSQL database accessible from the cluster, with the schema
   from `../db/schema.sql` applied.
4. A Kubernetes Secret named `geonlp-env` containing the four keys
   referenced by every manifest: `DB_HOST`, `DB_USER`, `DB_PASSWORD`,
   `DB_NAME`.

## Creating the secret

Replace the placeholder values:

```bash
kubectl create secret generic geonlp-env \
    --from-literal=DB_HOST='your.postgres.host' \
    --from-literal=DB_USER='your_db_user' \
    --from-literal=DB_PASSWORD='your_db_password' \
    --from-literal=DB_NAME='geonlp_db'
```

## Building and importing the image (k3s)

```bash
docker build -t geonlp-portal:latest .
docker save geonlp-portal:latest | sudo /usr/local/bin/k3s ctr -n k8s.io images import -
```

## Deploying

```bash
# Apply all CronJobs at once
kubectl apply -f k8s/

# Or apply individually as needed
kubectl apply -f k8s/geonlp-cronjob.yaml
kubectl apply -f k8s/geonlp-cronjob-large.yaml
kubectl apply -f k8s/geonlp-classifier-cronjob.yaml
kubectl apply -f k8s/geonlp-janitor-cronjob.yaml
```

## Resource budgets

Tested on a single-node NUC with 15.5 GiB RAM and 8 cores. Approximate
working-set memory at full saturation:

| Pool | Pods | Memory limit each | Working set |
|---|---|---|---|
| small-medium | 25 | 1 GiB | ~10 GiB |
| large | 5 | 4 GiB | ~7.5 GiB |
| classifier | 1 | 256 MiB | ~64 MiB |
| janitor | 1 | 256 MiB | ~32 MiB |

Combined working set ~17.5 GiB, which fits because the two pools rarely
saturate together. If `kubectl top node` shows sustained memory above 85%,
reduce `MAX_CONCURRENT_SMALL_MEDIUM` in `scripts/process_pending_terms.py`.

## Operational health checks

```bash
# How many miners are actually running?
kubectl get pods -l app=geonlp,component=term-miner --field-selector=status.phase=Running

# Zombie detection: DB-says-running minus K8s-says-running = zombie count
DB_RUNNING=$(psql -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" -t -A -c "SELECT COUNT(*) FROM term_requests WHERE status='running'")
K8S_RUNNING=$(kubectl get pods -l app=geonlp,component=term-miner --field-selector=status.phase=Running -o name | wc -l)
echo "DB: $DB_RUNNING | K8s: $K8S_RUNNING | Gap: $((DB_RUNNING - K8S_RUNNING))"

# Class distribution of the queue
psql -h "$DB_HOST" -U "$DB_USER" -d "$DB_NAME" -c "
SELECT term_class, status, COUNT(*)
FROM term_requests
GROUP BY 1, 2 ORDER BY 1, 2;
"
```
