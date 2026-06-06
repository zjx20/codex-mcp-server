#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="/opt/codex-mcp-server"
FEATURE_VERSION="${VERSION:-latest}"
SOURCE_HTTP_PROXY="${SOURCE_HTTP_PROXY:-}"
MCP_HTTP_PORT="${MCP_HTTP_PORT:-8765}"
REPO_API_URL="https://api.github.com/repos/zjx20/codex-mcp-server/tarball"

echo "Installing codex-mcp-server feature"
echo "  version: ${FEATURE_VERSION}"
echo "  port: ${MCP_HTTP_PORT}"

install_pkgs() {
    if command -v apt-get >/dev/null 2>&1; then
        export DEBIAN_FRONTEND=noninteractive
        apt-get update -y
        apt-get install -y --no-install-recommends "$@"
    elif command -v apk >/dev/null 2>&1; then
        apk add --no-cache "$@"
    elif command -v dnf >/dev/null 2>&1; then
        dnf install -y "$@"
    elif command -v yum >/dev/null 2>&1; then
        yum install -y "$@"
    else
        echo "ERROR: no supported package manager found (apt/apk/dnf/yum)" >&2
        exit 1
    fi
}

pkg_name() {
    case "$1" in
        pgrep)
            if command -v dnf >/dev/null 2>&1 || command -v yum >/dev/null 2>&1; then
                echo "procps-ng"
            else
                echo "procps"
            fi
            ;;
        python3)
            echo "python3"
            ;;
        pip3)
            if command -v apk >/dev/null 2>&1; then
                echo "py3-pip"
            else
                echo "python3-pip"
            fi
            ;;
        rg)
            echo "ripgrep"
            ;;
        setsid)
            echo "util-linux"
            ;;
        *)
            echo "$1"
            ;;
    esac
}

ensure_cmd() {
    local cmd="$1"
    local pkg
    pkg="$(pkg_name "$cmd")"
    if ! command -v "$cmd" >/dev/null 2>&1; then
        install_pkgs "$pkg"
    fi
}

ensure_cmd curl
ensure_cmd tar
ensure_cmd python3
ensure_cmd rg
ensure_cmd pgrep
ensure_cmd setsid

if command -v apt-get >/dev/null 2>&1; then
    install_pkgs ca-certificates
elif command -v apk >/dev/null 2>&1; then
    install_pkgs ca-certificates
elif command -v dnf >/dev/null 2>&1 || command -v yum >/dev/null 2>&1; then
    install_pkgs ca-certificates
fi

archive_ref="main"
if [ "${FEATURE_VERSION}" != "latest" ]; then
    archive_ref="${FEATURE_VERSION}"
fi

download_url="${REPO_API_URL}/${archive_ref}"
mkdir -p "${INSTALL_DIR}"
rm -rf "${INSTALL_DIR:?}"/*

curl_args=(--fail --silent --show-error --location --retry 3)
if [ -n "${SOURCE_HTTP_PROXY}" ]; then
    curl_args+=(--proxy "${SOURCE_HTTP_PROXY}")
fi

echo "Downloading ${download_url}"
curl "${curl_args[@]}" "${download_url}" | tar -xz -C "${INSTALL_DIR}" --strip-components=1

cat > /usr/local/bin/codex-mcp-server <<'EOF'
#!/usr/bin/env bash
set -euo pipefail

PYTHONPATH_PREFIX="/opt/codex-mcp-server/src"
if [ -n "${PYTHONPATH:-}" ]; then
    export PYTHONPATH="${PYTHONPATH_PREFIX}:${PYTHONPATH}"
else
    export PYTHONPATH="${PYTHONPATH_PREFIX}"
fi

exec python3 -m codex_mcp_server "$@"
EOF
chmod 755 /usr/local/bin/codex-mcp-server

cat > /usr/local/bin/codex-mcp-server-dev-start <<EOF
#!/usr/bin/env bash
set -euo pipefail

export CODEX_MCP_HTTP_PORT="${MCP_HTTP_PORT}"
exec /opt/codex-mcp-server/scripts/devcontainer-post-start.sh
EOF
chmod 755 /usr/local/bin/codex-mcp-server-dev-start

cat > /etc/profile.d/codex-mcp-server-feature.sh <<EOF
export CODEX_MCP_FEATURE_PORT="${MCP_HTTP_PORT}"
EOF
chmod 644 /etc/profile.d/codex-mcp-server-feature.sh

echo "codex-mcp-server feature installed to ${INSTALL_DIR}"
