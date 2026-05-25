#!/usr/bin/env bash
set -Eeuo pipefail

# AutoResearch24 Ubuntu/Debian deployment script.
#
# Usage from the project checkout on the server:
#   DOMAIN=example.com bash scripts/deploy_ubuntu.sh
#
# Common overrides:
#   APP_DIR=/opt/autoresearch24
#   APP_USER=autoresearch24
#   APP_PORT=8000
#   DOMAIN=_
#   SETUP_NGINX=true
#   RUN_TESTS=false
#   DEFAULT_ADMIN_USERNAME=admin
#   DEFAULT_ADMIN_PASSWORD='replace-me'
#
# This script intentionally does not use Docker. It deploys the FastAPI backend
# as a systemd service and serves the Vite build with nginx.

APP_NAME="${APP_NAME:-autoresearch24}"
APP_USER="${APP_USER:-autoresearch24}"
APP_DIR="${APP_DIR:-/opt/autoresearch24}"
APP_HOST="${APP_HOST:-127.0.0.1}"
APP_PORT="${APP_PORT:-8000}"
DOMAIN="${DOMAIN:-_}"
NODE_MAJOR="${NODE_MAJOR:-22}"
SERVICE_NAME="${SERVICE_NAME:-${APP_NAME}.service}"
SETUP_NGINX="${SETUP_NGINX:-true}"
DISABLE_DEFAULT_NGINX_SITE="${DISABLE_DEFAULT_NGINX_SITE:-true}"
RUN_TESTS="${RUN_TESTS:-false}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

log() {
  printf '[deploy] %s\n' "$*"
}

die() {
  printf '[deploy:error] %s\n' "$*" >&2
  exit 1
}

on_error() {
  local exit_code=$?
  printf '[deploy:error] failed at line %s with exit code %s\n' "${BASH_LINENO[0]}" "$exit_code" >&2
  exit "$exit_code"
}
trap on_error ERR

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    log "Re-running with sudo."
    exec sudo -E bash "$0" "$@"
  fi
}

validate_inputs() {
  command -v apt-get >/dev/null 2>&1 || die "This script supports Debian/Ubuntu hosts with apt-get."
  [[ -f "${SOURCE_DIR}/pyproject.toml" ]] || die "Run this script from the project checkout."
  [[ -f "${SOURCE_DIR}/frontend/package.json" ]] || die "frontend/package.json not found."
  [[ "${APP_DIR}" != "/" ]] || die "APP_DIR must not be '/'."
  [[ "${APP_DIR}" != *" "* ]] || die "APP_DIR must not contain spaces."
  [[ "${APP_USER}" != *" "* ]] || die "APP_USER must not contain spaces."
  [[ "${APP_PORT}" =~ ^[0-9]+$ ]] || die "APP_PORT must be numeric."
}

apt_install_base() {
  log "Installing system packages."
  export DEBIAN_FRONTEND=noninteractive
  apt-get update
  apt-get install -y ca-certificates curl gnupg nginx rsync util-linux
}

installed_node_major() {
  if command -v node >/dev/null 2>&1; then
    node -p "Number(process.versions.node.split('.')[0])" 2>/dev/null || printf '0'
  else
    printf '0'
  fi
}

install_node() {
  local current_major
  current_major="$(installed_node_major)"
  if (( current_major >= NODE_MAJOR )); then
    log "Node.js ${current_major}.x already satisfies required major ${NODE_MAJOR}."
    return
  fi

  log "Installing Node.js ${NODE_MAJOR}.x from NodeSource."
  curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | bash -
  apt-get install -y nodejs
}

install_uv() {
  if command -v uv >/dev/null 2>&1; then
    log "uv already installed at $(command -v uv)."
    return
  fi

  log "Installing uv."
  mkdir -p /usr/local/bin
  curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh
  command -v uv >/dev/null 2>&1 || die "uv installation failed."
}

ensure_app_user() {
  if id "${APP_USER}" >/dev/null 2>&1; then
    log "Using existing service user ${APP_USER}."
  else
    log "Creating service user ${APP_USER}."
    useradd --system --user-group --home-dir "${APP_DIR}" --create-home --shell /usr/sbin/nologin "${APP_USER}"
  fi
  APP_GROUP="$(id -gn "${APP_USER}")"
}

