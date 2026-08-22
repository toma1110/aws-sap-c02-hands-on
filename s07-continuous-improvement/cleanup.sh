#!/usr/bin/env bash
set -euo pipefail
REGION="${AWS_REGION:-ap-northeast-1}"
EXPECTED_ACCOUNT_ID="${EXPECTED_ACCOUNT_ID:-}"
LAB_ID="${LAB_ID:-${USER:-learner}}"
SAFE_ID="$(printf '%s' "$LAB_ID" | tr -cd '[:alnum:]-' | cut -c1-24)"
FUNCTION_NAME="sap-c02-s07-${SAFE_ID}"
ROLE_NAME="sap-c02-s07-${SAFE_ID}"
LOG_GROUP_NAME="/aws/lambda/${FUNCTION_NAME}"
POLICY_ARN="arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"

if [[ ! "$FUNCTION_NAME" =~ ^sap-c02-s07-[A-Za-z0-9][A-Za-z0-9-]{0,23}$ ]]; then
  echo "LAB_IDから安全なresource名を作れないためcleanupを停止します。" >&2
  exit 1
fi

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
if [[ ! "$EXPECTED_ACCOUNT_ID" =~ ^[0-9]{12}$ || "$ACCOUNT_ID" != "$EXPECTED_ACCOUNT_ID" ]]; then
  echo "現在のAWS accountがEXPECTED_ACCOUNT_IDと一致しないためcleanupを停止します。" >&2
  exit 1
fi

if aws lambda get-function --region "$REGION" --function-name "$FUNCTION_NAME" >/dev/null 2>&1; then
  FUNCTION_ARN="$(aws lambda get-function --region "$REGION" --function-name "$FUNCTION_NAME" --query 'Configuration.FunctionArn' --output text)"
  FUNCTION_TAG="$(aws lambda list-tags --resource "$FUNCTION_ARN" --query 'Tags.HandsOn' --output text)"
  [[ "$FUNCTION_TAG" == 's07-continuous-improvement' ]] || { echo "関数tagが一致しないため削除しません。" >&2; exit 1; }
  aws lambda delete-function --region "$REGION" --function-name "$FUNCTION_NAME"
fi
LOG_COUNT="$(MSYS2_ARG_CONV_EXCL='*' aws logs describe-log-groups --region "$REGION" \
  --log-group-name-prefix "$LOG_GROUP_NAME" \
  --query "length(logGroups[?logGroupName=='${LOG_GROUP_NAME}'])" --output text)"
if [[ "$LOG_COUNT" != 0 ]]; then
  LOG_GROUP_ARN="arn:aws:logs:${REGION}:${ACCOUNT_ID}:log-group:${LOG_GROUP_NAME}"
  LOG_GROUP_TAG="$(aws logs list-tags-for-resource --resource-arn "$LOG_GROUP_ARN" --query 'tags.HandsOn' --output text)"
  [[ "$LOG_GROUP_TAG" == 's07-continuous-improvement' ]] || {
    echo "log group tagが一致しないため削除しません。所有者を確認してください。" >&2
    exit 1
  }
  aws logs delete-log-group --region "$REGION" --log-group-name "$LOG_GROUP_NAME"
fi
if aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  ROLE_TAG="$(aws iam list-role-tags --role-name "$ROLE_NAME" --query "Tags[?Key=='HandsOn'].Value | [0]" --output text)"
  [[ "$ROLE_TAG" == 's07-continuous-improvement' ]] || { echo "IAM role tagが一致しないため削除しません。" >&2; exit 1; }
  aws iam detach-role-policy --role-name "$ROLE_NAME" --policy-arn "$POLICY_ARN" 2>/dev/null || true
  aws iam delete-role --role-name "$ROLE_NAME"
fi

lambda_residual=0
aws lambda get-function --region "$REGION" --function-name "$FUNCTION_NAME" >/dev/null 2>&1 && lambda_residual=1 || true
log_group_residual="$(MSYS2_ARG_CONV_EXCL='*' aws logs describe-log-groups --region "$REGION" \
  --log-group-name-prefix "$LOG_GROUP_NAME" \
  --query "length(logGroups[?logGroupName=='${LOG_GROUP_NAME}'])" --output text)"
iam_role_residual=0
aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1 && iam_role_residual=1 || true

printf 'cleanup residual: lambda=%s\n' "$lambda_residual"
printf 'cleanup residual: log_group=%s\n' "$log_group_residual"
printf 'cleanup residual: iam_role=%s\n' "$iam_role_residual"

if [[ "$lambda_residual" != 0 || "$log_group_residual" != 0 || "$iam_role_residual" != 0 ]]; then
  echo "残存resourceがあります。上の名前を確認してcleanupを再実行してください。" >&2
  exit 1
fi
