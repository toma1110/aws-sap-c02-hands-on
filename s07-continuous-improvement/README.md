# 観測結果から改善前後を比較する

同じ処理を同じ回数だけ実行し、観測結果から変更を一つ選びます。変更後も同じ条件で測定し、応答時間だけでなく費用への副作用と処理結果の同一性を確認します。

## 作成するもの

- AWS Lambda関数 1個（128 MBから開始）
- Lambda実行用IAM role 1個
- `deploy.sh`が作成するCloudWatch Logs log group 1個

既定Regionは東京（`ap-northeast-1`）です。すべての名前には `sap-c02-s07-` が付きます。

## 前提と権限

AWS CloudShellで実行します。AWS CLI、Python 3、zipを使用します。次の操作権限が必要です。

- `sts:GetCallerIdentity`
- Lambda関数の作成、取得、実行、設定変更、削除、tag付与・`lambda:ListTags`
- IAM roleの作成、取得、managed policyの付け外し、削除、`iam:PassRole`、`iam:TagRole`、`iam:ListRoleTags`
- 対象log groupの`logs:CreateLogGroup`、`logs:DescribeLogGroups`、`logs:TagResource`、`logs:ListTagsForResource`、`logs:DeleteLogGroup`

scriptのローカルtestは次で実行できます。

```bash
python3 -m unittest discover -s tests -v
```

演習用アカウントで実行し、本番環境と同じ名前を使わないでください。

## 料金

