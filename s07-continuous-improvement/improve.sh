#!/usr/bin/env bash
set -euo pipefail
REGION="${AWS_REGION:-ap-northeast-1}"
EXPECTED_ACCOUNT_ID="${EXPECTED_ACCOUNT_ID:-}"
LAB_ID="${LAB_ID:-${USER:-learner}}"
SAFE_ID="$(printf '%s' "$LAB_ID" | tr -cd '[:alnum:]-' | cut -c1-24)"
FUNCTION_NAME="sap-c02-s07-${SAFE_ID}"

if [[ ! "$FUNCTION_NAME" =~ ^sap-c02-s07-[A-Za-z0-9][A-Za-z0-9-]{0,23}$ ]]; then
  echo "LAB_IDから安全なresource名を作れません。英数字で始まる値を指定してください。" >&2
  exit 1
fi

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
if [[ ! "$EXPECTED_ACCOUNT_ID" =~ ^[0-9]{12}$ || "$ACCOUNT_ID" != "$EXPECTED_ACCOUNT_ID" ]]; then
  echo "現在のAWS accountがEXPECTED_ACCOUNT_IDと一致しないため変更を停止します。" >&2
  exit 1
fi

if ! aws lambda get-function --region "$REGION" --function-name "$FUNCTION_NAME" >/dev/null 2>&1; then
  echo "対象のLambda関数が見つからないため変更を停止します。" >&2
  exit 1
fi
FUNCTION_ARN="$(aws lambda get-function --region "$REGION" --function-name "$FUNCTION_NAME" --query 'Configuration.FunctionArn' --output text)"
FUNCTION_TAG="$(aws lambda list-tags --resource "$FUNCTION_ARN" --query 'Tags.HandsOn' --output text)"
if [[ "$FUNCTION_TAG" != 's07-continuous-improvement' ]]; then
  echo "関数tagが一致しないため変更しません。" >&2
  exit 1
fi

aws lambda update-function-configuration \
  --region "$REGION" --function-name "$FUNCTION_NAME" --memory-size 512 >/dev/null
aws lambda wait function-updated-v2 --region "$REGION" --function-name "$FUNCTION_NAME"
echo "変更完了: memory=512 MB（変更点はこの1項目だけ）"
