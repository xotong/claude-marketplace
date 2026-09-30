#!/usr/bin/env bash
# build-ca-context.sh <ca-bundle> <out-dir> <runtime> [keytool-image]
#
# Prepares the build context ca-overlay.awk mounts into every RUN step of a
# local container build: <out-dir>/ca.pem (the bundle as-is) and, when a
# keytool can be found, <out-dir>/truststore.p12 for JVM builds (Gradle,
# Maven), which cannot read a PEM bundle.
#
# keytool comes from the host when it has one, otherwise from [keytool-image]
# (run-scan.sh passes the Fortify image, which ships a JDK). The truststore is
# rebuilt only when the bundle changed — importing ~120 certificates one JVM
# start at a time is the slow part, and .appsec-results outlives a run.
#
# Prints java=1 when truststore.p12 is ready, java=0 when it is not (JVM builds
# then run without it; everything else still trusts ca.pem). Exits non-zero
# only when ca.pem itself could not be written.
set -euo pipefail

if [[ $# -lt 3 ]]; then
  echo "Usage: $0 <ca-bundle> <out-dir> <runtime> [keytool-image]" >&2
  exit 2
fi
bundle=$1
out=$2
runtime=$3
keytool_image=${4:-}

mkdir -p "$out"
# GNU wget ignores SSL_CERT_FILE; ca-overlay.awk points WGETRC here instead.
printf 'ca_certificate = /tmp/appsec-ca/ca.pem\n' >"$out/wgetrc"
if [[ -f "$out/ca.pem" && -f "$out/truststore.p12" ]] && cmp -s "$bundle" "$out/ca.pem"; then
  echo "java=1"
  exit 0
fi
cp "$bundle" "$out/ca.pem"
rm -f "$out/truststore.p12"

# One certificate per file: keytool -importcert reads a single certificate.
certs="$out/.certs"
rm -rf "$certs"
mkdir -p "$certs"
awk -v dir="$certs" '
  /-----BEGIN CERTIFICATE-----/ { n++; file = sprintf("%s/c-%04d.pem", dir, n); inside = 1 }
  inside { print > file }
  /-----END CERTIFICATE-----/ { inside = 0; close(file) }
' "$out/ca.pem"

import_all='n=0
for f in "$1"/c-*.pem; do
  [ -f "$f" ] || continue
  n=$((n + 1))
  keytool -importcert -noprompt -storetype PKCS12 -keystore "$2" \
    -storepass changeit -alias "appsec-ca-$n" -file "$f" >/dev/null 2>&1 || :
done'

if command -v keytool >/dev/null 2>&1; then
  sh -c "$import_all" sh "$certs" "$out/truststore.p12" || :
elif [[ -n "$keytool_image" ]] && "$runtime" image inspect "$keytool_image" >/dev/null 2>&1; then
  # Run as the invoking user so the truststore lands owned by them, not by the
  # image's uid, on hosts where bind mounts keep ownership.
  "$runtime" run --rm --user "$(id -u):$(id -g)" --entrypoint sh \
    -v "$(cd "$out" && pwd):/appsec-ca" "$keytool_image" \
    -c "$import_all" sh /appsec-ca/.certs /appsec-ca/truststore.p12 >/dev/null 2>&1 || :
fi
rm -rf "$certs"

if [[ -s "$out/truststore.p12" ]]; then
  echo "java=1"
else
  rm -f "$out/truststore.p12"
  echo "java=0"
fi
