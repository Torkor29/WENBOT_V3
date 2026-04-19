#!/bin/bash
# =============================================================================
# WenBot - K3s Setup Script
# Installs K3s on a VPS and bootstraps the wenbot-prod environment
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
K8S_DIR="$(dirname "$SCRIPT_DIR")/k8s"

echo "============================================"
echo "  WenBot - K3s Setup"
echo "============================================"

# --- Step 1: Install K3s ---
echo ""
echo "[1/5] Installing K3s..."
if command -v k3s &> /dev/null; then
    echo "  K3s is already installed, skipping."
else
    curl -sfL https://get.k3s.io | sh -
    echo "  K3s installed successfully."
fi

# Wait for K3s to be ready
echo "  Waiting for K3s to be ready..."
sleep 5
sudo k3s kubectl wait --for=condition=Ready node --all --timeout=120s

# Set up kubeconfig for current user
export KUBECONFIG=/etc/rancher/k3s/k3s.yaml
echo "  KUBECONFIG set to /etc/rancher/k3s/k3s.yaml"

# --- Step 2: Create namespace ---
echo ""
echo "[2/5] Creating namespace wenbot-prod..."
sudo k3s kubectl apply -f "$K8S_DIR/namespace.yaml"
echo "  Namespace wenbot-prod created."

# --- Step 3: Remind about secrets ---
echo ""
echo "[3/5] Secrets reminder"
echo "  ============================================"
echo "  IMPORTANT: You must create your secrets before deploying!"
echo ""
echo "  1. cp $K8S_DIR/secrets.yaml.example $K8S_DIR/secrets.yaml"
echo "  2. Edit secrets.yaml with your real base64-encoded values"
echo "  3. Run: sudo k3s kubectl apply -f $K8S_DIR/secrets.yaml"
echo "  ============================================"
echo ""
read -p "  Press Enter once secrets are applied (or Ctrl+C to abort)..."

# --- Step 4: Deploy Redis ---
echo ""
echo "[4/5] Deploying Redis..."
sudo k3s kubectl apply -f "$K8S_DIR/redis.yaml"
echo "  Waiting for Redis to be ready..."
sudo k3s kubectl -n wenbot-prod wait --for=condition=Ready pod -l app=redis --timeout=120s
echo "  Redis is running."

# --- Step 5: Apply network policy ---
echo ""
echo "[5/5] Applying network policy for strategy isolation..."
sudo k3s kubectl apply -f "$K8S_DIR/network-policy-strategy.yaml"
echo "  Network policy applied."

echo ""
echo "============================================"
echo "  K3s setup complete!"
echo "============================================"
echo ""
echo "Next steps:"
echo "  1. Deploy the telegram bot:"
echo "     sudo k3s kubectl apply -f $K8S_DIR/telegram-bot.yaml"
echo "  2. Deploy the execution engine:"
echo "     sudo k3s kubectl apply -f $K8S_DIR/execution-engine.yaml"
echo "  3. Deploy strategies using:"
echo "     ./scripts/deploy_strategy.sh <strategy_id> <docker_image>"
echo ""
echo "Useful commands:"
echo "  sudo k3s kubectl -n wenbot-prod get pods"
echo "  sudo k3s kubectl -n wenbot-prod logs <pod-name>"
