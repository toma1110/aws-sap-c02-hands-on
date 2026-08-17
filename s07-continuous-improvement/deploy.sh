#!/usr/bin/env bash
set -euo pipefail

REGION="${AWS_REGION:-ap-northeast-1}"
LAB_ID="${LAB_ID:-${USER:-learner}}"
SAFE_ID="$(printf '%s' "$LAB_ID" | tr -cd '[:alnum:]-' | cut -c1-24)"
FUNCTION_NAME="sap-c02-s07-${SAFE_ID}"
ROLE_NAME="sap-c02-s07-${SAFE_ID}"
POLICY_ARN="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"

if [[ ! "$FUNCTION_NAME" =~ ^sap-c02-s07-[A-Za-z0-9][A-Za-z0-9-]{0,23}$ ]]; then
  echo "LAB_IDから安全なresource名を作れません。英数字で始まる値を指定してください。" >&2
  exit 1
fi

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
printf 'Account: %s\nRegion: %s\nFunction: %s\nRole: %s\n' "$ACCOUNT_ID" "$REGION" "$FUNCTION_NAME" "$ROLE_NAME"

if aws lambda get-function --region "$REGION" --function-name "$FUNCTION_NAME" >/dev/null 2>&1; then
  echo "同名の関数が既にあります。cleanup.shを実行するかLAB_IDを変更してください。" >&2
  exit 1
fi
if aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  echo "同名のIAM roleが既にあります。所有者を確認し、別のLAB_IDを使用してください。" >&2
  exit 1
fi
LOG_COUNT="$(MSYS2_ARG_CONV_EXCL='*' aws logs describe-log-groups --region "$REGION" \
  --log-group-name-prefix "/aws/lambda/${FUNCTION_NAME}" \
  --query "length(logGroups[?logGroupName=='/aws/lambda/${FUNCTION_NAME}'])" --output text)"
if [[ "$LOG_COUNT" != 0 ]]; then
  echo "同名のlog groupが既にあります。所有者を確認し、別のLAB_IDを使用してください。" >&2
  exit 1
fi

TRUST_POLICY='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
BUILD_DIR="$(pwd)/.s07-build"
rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR"
trap 'rm -rf "$BUILD_DIR"' EXIT

aws iam create-role \
  --role-name "$ROLE_NAME" \
  --assume-role-policy-document "$TRUST_POLICY" \
  --tags Key=Course,Value=aws-sap-c02 Key=HandsOn,Value=s07-continuous-improvement >/dev/null
aws iam attach-role-policy --role-name "$ROLE_NAME" --policy-arn "$POLICY_ARN"

if command -v zip >/dev/null 2>&1; then
  zip -q -j "$BUILD_DIR/function.zip" "$(dirname "$0")/handler.py"
else
  python3 -c 'import sys, zipfile; z=zipfile.ZipFile(sys.argv[1], "w", zipfile.ZIP_DEFLATED); z.write(sys.argv[2], "handler.py"); z.close()' \
    "$BUILD_DIR/function.zip" "$(dirname "$0")/handler.py"
fi
ROLE_ARN="arn:aws:iam::${ACCOUNT_ID}:role/${ROLE_NAME}"
ZIP_PATH="$BUILD_DIR/function.zip"
if command -v cygpath >/dev/null 2>&1; then
  ZIP_PATH="$(cygpath -w "$ZIP_PATH")"
fi

for attempt in {1..12}; do
  if aws lambda create-function \
    --region "$REGION" \
    --function-name "$FUNCTION_NAME" \
    --runtime python3.12 \
    --handler handler.lambda_handler \
    --role "$ROLE_ARN" \
    --zip-file "fileb://$ZIP_PATH" \
    --memory-size 128 \
    --timeout 30 \
    --tags Course=aws-sap-c02,HandsOn=s07-continuous-improvement >/dev/null 2>/tmp/s07-create-error.txt; then
    break
  fi
  if [[ "$attempt" == 12 ]]; then
    cat /tmp/s07-create-error.txt >&2
    exit 1
  fi
  sleep 5
done

aws lambda wait function-active-v2 --region "$REGION" --function-name "$FUNCTION_NAME"
echo "作成完了: memory=128 MB"
