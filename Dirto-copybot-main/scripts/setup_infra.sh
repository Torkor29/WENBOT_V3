#!/usr/bin/env bash
#
# WenBot Infrastructure Setup
# ============================
# Installs: WireGuard → K3s → Build images → Deploy everything
#
# Usage:
#   sudo bash scripts/setup_infra.sh          # Run everything
#   sudo bash scripts/setup_infra.sh wireguard # Only WireGuard
#   sudo bash scripts/setup_infra.sh k3s       # Only K3s
#   sudo bash scripts/setup_infra.sh build     # Only build images
#   sudo bash scripts/setup_infra.sh deploy    # Only deploy to K3s
#
set -euo pipefail

# ── Config ──────────────────────────────────────────────────────────
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
WG_IFACE="wg0"
WG_IP="10.1.0.9"           # VPS IP on existing WireGuard network
PUBLIC_IFACE="enp1s0"
PUBLIC_IP="65.20.111.101"
NAMESPACE="wenbot-prod"
DOMAIN="copytrade.vqnirr.me"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()  { echo -e "${BLUE}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
fail()  { echo -e "${RED}[FAIL]${NC} $*"; exit 1; }
step()  { echo -e "\n${GREEN}━━━ $* ━━━${NC}\n"; }

check_wireguard() {
    step "Phase 1: WireGuard check"

    if ip link show "$WG_IFACE" &>/dev/null; then
        local wg_ip
        wg_ip=$(ip -4 addr show "$WG_IFACE" | grep -oP '(?<=inet )\S+' | cut -d/ -f1)
        ok "WireGuard $WG_IFACE up on $wg_ip"

        # Firewall: block Traefik ports on public interface (only allow via WireGuard)
        iptables -C INPUT -i "$PUBLIC_IFACE" -p tcp --dport 80 -j DROP 2>/dev/null || \
            iptables -A INPUT -i "$PUBLIC_IFACE" -p tcp --dport 80 -j DROP
        iptables -C INPUT -i "$PUBLIC_IFACE" -p tcp --dport 443 -j DROP 2>/dev/null || \
            iptables -A INPUT -i "$PUBLIC_IFACE" -p tcp --dport 443 -j DROP
        info "Firewall: ports 80/443 blocked on $PUBLIC_IFACE (only accessible via $WG_IFACE)"

        # Persist iptables rules
        if command -v netfilter-persistent &>/dev/null; then
            netfilter-persistent save >/dev/null 2>&1 || true
        else
            apt-get install -y -qq iptables-persistent >/dev/null 2>&1 || true
            netfilter-persistent save >/dev/null 2>&1 || true
        fi
    else
        fail "WireGuard $WG_IFACE is not up. Start it with: sudo systemctl start wg-quick@wg0"
    fi
}

# ════════════════════════════════════════════════════════════════════
# Phase 2: K3s
# ════════════════════════════════════════════════════════════════════
install_k3s() {
    step "Phase 2: K3s (lightweight Kubernetes)"

    if command -v k3s &>/dev/null; then
        ok "K3s already installed: $(k3s --version | head -1)"
    else
        info "Installing K3s..."
        # Install K3s with Docker backend (reuse existing Docker)
        # --tls-san: add WireGuard IP for kubectl access via VPN
        curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="server \
            --docker \
            --tls-san ${WG_IP} \
            --tls-san ${PUBLIC_IP} \
            --node-ip ${PUBLIC_IP} \
            --write-kubeconfig-mode 644" sh -
        ok "K3s installed"
    fi

    # Wait for K3s to be ready
    info "Waiting for K3s node to be Ready..."
    for i in $(seq 1 60); do
        if kubectl get nodes 2>/dev/null | grep -q " Ready"; then
            break
        fi
        sleep 2
    done
    kubectl get nodes || fail "K3s node not ready after 120s"

    # Configure Traefik to bind to WireGuard IP only
    info "Configuring Traefik to bind to WireGuard interface..."
    kubectl apply -f "$REPO_DIR/k8s/traefik-config.yaml"
    ok "Traefik configured for WireGuard-only access"

    # Wait for Traefik to restart with new config
    sleep 5
    kubectl -n kube-system rollout restart deployment traefik 2>/dev/null || true
    info "Traefik restarting with WireGuard binding..."

    # Setup kubeconfig for non-root user
    KUBE_DIR="/home/lab/.kube"
    mkdir -p "$KUBE_DIR"
    cp /etc/rancher/k3s/k3s.yaml "$KUBE_DIR/config"
    chown -R lab:lab "$KUBE_DIR"
    chmod 600 "$KUBE_DIR/config"
    ok "kubeconfig installed for user lab"
}

# ════════════════════════════════════════════════════════════════════
# Phase 3: Build Docker images
# ════════════════════════════════════════════════════════════════════
build_images() {
    step "Phase 3: Build Docker images"

    cd "$REPO_DIR"

    info "Building wenbot/engine..."
    docker build -f engine/Dockerfile -t wenbot/engine:latest .

    info "Building wenbot/bot..."
    docker build -f bot/Dockerfile -t wenbot/bot:latest .

    info "Building wenbot/strategy-test..."
    docker build -f strategies/example_strategy/Dockerfile -t wenbot/strategy-test:latest .

    ok "All images built"
    docker images | grep wenbot
}

# ════════════════════════════════════════════════════════════════════
# Phase 4: Deploy everything to K3s
# ════════════════════════════════════════════════════════════════════
deploy_all() {
    step "Phase 4: Deploy to K3s"

    cd "$REPO_DIR"

    # 4a. Create namespace
    info "Creating namespace ${NAMESPACE}..."
    kubectl apply -f k8s/namespace.yaml

    # 4b. Create secrets from .env
    info "Creating secrets from .env..."
    create_secrets

    # 4c. Deploy Redis
    info "Deploying Redis..."
    kubectl apply -f k8s/redis.yaml
    kubectl -n "$NAMESPACE" rollout status statefulset/redis --timeout=60s
    ok "Redis ready"

    # 4d. Deploy execution engine
    info "Deploying execution engine..."
    kubectl apply -f k8s/execution-engine.yaml
    ok "Execution engine deployed"

    # 4e. Deploy Telegram bot
    info "Deploying Telegram bot..."
    kubectl apply -f k8s/telegram-bot.yaml
    ok "Telegram bot deployed"

    # 4f. Apply network policy
    info "Applying network policy for strategies..."
    kubectl apply -f k8s/network-policy-strategy.yaml
    ok "Network policy applied"

    # 4g. Deploy Portainer
    info "Deploying Portainer..."
    kubectl apply -f k8s/portainer.yaml
    kubectl -n portainer rollout status deployment/portainer --timeout=120s
    ok "Portainer deployed"

    echo ""
    step "Deployment complete"
    echo ""
    kubectl -n "$NAMESPACE" get pods
    echo ""
    kubectl -n portainer get pods
    echo ""
    ok "Portainer: http://portainer.${DOMAIN}"
    warn "First login: create admin user within 5 minutes or Portainer locks out"
}

create_secrets() {
    # Read .env and create K8s secret
    ENV_FILE="$REPO_DIR/.env"
    if [[ ! -f "$ENV_FILE" ]]; then
        fail ".env file not found at $ENV_FILE"
    fi

    # Build --from-literal args from .env, override REDIS_URL for in-cluster
    local ARGS=""
    while IFS= read -r line; do
        line=$(echo "$line" | xargs)  # trim
        [[ -z "$line" || "$line" == \#* ]] && continue
        key="${line%%=*}"
        value="${line#*=}"
        # Strip quotes
        value="${value#\"}" ; value="${value%\"}"
        value="${value#\'}" ; value="${value%\'}"
        # Override REDIS_URL for in-cluster access
        if [[ "$key" == "REDIS_URL" ]]; then
            value="redis://redis.${NAMESPACE}.svc.cluster.local:6379"
        fi
        ARGS="$ARGS --from-literal=${key}=${value}"
    done < "$ENV_FILE"

    # Delete old secret if exists, then create
    kubectl -n "$NAMESPACE" delete secret wenbot-secrets 2>/dev/null || true
    eval kubectl -n "$NAMESPACE" create secret generic wenbot-secrets $ARGS
    ok "Secret wenbot-secrets created in $NAMESPACE"
}

# ════════════════════════════════════════════════════════════════════
# Main
# ════════════════════════════════════════════════════════════════════
main() {
    echo ""
    echo -e "${GREEN}╔══════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║   WenBot Infrastructure Setup            ║${NC}"
    echo -e "${GREEN}║   VPS: ${PUBLIC_IP} (Vultr ES)          ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════╝${NC}"
    echo ""

    if [[ $EUID -ne 0 ]]; then
        fail "This script must be run as root (sudo)"
    fi

    local PHASE="${1:-all}"

    case "$PHASE" in
        wireguard|wg)  check_wireguard ;;
        k3s)           install_k3s ;;
        build)         build_images ;;
        deploy)        deploy_all ;;
        all)
            check_wireguard
            install_k3s
            build_images
            deploy_all
            ;;
        *)
            echo "Usage: $0 {all|wireguard|k3s|build|deploy}"
            exit 1
            ;;
    esac

    echo ""
    ok "Done! Run 'kubectl -n $NAMESPACE get pods' to check status."
}

main "$@"
