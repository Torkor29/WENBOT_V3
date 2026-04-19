#!/bin/bash
# =============================================================================
# WenBot - Deploy a Strategy
# Creates a strategy deployment from the template and applies it
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
K8S_DIR="$(dirname "$SCRIPT_DIR")/k8s"
TEMPLATE="$K8S_DIR/strategy-template.yaml"

# --- Argument validation ---
if [ $# -ne 2 ]; then
    echo "Usage: $0 <strategy_id> <docker_image>"
    echo ""
    echo "Examples:"
    echo "  $0 abc123 wenbot/strategy-momentum:v1.0"
    echo "  $0 def456 ghcr.io/user/my-strategy:latest"
    exit 1
fi

STRATEGY_ID="$1"
DOCKER_IMAGE="$2"
OUTPUT_FILE="$K8S_DIR/strategy-${STRATEGY_ID}.yaml"

echo "============================================"
echo "  Deploying strategy: $STRATEGY_ID"
echo "  Image: $DOCKER_IMAGE"
echo "============================================"

# --- Check template exists ---
if [ ! -f "$TEMPLATE" ]; then
    echo "ERROR: Template not found at $TEMPLATE"
    exit 1
fi

# --- Generate manifest from template ---
echo ""
echo "[1/3] Generating manifest from template..."
sed \
    -e "s|STRATEGY_ID_PLACEHOLDER|${STRATEGY_ID}|g" \
    -e "s|STRATEGY_IMAGE_PLACEHOLDER|${DOCKER_IMAGE}|g" \
    "$TEMPLATE" > "$OUTPUT_FILE"

# Remove template comments from generated file
sed -i '/^# =====/d; /^# Usage:/d; /^# Or use/d; /^#   1\./d; /^#   2\./d; /^#   3\./d; /^#   4\./d; /^#   \.\//d' "$OUTPUT_FILE"

echo "  Manifest written to $OUTPUT_FILE"

# --- Apply to cluster ---
echo ""
echo "[2/3] Applying to cluster..."
sudo k3s kubectl apply -f "$OUTPUT_FILE"

# --- Verify pod status ---
echo ""
echo "[3/3] Verifying pod status..."
echo "  Waiting for pod to start..."
sleep 3

POD_STATUS=$(sudo k3s kubectl -n wenbot-prod get pods -l strategy-id="$STRATEGY_ID" -o jsonpath='{.items[0].status.phase}' 2>/dev/null || echo "Unknown")
POD_NAME=$(sudo k3s kubectl -n wenbot-prod get pods -l strategy-id="$STRATEGY_ID" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "N/A")

echo ""
echo "============================================"
echo "  Strategy deployed!"
echo "  Pod: $POD_NAME"
echo "  Status: $POD_STATUS"
echo "============================================"
echo ""
echo "Useful commands:"
echo "  sudo k3s kubectl -n wenbot-prod logs $POD_NAME"
echo "  sudo k3s kubectl -n wenbot-prod describe pod $POD_NAME"
echo "  sudo k3s kubectl -n wenbot-prod delete deployment strategy-${STRATEGY_ID}"
