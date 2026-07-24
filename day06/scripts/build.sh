#!/usr/bin/env bash
# Build all 5 demo-services images and import them into the k3d cluster.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CLUSTER="demo-services"

build_one() {
  local svc="$1"
  local image="demo-services/${svc}:dev"
  echo "[build] ${image}"
  docker build -t "${image}" -f "${ROOT}/services/${svc}/Dockerfile" "${ROOT}"
  k3d image import "${image}" -c "${CLUSTER}"
}

build_one payment
build_one user
build_one order
build_one api-gateway
build_one webapp
