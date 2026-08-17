#!/usr/bin/env bash
set -euo pipefail
REGION="${AWS_REGION:-ap-northeast-1}"
LAB_ID="${LAB_ID:-${USER:-learner}}"
SAFE_ID="$(printf '%s' "$LAB_ID" | tr -cd '[:alnum:]-' | cut -c1-24)"
FUNCTION_NAME="sap-c02-s07-${SAFE_ID}"

if [[ ! "$FUNCTION_NAME" =~ ^sap-c02-s07-[A-Za-z0-9][A-Za-z0-9-]{0,23}$ ]]; then
  echo "LAB_IDから安全なresource名を作れません。英数字で始まる値を指定してください。" >&2
  exit 1
fi

aws lambda update-function-configuration \
  --region "$REGION" --function-name "$FUNCTION_NAME" --memory-size 512 >/dev/null
aws lambda wait function-updated-v2 --region "$REGION" --function-name "$FUNCTION_NAME"
echo "変更完了: memory=512 MB（変更点はこの1項目だけ）"
