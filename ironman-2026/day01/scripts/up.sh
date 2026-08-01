#!/usr/bin/env bash
# Bring up the Day1 bench cluster: k3d + the o11y stack, ready to be queried.
#
# Run from the repo root:  ./ironman-2026/day01/scripts/up.sh
set -euo pipefail

DAY_DIR="$(cd "$(dirname "$0")/.." && pwd)"
CLUSTER="aiops-day01"
IMAGE="${O11Y_STACK_IMAGE:-o11y-bench-o11y-stack:latest}"

for bin in k3d kubectl docker; do
  command -v "$bin" >/dev/null || { echo "[up] missing dependency: $bin"; exit 1; }
done

# The stack image is built from the o11y-bench repo (docker/Dockerfile). We never
# pull it — a missing image here is a setup error, not something to paper over.
if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
  cat >&2 <<EOF
[up] image ${IMAGE} not found locally.

Build it from the o11y-bench repo first:

  git clone https://github.com/tedmax100/o11y-bench
  cd o11y-bench
  docker build -t ${IMAGE} -f docker/Dockerfile docker
EOF
  exit 1
fi

if k3d cluster list "${CLUSTER}" >/dev/null 2>&1; then
  echo "[up] cluster ${CLUSTER} already exists"
else
  echo "[up] creating k3d cluster ${CLUSTER}"
  k3d cluster create --config "${DAY_DIR}/k8s/cluster.yaml"
fi

# k3d nodes have their own containerd store, so a local image has to be imported
# explicitly. Without this the pod sits in ErrImagePull even though `docker
# images` on the host clearly shows it.
echo "[up] importing ${IMAGE} into the cluster (this takes ~1 min, the image is ~1.5GB)"
k3d image import "${IMAGE}" -c "${CLUSTER}"

echo "[up] applying manifests"
kubectl apply -f "${DAY_DIR}/k8s/00-namespace.yaml"
kubectl apply -f "${DAY_DIR}/k8s/10-o11y-stack.yaml"

# Telemetry generation runs before the readiness gateway comes up, so the pod
# stays NotReady for a few minutes on a cold start. That is expected.
echo "[up] waiting for the stack to finish generating telemetry (timeout 600s)"
kubectl -n o11y rollout status deploy/o11y-stack --timeout=600s

echo "[up] verifying the data is actually queryable"
for i in $(seq 1 60); do
  if curl -sf "http://localhost:9090/api/v1/query?query=http_requests_total" \
      | grep -q '"result":\[{'; then
    echo "[up] ready."
    echo "  prometheus: http://localhost:9090"
    echo "  loki:       http://localhost:3100"
    echo "  tempo:      http://localhost:3200"
    echo "  grafana:    http://localhost:3000"
    exit 0
  fi
  sleep 5
done

echo "[up] the stack is Ready but Prometheus returned no series — check:"
echo "  kubectl -n o11y logs deploy/o11y-stack"
exit 1
