#!/bin/sh
set -eu

# Generated configuration stays outside the document root and contains secrets.
umask 077
mkdir -p /etc/nginx/operator-gateway
rm -f /etc/nginx/conf.d/10-odin-operator-maps.conf /etc/nginx/operator-gateway/locations.conf
case "${ODIN_OPERATOR_GATEWAY_ENABLED:-false}" in
    false) exit 0 ;;
    true) ;;
    *) echo "Invalid ODIN_OPERATOR_GATEWAY_ENABLED (expected true or false)" >&2; exit 1 ;;
esac

secret_file="${ODIN_OPERATOR_TOKEN_FILE:-/run/secrets/odin_operator_token}"
if [ ! -r "$secret_file" ]; then
    echo "Operator gateway requires a readable runtime token file" >&2
    exit 1
fi
ODIN_OPERATOR_TOKEN=$(sed 's/^[[:space:]]*//;s/[[:space:]]*$//' "$secret_file")
# Restrict nginx interpolation to the existing gateway's URL-safe credential format.
case "$ODIN_OPERATOR_TOKEN" in
    *[!A-Za-z0-9_-]*|'') echo "Invalid operator token format" >&2; exit 1 ;;
esac
if [ "${#ODIN_OPERATOR_TOKEN}" -lt 32 ] || [ "${#ODIN_OPERATOR_TOKEN}" -gt 128 ]; then
    echo "Operator token must contain 32 to 128 URL-safe characters" >&2
    exit 1
fi
export ODIN_OPERATOR_TOKEN
envsubst '${ODIN_OPERATOR_TOKEN}' < /opt/odin/operator-gateway/maps.conf.template \
    > /etc/nginx/conf.d/10-odin-operator-maps.conf
envsubst '${ODIN_OPERATOR_TOKEN}' < /opt/odin/operator-gateway/locations.conf.template \
    > /etc/nginx/operator-gateway/locations.conf
unset ODIN_OPERATOR_TOKEN
