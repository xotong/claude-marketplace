# ca-overlay.awk — rewrite a Dockerfile so every shell-form RUN step trusts
# settings.ca_bundle, for local image builds behind TLS inspection.
#
# Usage: awk -v java=0|1 -f ca-overlay.awk Dockerfile > Dockerfile.appsec-ca
#
# Behind a proxy that re-signs every certificate (Zscaler and the like) a local
# `docker build` fails at the first RUN that downloads anything — apk, pip, npm,
# go, gradle — while the same Dockerfile builds fine in CI, whose network has no
# such proxy. The fix must not change the image being scanned, so it adds no
# COPY and no ENV:
#   - the CA directory is bind-mounted per RUN step (RUN --mount=type=bind,
#     from=appsec-ca), which exists only while that step runs and never lands
#     in a layer; the caller supplies it with --build-context appsec-ca=<dir>;
#   - the variables each tool reads are exported inside the step's own shell.
# Every other line is passed through byte for byte. Exec-form (RUN [...]) and
# heredoc (RUN <<EOF) steps are left untouched: neither goes through a shell
# that could take the exports.
#
# java=1 only when <dir>/truststore.p12 exists: a JVM pointed at a missing
# truststore fails every TLS handshake, which is worse than not trying.
BEGIN {
  ca = "/tmp/appsec-ca"
  mount = "--mount=type=bind,from=appsec-ca,target=" ca
  envs = "export SSL_CERT_FILE=" ca "/ca.pem CURL_CA_BUNDLE=" ca "/ca.pem" \
         " REQUESTS_CA_BUNDLE=" ca "/ca.pem PIP_CERT=" ca "/ca.pem" \
         " NODE_EXTRA_CA_CERTS=" ca "/ca.pem GIT_SSL_CAINFO=" ca "/ca.pem" \
         " WGETRC=" ca "/wgetrc"
  if (java == 1) {
    envs = envs " JAVA_TOOL_OPTIONS=\"${JAVA_TOOL_OPTIONS:+$JAVA_TOOL_OPTIONS }" \
           "-Djavax.net.ssl.trustStore=" ca "/truststore.p12" \
           " -Djavax.net.ssl.trustStorePassword=changeit" \
           " -Djavax.net.ssl.trustStoreType=PKCS12\""
  }
  envs = envs ";"
}
{
  if (match($0, /^[ \t]*[Rr][Uu][Nn][ \t]+/)) {
    head = substr($0, 1, RLENGTH)
    rest = substr($0, RLENGTH + 1)
    flags = ""
    while (match(rest, /^--[^ \t]+[ \t]+/)) {
      flags = flags substr(rest, 1, RLENGTH)
      rest = substr(rest, RLENGTH + 1)
    }
    if (rest ~ /^\[/ || rest ~ /^<</) { print; next }
    print head mount " " flags envs " " rest
    next
  }
  print
}
