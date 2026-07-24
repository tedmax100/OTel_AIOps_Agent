#!/usr/bin/env bash
# Bring up the demo-services k3d cluster and apply all manifests.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CLUSTER="demo-services"

if ! k3d cluster list "${CLUSTER}" >/dev/null 2>&1; then
  echo "[up] creating k3d cluster ${CLUSTER}"
  k3d cluster create --config "${ROOT}/k8s/cluster.yaml"
else
  echo "[up] cluster ${CLUSTER} already exists"
fi

echo "[up] building all service images"
"${ROOT}/scripts/build.sh"

# Bind-mount the aiops-agent Grafana plugin dist into the k3d node so the
# grafana Deployment's hostPath volume (see 14-grafana.yaml) can pick it up.
# If the dist isn't built yet, lay down a placeholder so the hostPath mount
# still resolves — the user can rebuild + re-cp without recreating the cluster.
PLUGIN_DIST="${ROOT}/../aiops-agent/plugin/dist"
NODE_CONTAINER="k3d-${CLUSTER}-server-0"
if [[ -d "${PLUGIN_DIST}" ]]; then
  echo "[up] copying aiops-agent plugin dist into ${NODE_CONTAINER}"
  docker exec "${NODE_CONTAINER}" mkdir -p /aiops-plugin
  docker exec "${NODE_CONTAINER}" rm -rf /aiops-plugin/tedmax100-aiops-app
  docker cp "${PLUGIN_DIST}" "${NODE_CONTAINER}:/aiops-plugin/tedmax100-aiops-app"
else
  echo "[up] WARN: ${PLUGIN_DIST} not found — creating empty placeholder so grafana hostPath resolves"
  echo "[up]       build the plugin (cd aiops-agent/plugin && npm install && npm run build), then re-run up.sh"
  docker exec "${NODE_CONTAINER}" mkdir -p /aiops-plugin/tedmax100-aiops-app
fi

echo "[up] applying manifests"
# Apply in numeric prefix order: 00-namespace then everything else.
# cluster.yaml is a k3d config, not a k8s resource — skip it.
for f in "${ROOT}"/k8s/[0-9]*-*.yaml; do
  kubectl apply -f "$f"
done

echo "[up] waiting for pods to become ready (timeout 180s)"
kubectl -n demo wait --for=condition=Ready pod --all --timeout=180s || {
  echo "[up] some pods are not ready; check 'kubectl -n demo get pods'"
  exit 1
}

echo "[up] ready."
echo "  grafana: http://localhost:3001"
echo "  webapp:  http://localhost:8002   (public entrypoint)"
echo "  payment: http://localhost:8001   (direct, for debugging)"