Lambdaのリクエスト数と実行時間、CloudWatch Logsの取り込み・保存に料金が発生し得ます。この演習はwarm-upを含めて18回実行します。検証時の東京RegionのLambda実行時間単価では、18回すべてが30秒・512 MBかかったと仮定しても、compute分は約0.0045 USD以下でした（リクエストとログ料金を除く）。単価は変わるため、実行前に[AWS Pricing Calculator](https://calculator.aws/)と利用中Regionの料金を確認してください。無料利用枠は保証せず、終了後は必ずcleanupします。

## 1. 準備

```bash
git clone https://github.com/toma1110/aws-sap-c02-hands-on.git
cd aws-sap-c02-hands-on/s07-continuous-improvement
export AWS_REGION=ap-northeast-1
export EXPECTED_ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
export LAB_ID="$(whoami)-$(date +%H%M%S)"
printf 'Account=%s Region=%s LAB_ID=%s\n' "$EXPECTED_ACCOUNT_ID" "$AWS_REGION" "$LAB_ID"
bash deploy.sh
```

この初期化直後に、`AWS_REGION`、`EXPECTED_ACCOUNT_ID`、`LAB_ID`の3値をcleanup完了まで控えておきます。CloudShellを再接続した場合は、最初に保存した値を次のplaceholderへ戻してから作業を再開します。

```bash
cd "$HOME/aws-sap-c02-hands-on/s07-continuous-improvement"
export AWS_REGION='<最初に保存したRegion>'
export EXPECTED_ACCOUNT_ID='<最初に保存した12桁のaccount ID>'
export LAB_ID='<最初に保存したLAB_ID>'
printf 'Account=%s Region=%s LAB_ID=%s\n' "$EXPECTED_ACCOUNT_ID" "$AWS_REGION" "$LAB_ID"
```

再接続時も必ず元の3値を再利用します。`export LAB_ID="$(whoami)-$(date +%H%M%S)"`を再実行すると別のresource名になるため、deploy後からcleanup完了までは実行しないでください。clone先を変えた場合だけ、`cd`のpathを実際のclone先へ置き換えます。

`EXPECTED_ACCOUNT_ID`にはSTSで取得した12桁のaccount IDを設定します。表示されたaccount、Region、`LAB_ID`を見て、演習用accountと東京Regionであることを確認してから`deploy.sh`を実行してください。`deploy.sh`は現在のaccountが`EXPECTED_ACCOUNT_ID`と一致しない場合に停止し、account、Region、関数名、role名を表示します。次の対応を確認してから測定へ進みます。

- account: この演習に使う予定のAWS account
- Region: `ap-northeast-1`
- Lambda関数とIAM role: `sap-c02-s07-`に、今回の`LAB_ID`を安全な名前へ変換した値を続けたもの
- log group: `/aws/lambda/<Lambda関数名>`

account、Region、名前のいずれかが予定と違う場合はその場で停止します。同名のLambda関数、IAM role、log groupが一つでも存在する場合も、既存resourceを上書きせず停止します。`LAB_ID`を変えて再実行するか、今回の演習で作成したresourceだと確認できる場合だけ同じ`LAB_ID`でcleanupしてください。

## 2. beforeを測定する

```bash
FUNCTION_NAME="sap-c02-s07-$(printf '%s' "$LAB_ID" | tr -cd '[:alnum:]-' | cut -c1-24)"
python3 measure.py --phase before --function-name "$FUNCTION_NAME" --region "$AWS_REGION" --output before.json
```

warm-up 1回を除外し、同じ25万回のSHA-256計算を8回測ります。確認済みの実行では、`before.json`の判断に必要な部分は次の値でした。実行基盤の揺らぎにより、時間の値は毎回同じにはなりません。

```json
{
  "fixed_conditions": {
    "iterations": 250000,
    "samples": 8,
    "warmup_excluded": 1
  },
  "summary": {
    "memory_mb": 128,
    "median_duration_ms": 2636.13,
    "median_billed_duration_ms": 2636.5,
    "max_memory_used_mb": 42,
    "median_cost_proxy_mb_ms": 337472.0
  }
}
```

見る場所は`fixed_conditions.iterations`、`fixed_conditions.samples`、`fixed_conditions.warmup_excluded`と、`summary`配下の5項目です。`summary.memory_mb`が128でない、固定条件が上の値と違う、または項目が欠けている場合は変更を適用せず停止します。`median_duration_ms`は実行時間の中央値、`median_billed_duration_ms`は課金対象時間の中央値、`max_memory_used_mb`は8回中の最大メモリ使用量です。`median_cost_proxy_mb_ms`はメモリMB×課金時間msの中央値であり、実際の請求額そのものではありません。

## 3. 変更を一つだけ適用する

```bash
bash improve.sh
```

`improve.sh`は現在のaccountが保存済みの`EXPECTED_ACCOUNT_ID`と一致し、同名関数の`HandsOn` tagがこの演習を示す場合だけ更新します。変更するのはLambdaのメモリを128 MBから512 MBへ増やすことだけです。Lambdaではメモリ量に応じてCPU能力も増えるため、CPU負荷の処理時間が短くなるかを検証します。

## 4. afterを同条件で測定する

```bash
python3 measure.py --phase after --function-name "$FUNCTION_NAME" --region "$AWS_REGION" --output after.json
python3 compare.py before.json after.json > comparison.json && cat comparison.json
```

確認済みの実行では、`comparison.json`は次の内容でした。

```json
{
  "fixed_conditions_match": true,
  "result_checksum_match": true,
  "change": "Lambda memory 128 MB -> 512 MB",
  "median_duration_ms": {
    "before": 2636.13,
    "after": 631.265
  },
  "latency_improvement_percent": 76.1,
  "median_cost_proxy_mb_ms": {
    "before": 337472.0,
    "after": 323328.0
  },
  "cost_proxy_change_percent": -4.2,
  "side_effect_to_check": "メモリ増加で応答時間は短縮しても、GB秒相当の費用が増える場合がある"
}
```

見る場所はすべて最上位です。次の順で判断します。

- `fixed_conditions_match`と`result_checksum_match`が両方`true`の場合だけ、改善率を解釈します。固定条件またはchecksumが不一致なら`compare.py`はエラーで停止するため、表示された不一致を直すまで次へ進みません。
- `latency_improvement_percent`が正なら応答時間は短縮、0なら変化なし、負なら悪化です。
- `cost_proxy_change_percent`が正なら費用代理値は増加、0なら変化なし、負なら減少です。速度改善と費用代理値を別々に評価します。

実行基盤には揺らぎがあるため、1回の最速値ではなく中央値を比較します。改善率や費用代理値の変化が小さい場合は結論を急がず、別の変更を重ねないままsample数を増やして再測定します。

## 想定と異なる場合

- `ResourceConflictException`: 関数更新の完了を待ち、`aws lambda get-function-configuration`で状態を確認します。
- `AccessDenied`: 表示された操作権限と`iam:PassRole`を確認します。権限やcredentialをREADMEへ貼り付けないでください。
- REPORT行を解析できない: Lambda roleに`AWSLambdaBasicExecutionRole`が付いているか、関数が成功したかを確認します。
- 固定条件の不一致: `before.json`と`after.json`の`fixed_conditions`、関数名、Regionを確認し、同じ条件で取り直すまで比較を中止します。
- checksum不一致: before/afterの`iterations`と`handler.py`が同じか確認し、比較を中止します。異なる処理結果の改善率は採用しません。

## 5. cleanupと残存確認

```bash
bash cleanup.sh
```

確認済みのcleanup出力は次の3行です。

```text
cleanup residual: lambda=0
cleanup residual: log_group=0
cleanup residual: iam_role=0
```

`lambda`、`log_group`、`iam_role`がすべて0なら完了です。1つでも0以外なら、同じ`LAB_ID`と`AWS_REGION`を維持し、表示された名前が今回の演習resourceかを確認してからcleanupを再実行します。ownership tagが一致しないlog groupやresourceは削除せず停止するため、別のresourceを手動削除して先へ進まないでください。`before.json`、`after.json`、`comparison.json`はCloudShell内の測定結果なので、不要ならcleanup確認後に削除できます。
