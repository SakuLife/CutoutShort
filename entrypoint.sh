#!/bin/bash
set -e

echo "=== Starting PO Token Server (background) ==="

# PO Token Server をバックグラウンドで起動
bgutil-pot server \
    --host 127.0.0.1 \
    --port "${POT_SERVER_PORT:-4416}" \
    &

POT_PID=$!
echo "PO Token Server started (PID: $POT_PID)"

# サーバーの起動を待つ（最大30秒）
echo "Waiting for PO Token Server to be ready..."
for i in $(seq 1 30); do
    if curl -s "http://127.0.0.1:${POT_SERVER_PORT:-4416}/ping" > /dev/null 2>&1; then
        echo "PO Token Server is ready!"
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "WARNING: PO Token Server did not respond within 30s, continuing anyway..."
    fi
    sleep 1
done

echo "=== Starting main application ==="

# 終了時にPO Tokenサーバーも停止
trap "echo 'Stopping PO Token Server...'; kill $POT_PID 2>/dev/null || true" EXIT

python -m app.multi_scheduler

echo "=== Application completed ==="
