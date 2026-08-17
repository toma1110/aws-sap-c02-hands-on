#!/usr/bin/env bash
set -euo pipefail
REGION="${AWS_REGION:-ap-northeast-1}"
LAB_ID="${LAB_ID:-${USER:-learner}}"
SAFE_ID="$(printf '%s' "$LAB_ID" | tr -cd '[:alnum:]-' | cut -c1-24)"
FUNCTION_NAME="sap-c02-s07-${SAFE_ID}"
ROLE_NAME="sap-c02-s07-${SAFE_ID}"
POLICY_ARN="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"

if [[ ! "$FUNCTION_NAME" =~ ^sap-c02-s07-[A-Za-z0-9][A-Za-z0-9-]{0,23}$ ]]; then
  echo "LAB_IDから安全なresource名を作れないためcleanupを停止します。" >&2
  exit 1
fi

if aws lambda get-function --region "$REGION" --function-name "$FUNCTION_NAME" >/dev/null 2>&1; then
  FUNCTION_ARN="$(aws lambda get-function --region "$REGION" --function-name "$FUNCTION_NAME" --query 'Configuration.FunctionArn' --output text)"
  FUNCTION_TAG="$(aws lambda list-tags --resource "$FUNCTION_ARN" --query 'Tags.HandsOn' --output text)"
  [[ "$FUNCTION_TAG" == 's07-continuous-improvement' ]] || { echo "関数tagが一致しないため削除しません。" >&2; exit 1; }
  aws lambda delete-function --region "$REGION" --function-name "$FUNCTION_NAME"
fi
MSYS2_ARG_CONV_EXCL='*' aws logs delete-log-group --region "$REGION" --log-group-name "/aws/lambda/${FUNCTION_NAME}" 2>/dev/null || true
if aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  ROLE_TAG="$(aws iam list-role-tags --role-name "$ROLE_NAME" --query "Tags[?Key=='HandsOn'].Value | [0]" --output text)"
  [[ "$ROLE_TAG" == 's07-continuous-improvement' ]] || { echo "IAM role tagが一致しないため削除しません。" >&2; exit 1; }
  aws iam detach-role-policy --role-name "$ROLE_NAME" --policy-arn "$POLICY_ARN" 2>/dev/null || true
  aws iam delete-role --role-name "$ROLE_NAME"
fi

remaining=0
aws lambda get-function --region "$REGION" --function-name "$FUNCTION_NAME" >/dev/null 2>&1 && remaining=1 || true
MSYS2_ARG_CONV_EXCL='*' aws logs describe-log-groups --region "$REGION" --log-group-name-prefix "/aws/lambda/${FUNCTION_NAME}" \
  --query "length(logGroups[?logGroupName=='/aws/lambda/${FUNCTION_NAME}'])" --output text | grep -qx '0' || remaining=1
aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1 && remaining=1 || true

if [[ "$remaining" != 0 ]]; then
  echo "残存resourceがあります。上の名前を確認してcleanupを再実行してください。" >&2
  exit 1
fi
echo "cleanup確認: Lambda function 0 / log group 0 / IAM role 0"