sync_source() {
  local source_real app_real
  source_real="$(realpath -m "${SOURCE_DIR}")"
  app_real="$(realpath -m "${APP_DIR}")"

  mkdir -p "${app_real}"

  if [[ "${source_real}" == "${app_real}" ]]; then
    log "Source and target are the same directory; skipping rsync."
    return
  fi

  case "${app_real}" in
    "${source_real}"/*)
      die "APP_DIR must not be inside the source checkout when rsync --delete is used."
      ;;
  esac

  log "Syncing source from ${source_real} to ${app_real}."
  rsync -a --delete \
    --exclude '.git' \
    --exclude '.venv' \
    --exclude '.uv-cache' \
    --exclude '.pytest_cache' \
    --exclude '.ruff_cache' \
    --exclude 'runtime' \
    --exclude 'backend/.env' \
    --exclude 'frontend/node_modules' \
    --exclude 'frontend/dist' \
    "${source_real}/" "${app_real}/"
}

generate_urlsafe_secret() {
  local bytes="${1:-48}"
  head -c "${bytes}" /dev/urandom | base64 | tr '+/' '-_' | tr -d '\n'
}

generate_fernet_key() {
  head -c 32 /dev/urandom | base64 | tr '+/' '-_' | tr -d '\n'
}

write_env_if_missing() {
  local env_file="${APP_DIR}/backend/.env"
  if [[ -f "${env_file}" ]]; then
    log "Preserving existing ${env_file}."
    return
  fi

  log "Creating production backend environment file."
  local secret_key lab4ai_key admin_username admin_password database_url
  secret_key="${SECRET_KEY:-$(generate_urlsafe_secret 64)}"
  lab4ai_key="${LAB4AI_CREDENTIAL_KEY:-$(generate_fernet_key)}"
  admin_username="${DEFAULT_ADMIN_USERNAME:-admin}"
  admin_password="${DEFAULT_ADMIN_PASSWORD:-$(generate_urlsafe_secret 18)}"
  database_url="${DATABASE_URL:-sqlite+aiosqlite:///./runtime/app.db}"

  cat > "${env_file}" <<ENV
APP_NAME=AutoResearch24
APP_ENV=production
APP_HOST=${APP_HOST}
APP_PORT=${APP_PORT}
APP_DEBUG=false

SECRET_KEY=${secret_key}
ACCESS_TOKEN_EXPIRE_MINUTES=1440

DATABASE_URL=${database_url}

DEFAULT_ADMIN_USERNAME=${admin_username}
DEFAULT_ADMIN_PASSWORD=${admin_password}

WORKSPACE_ROOT=runtime/workspaces
SKILLS_DIR=skills
AGENT_RUNTIME_V3_ENABLED=${AGENT_RUNTIME_V3_ENABLED:-false}

LAB4AI_CREDENTIAL_KEY=${lab4ai_key}
ENV

  chmod 0640 "${env_file}"
  chown "${APP_USER}:${APP_GROUP}" "${env_file}"

  if [[ -z "${DEFAULT_ADMIN_PASSWORD:-}" ]]; then
    local credentials_file="/root/${APP_NAME}-initial-admin.txt"
    cat > "${credentials_file}" <<CREDS
AutoResearch24 initial admin credentials
username: ${admin_username}
password: ${admin_password}

The password was generated because DEFAULT_ADMIN_PASSWORD was not set.
Change it after first login.
CREDS
    chmod 0600 "${credentials_file}"
    log "Initial admin credentials written to ${credentials_file}."
  fi
}

prepare_runtime_dirs() {
  log "Preparing runtime directories."
  mkdir -p "${APP_DIR}/runtime/workspaces" "${APP_DIR}/runtime/logs" "${APP_DIR}/.uv-cache"
  chown -R "${APP_USER}:${APP_GROUP}" "${APP_DIR}"
}

run_as_app() {
  runuser -u "${APP_USER}" -- "$@"
}

install_backend() {
  log "Installing backend dependencies with uv."
  local sync_args=(sync --frozen --python 3.13 --project "${APP_DIR}")
  if [[ "${RUN_TESTS}" != "true" ]]; then
    sync_args+=(--no-dev)
  fi

  run_as_app env \
    HOME="${APP_DIR}" \
    UV_CACHE_DIR="${APP_DIR}/.uv-cache" \
    UV_LINK_MODE=copy \
    uv python install 3.13

  run_as_app env \
    HOME="${APP_DIR}" \
    UV_CACHE_DIR="${APP_DIR}/.uv-cache" \
    UV_LINK_MODE=copy \
    uv "${sync_args[@]}"
}

build_frontend() {
  log "Installing frontend dependencies and building static assets."
  run_as_app env HOME="${APP_DIR}" npm --prefix "${APP_DIR}/frontend" ci
  run_as_app env HOME="${APP_DIR}" npm --prefix "${APP_DIR}/frontend" run build
}

run_optional_tests() {
  if [[ "${RUN_TESTS}" != "true" ]]; then
    return
  fi

  log "Running optional backend and frontend tests."
  run_as_app env \
    HOME="${APP_DIR}" \
    UV_CACHE_DIR="${APP_DIR}/.uv-cache" \
    UV_LINK_MODE=copy \
    uv run --project "${APP_DIR}" pytest
  run_as_app env HOME="${APP_DIR}" npm --prefix "${APP_DIR}/frontend" run test:run
}

write_systemd_unit() {
  local service_file="/etc/systemd/system/${SERVICE_NAME}"
  log "Writing systemd unit ${service_file}."
  cat > "${service_file}" <<UNIT
[Unit]
Description=AutoResearch24 FastAPI backend
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${APP_USER}
Group=${APP_GROUP}
WorkingDirectory=${APP_DIR}
Environment=PYTHONDONTWRITEBYTECODE=1
ExecStart=${APP_DIR}/.venv/bin/python -m uvicorn app.main:app --app-dir backend --host ${APP_HOST} --port ${APP_PORT}
Restart=always
RestartSec=5
KillSignal=SIGINT
TimeoutStopSec=30
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ProtectHome=true
ReadWritePaths=${APP_DIR}/runtime
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
UNIT

  systemctl daemon-reload
  systemctl enable "${SERVICE_NAME}"
}

write_nginx_site() {
  if [[ "${SETUP_NGINX}" != "true" ]]; then
    log "Skipping nginx configuration because SETUP_NGINX is not true."
    return
  fi

  local site_name="${APP_NAME}.conf"
  local available="/etc/nginx/sites-available/${site_name}"
  local enabled="/etc/nginx/sites-enabled/${site_name}"

  log "Writing nginx site ${available}."
  cat > "${available}" <<NGINX
map \$http_upgrade \$connection_upgrade {
    default upgrade;
    '' close;
}

server {
    listen 80;
    server_name ${DOMAIN};

    client_max_body_size 100m;
    root ${APP_DIR}/frontend/dist;
    index index.html;

    location /api/ {
        proxy_pass http://${APP_HOST}:${APP_PORT}/api/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection \$connection_upgrade;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    location / {
        try_files \$uri \$uri/ /index.html;
    }
}
NGINX

  ln -sfn "${available}" "${enabled}"
  if [[ "${DISABLE_DEFAULT_NGINX_SITE}" == "true" && -e /etc/nginx/sites-enabled/default ]]; then
    rm -f /etc/nginx/sites-enabled/default
  fi
  nginx -t
}

restart_services() {
  log "Restarting backend service."
  systemctl restart "${SERVICE_NAME}"

  log "Waiting for backend health check."
  local ok=false
  for _ in $(seq 1 30); do
    if curl -fsS "http://${APP_HOST}:${APP_PORT}/api/health" >/dev/null; then
      ok=true
      break
    fi
    sleep 1
  done

  if [[ "${ok}" != "true" ]]; then
    systemctl --no-pager --full status "${SERVICE_NAME}" || true
    journalctl -u "${SERVICE_NAME}" -n 80 --no-pager || true
    die "Backend health check failed."
  fi

  if [[ "${SETUP_NGINX}" == "true" ]]; then
    log "Reloading nginx."
    systemctl reload nginx || systemctl restart nginx
  fi
}

print_summary() {
  local url="http://${DOMAIN}"
  if [[ "${DOMAIN}" == "_" ]]; then
    url="http://<server-ip>"
  fi

  cat <<SUMMARY

Deployment finished.

Application directory: ${APP_DIR}
Backend service:       ${SERVICE_NAME}
Backend health:        http://${APP_HOST}:${APP_PORT}/api/health
Frontend URL:          ${url}
Nginx enabled:         ${SETUP_NGINX}

Useful commands:
  systemctl status ${SERVICE_NAME}
  journalctl -u ${SERVICE_NAME} -f
  nginx -t

SUMMARY
}

main() {
  require_root "$@"
  validate_inputs
  apt_install_base
  install_node
  install_uv
  ensure_app_user
  sync_source
  prepare_runtime_dirs
  write_env_if_missing
  install_backend
  build_frontend
  run_optional_tests
  write_systemd_unit
  write_nginx_site
  restart_services
  print_summary
}

main "$@"
