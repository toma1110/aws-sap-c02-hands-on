# 観測結果から改善前後を比較する

同じ処理を同じ回数だけ実行し、観測結果から変更を一つ選びます。変更後も同じ条件で測定し、応答時間だけでなく費用への副作用と処理結果の同一性を確認します。

## 作成するもの

- AWS Lambda関数 1個（128 MBから開始）
- Lambda実行用IAM role 1個
- Lambdaが自動作成するCloudWatch Logs log group 1個

既定Regionは東京（`ap-northeast-1`）です。すべての名前には `sap-c02-s07-` が付きます。

## 前提と権限

AWS CloudShellで実行します。AWS CLI、Python 3、zipを使用します。次の操作権限が必要です。

- `sts:GetCallerIdentity`
- Lambda関数の作成、取得、実行、設定変更、削除、tag付与・`lambda:ListTags`
- IAM roleの作成、取得、managed policyの付け外し、削除、`iam:PassRole`、`iam:TagRole`、`iam:ListRoleTags`
- 対象log groupの`logs:DescribeLogGroups`と`logs:DeleteLogGroup`

scriptのローカルtestは次で実行できます。

```bash
python3 -m unittest discover -s tests -v
```

演習用アカウントで実行し、本番環境と同じ名前を使わないでください。

## 料金

Lambdaのリクエスト数と実行時間、CloudWatch Logsの取り込み・保存に料金が発生し得ます。この演習は短い関数を18回実行し、通常はごく少額ですが、無料利用枠は保証しません。実行前に[AWS Pricing Calculator](https://calculator.aws/)と利用中Regionの料金を確認してください。終了後は必ずcleanupします。

## 1. 準備

```bash
git clone https://github.com/toma1110/aws-sap-c02-hands-on.git
cd aws-sap-c02-hands-on/s07-continuous-improvement
export AWS_REGION=ap-northeast-1
export LAB_ID="$(whoami)-$(date +%H%M%S)"
bash deploy.sh
```

表示されたaccount、Region、関数名、role名が演習対象と一致することを確認します。同名関数が既にある場合、scriptは上書きせず停止します。

## 2. beforeを測定する

```bash
FUNCTION_NAME="sap-c02-s07-$(printf '%s' "$LAB_ID" | tr -cd '[:alnum:]-' | cut -c1-24)"
python3 measure.py --phase before --function-name "$FUNCTION_NAME" --region "$AWS_REGION" --output before.json
```

warm-up 1回を除外し、同じ25万回のSHA-256計算を8回測ります。`median_duration_ms`、`median_billed_duration_ms`、`max_memory_used_mb`、`median_cost_proxy_mb_ms`を確認します。費用代理値はメモリMB×課金時間msであり、実際の請求額そのものではありません。

## 3. 変更を一つだけ適用する

```bash
bash improve.sh
```

変更するのはLambdaのメモリを128 MBから512 MBへ増やすことだけです。Lambdaではメモリ量に応じてCPU能力も増えるため、CPU負荷の処理時間が短くなるかを検証します。

## 4. afterを同条件で測定する

```bash
python3 measure.py --phase after --function-name "$FUNCTION_NAME" --region "$AWS_REGION" --output after.json
python3 compare.py before.json after.json | tee comparison.json
```

次を確認します。

- `fixed_conditions_match` と `result_checksum_match` が `true`
- `latency_improvement_percent` が正なら応答時間が短縮
- `cost_proxy_change_percent` が正なら、速度改善と引き換えに費用代理値は増加

実行基盤には揺らぎがあるため、1回の最速値ではなく中央値を比較します。差が小さい場合は、別の変更を重ねず、sample数を増やして再測定します。

## 想定と異なる場合

- `ResourceConflictException`: 関数更新の完了を待ち、`aws lambda get-function-configuration`で状態を確認します。
- `AccessDenied`: 表示された操作権限と`iam:PassRole`を確認します。権限やcredentialをREADMEへ貼り付けないでください。
- REPORT行を解析できない: Lambda roleに`AWSLambdaBasicExecutionRole`が付いているか、関数が成功したかを確認します。
- checksum不一致: before/afterの`iterations`とhandler codeが同じか確認し、比較を中止します。

## 5. cleanupと残存確認

```bash
bash cleanup.sh
```

`Lambda function 0 / log group 0 / IAM role 0`と表示されれば完了です。途中で失敗した場合も同じ`LAB_ID`とRegionを設定してcleanupを再実行してください。`before.json`、`after.json`、`comparison.json`はローカルの測定結果なので、不要なら削除できます。
