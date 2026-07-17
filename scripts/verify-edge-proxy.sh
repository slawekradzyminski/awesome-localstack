#!/usr/bin/env bash
set -Eeuo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
network="awesome-edge-proxy-test-$$"
edge="awesome-edge-proxy-test-edge-$$"
echo_server="awesome-edge-proxy-test-echo-$$"
test_config="$(mktemp)"

cleanup() {
  docker stop "${edge}" "${echo_server}" >/dev/null 2>&1 || true
  docker network rm "${network}" >/dev/null 2>&1 || true
  rm -f -- "${test_config}"
}
trap cleanup EXIT

sed 's#http://127.0.0.1:8080#http://echo:80#' \
  "${repo_root}/nginx/conf.d/edge-gateway.conf" > "${test_config}"

docker network create "${network}" >/dev/null
docker run --detach --rm \
  --name "${echo_server}" \
  --network "${network}" \
  --network-alias echo \
  traefik/whoami:v1.11.0 >/dev/null
docker run --detach --rm \
  --name "${edge}" \
  --network "${network}" \
  --network-alias edge \
  --volume "${test_config}:/etc/nginx/conf.d/default.conf:ro" \
  nginx:1.31.2-trixie >/dev/null

response=""
for _ in $(seq 1 20); do
  if response="$(
    docker run --rm --network "${network}" curlimages/curl:8.21.0 \
      --fail \
      --silent \
      --show-error \
      --header 'X-Forwarded-For: 198.51.100.77' \
      http://edge/
  )"; then
    break
  fi
  sleep 1
done

if [[ -z "${response}" ]]; then
  echo "Edge proxy did not return a response" >&2
  exit 1
fi

if grep -q '198\.51\.100\.77' <<<"${response}"; then
  echo "Edge proxy passed a spoofed X-Forwarded-For value upstream" >&2
  exit 1
fi

if ! grep -qi '^X-Forwarded-For: ' <<<"${response}"; then
  echo "Edge proxy did not provide a sanitized X-Forwarded-For value" >&2
  exit 1
fi

echo "Edge proxy rejected the spoofed client address"
