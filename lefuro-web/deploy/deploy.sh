#!/usr/bin/env bash
#
# deploy.sh — public/ 配下を さくら(www2) へ FTP アップロードする
#
# ⚠️ ネットワークについて:
#   FTP(21)/SSH(22) は Claude Code on the web のクラウド環境からは到達不可
#   （HTTP/HTTPS プロキシのみ）。本スクリプトは FTP が通る環境
#   （手元PC や FTP 許可のある環境）で実行する想定。
#
# 使い方:
#   cp deploy/.env.sample deploy/.env   # 実値を記入
#   ./deploy/deploy.sh                  # public/ 全体を配置
#   ./deploy/deploy.sh public/index.html  # 単一ファイルだけ配置
#
# 依存: bash, curl
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT/deploy/.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "エラー: $ENV_FILE がありません。deploy/.env.sample を複製してください。" >&2
  exit 1
fi
# shellcheck disable=SC1090
set -a; source "$ENV_FILE"; set +a

: "${FTP_HOST:?}" "${FTP_USER:?}" "${FTP_PASS:?}" "${FTP_REMOTE_DIR:?}"

PUBLIC_DIR="$ROOT/public"

# アップロード対象を決める（引数があればそれ、なければ public/ 全体）
if [[ $# -gt 0 ]]; then
  FILES=("$@")
else
  mapfile -t FILES < <(cd "$PUBLIC_DIR" && find . -type f \
    ! -name 'config.php' ! -name '*.sample' ! -name '.htpasswd' \
    | sed 's|^\./||')
fi

upload_one() {
  local rel="$1"
  # public/ からの相対パスに正規化
  rel="${rel#public/}"
  local local_path="$PUBLIC_DIR/$rel"
  if [[ ! -f "$local_path" ]]; then
    echo "  skip（無し）: $rel"; return 0
  fi
  local remote_dir
  remote_dir="$(dirname "$rel")"
  echo "  → $rel"
  # 中間ディレクトリを作りつつアップロード（--ftp-create-dirs）
  curl -sS --ftp-create-dirs -T "$local_path" \
    -u "$FTP_USER:$FTP_PASS" \
    "ftp://$FTP_HOST/$FTP_REMOTE_DIR/$rel"
}

echo "FTP 配置先: $FTP_HOST /$FTP_REMOTE_DIR/"
for f in "${FILES[@]}"; do upload_one "$f"; done
echo "完了。"

# 疎通確認（任意）
if [[ -n "${SITE_HOST:-}" && -n "${SITE_IP:-}" ]]; then
  scheme="${SITE_SCHEME:-http}"
  port=80; [[ "$scheme" == "https" ]] && port=443
  code=$(curl -sS -k -o /dev/null -w "%{http_code}" \
    --resolve "$SITE_HOST:$port:$SITE_IP" "$scheme://$SITE_HOST/" || echo "ERR")
  echo "疎通確認 $scheme://$SITE_HOST/ → HTTP $code"
fi
