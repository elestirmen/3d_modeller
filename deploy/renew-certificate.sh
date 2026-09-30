#!/usr/bin/env bash
set -euo pipefail

: "${CLOUDFLARE_API_TOKEN:?CLOUDFLARE_API_TOKEN is required}"
export CF_Token="$CLOUDFLARE_API_TOKEN"

acme_home="$HOME/.acme.sh"
certificate_dir="$HOME/nginx-proxy-manager/letsencrypt/live/3d-models-perinet-org"

docker run --rm \
  --name 3d-models-cert-renew \
  --env CF_Token \
  --volume "$acme_home:/acme.sh" \
  --volume "$certificate_dir:/certs" \
  neilpang/acme.sh:latest \
  --cron --home /acme.sh

docker exec nginx-proxy-manager nginx -s reload
