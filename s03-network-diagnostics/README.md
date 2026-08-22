# ルート・名前解決・到達性から通信障害を絞る

アプリケーションから接続できないとき、最初からすべての設定を調べると原因を見失いがちです。このハンズオンでは、固定データを使って次の順に確認し、最初に問題が見つかった場所へ調査を絞ります。

1. 宛先へ向かうルートがあるか
2. 接続先の名前をIPアドレスへ解決できるか
3. セキュリティグループとネットワークACLが通信を許可しているか
4. 経路の途中から宛先まで到達できるか

固定データの演習だけならAWSリソースは作成せず、約10分で終わります。希望する場合は、その後に隔離したVPCを作り、AWS上のルートやDNS設定を約8分で観察できます。

## 準備

AWS CloudShellを開き、次のコマンドで教材を取得します。Python 3.11以降が必要ですが、追加パッケージはありません。

```bash
git clone https://github.com/toma1110/aws-sap-c02-hands-on.git
cd aws-sap-c02-hands-on/s03-network-diagnostics
python3 --version
```

`Python 3.11.x`のように表示されたら準備完了です。固定データの診断ではAWSへアクセスしないため、AWSの認証情報は使いません。

## 固定データで診断順序を体験する

最初に、すべての確認を通過するデータを診断します。

```bash
python3 diagnose.py fixtures/scenarios.json healthy
```

結果はJSONで表示されます。主に次の3点を読みます。

- `decision`: 最初に問題が見つかった場所。問題がなければ`HEALTHY`
- `checked_stages`: 実際に確認した項目と順序
- `evidence`: 各項目で分かったこと

正常なデータでは、ルート、DNS、セキュリティ制御、到達性の4項目が順番に確認され、`decision`は`HEALTHY`になります。

次に、問題の場所が異なる4つのデータを診断します。

```bash
python3 diagnose.py fixtures/scenarios.json route-missing
python3 diagnose.py fixtures/scenarios.json dns-forwarding-missing
python3 diagnose.py fixtures/scenarios.json security-blocked
python3 diagnose.py fixtures/scenarios.json reachability-blocked
```

表示された`decision`と`checked_stages`を比べてください。

| データ | 最初に分かる問題 | そこまでに確認する項目 |
| --- | --- | --- |
| `route-missing` | 宛先CIDRに一致するルートがない | ルート |
| `dns-forwarding-missing` | オンプレミスのドメインに合うDNS転送ルールがない | ルート → DNS |
| `security-blocked` | 宛先のセキュリティグループがポートを許可していない | ルート → DNS → セキュリティ制御 |
| `reachability-blocked` | 経路の中継先を利用できない | ルート → DNS → セキュリティ制御 → 到達性 |

前の項目に問題があれば、後ろの項目を先に調べても原因は確定できません。たとえばDNSの問題を調べる前に、宛先へ向かうルートがあることを確認します。この順序を実際の障害調査にも使えます。

`INVALID_INPUT`と表示された場合は、コマンドを実行したディレクトリ、データのファイル名、シナリオ名を確認してください。入力が不足している状態でAWS設定を推測して変更する必要はありません。

## 任意: AWS上の設定を観察する

ここからはVPC、サブネット、カスタムルートテーブル、セキュリティグループを1つずつ作ります。EC2インスタンス、NAT Gateway、VPCエンドポイント、Route 53プライベートホストゾーン、Reachability Analyzer、Internet Gatewayは作成しません。他のVPCへ接続せず、既存ネットワークの設定も変更しません。

ここで作成するリソース自体に時間料金はありませんが、AWSの料金体系は変更されることがあります。実行前に[Amazon VPCの料金](https://aws.amazon.com/vpc/pricing/)を確認してください。手順にない接続や分析を追加すると、別途料金が発生する場合があります。

### 必要な権限

実行するIAMユーザーまたはロールには、次の権限が必要です。

- 本人確認: `sts:GetCallerIdentity`
- 作成と設定: `ec2:CreateVpc`、`ec2:ModifyVpcAttribute`、`ec2:CreateSubnet`、`ec2:CreateRouteTable`、`ec2:AssociateRouteTable`、`ec2:CreateSecurityGroup`、`ec2:CreateTags`
- 観察: `ec2:DescribeAvailabilityZones`、`ec2:DescribeVpcs`、`ec2:DescribeVpcAttribute`、`ec2:DescribeSubnets`、`ec2:DescribeRouteTables`、`ec2:DescribeSecurityGroups`
- 後片付け: `ec2:DisassociateRouteTable`、`ec2:DeleteRouteTable`、`ec2:DeleteSecurityGroup`、`ec2:DeleteSubnet`、`ec2:DeleteVpc`

### 1. AWSアカウントとリージョンを確認する

CloudShellで次を実行します。

```bash
export AWS_REGION="us-east-1"
export EXPECTED_ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
printf 'Account=%s Region=%s\n' "$EXPECTED_ACCOUNT_ID" "$AWS_REGION"
```

表示された12桁のアカウントIDが演習に使うアカウントと一致し、リージョンが`us-east-1`であることを目で確認してください。一致しない場合は、ここで操作を止めて正しいアカウントへログインし直します。

この演習で使うCIDRは、VPCが`10.63.0.0/24`、サブネットが`10.63.0.0/28`です。作成用スクリプトも、実際のアカウントやリージョンがここで指定した値と違う場合は処理を止めます。

### 2. 観察用リソースを作る

```bash
bash scripts/aws-control-plane.sh create
```

作成したVPC、サブネット、ルートテーブル、セキュリティグループのIDが表示されます。これらのIDは`.s03-state/aws-state.json`にも保存され、後片付けの対象を特定するために使われます。

エラーになった場合は、同じコマンドを繰り返す前にメッセージを確認してください。途中まで作成されている可能性があるため、`.s03-state/aws-state.json`は削除せず、後述の後片付けを実行します。

### 3. ルートとDNS設定を見る

```bash
bash scripts/aws-control-plane.sh observe
```

出力は次のようになります。リソースIDを含む詳細は`.s03-state/aws-observation.json`へ保存されます。

```json
{
  "boundary": "control-plane configuration only; no packet or DNS query executed",
  "vpc_cidr": "10.63.0.0/24",
  "subnet_cidr": "10.63.0.0/28",
  "dns_support": true,
  "dns_hostnames": true,
  "routes": [
    {"destination": "10.63.0.0/24", "gateway": "local", "state": "active"}
  ],
  "inbound_rule_count": 0
}
```

この結果から、VPCとサブネットのCIDR、VPCのDNS機能が有効であること、ローカルルートが有効であること、作成したセキュリティグループに受信ルールがないことを確認できます。この観察はAWSの設定情報を読んだものであり、実際のパケット通信やDNSクエリを実行した結果ではありません。

## 後片付け

AWS上の設定を観察した場合は、演習を終える前に必ず実行します。

```bash
bash scripts/aws-control-plane.sh cleanup
bash scripts/aws-control-plane.sh residual
```

スクリプトは、作成時に保存したIDを使い、ルートテーブルの関連付け、カスタムルートテーブル、セキュリティグループ、サブネット、VPCの順に削除します。名前が似ているリソースや既存リソースは削除しません。

最後のコマンドで次のように表示されれば、演習で作成したリソースは残っていません。

```json
{"remaining": []}
```

リソースが残っている場合は、そのIDが表示されます。少し待ってから`cleanup`と`residual`をもう一度実行してください。エラーになった場合も状態ファイルは手動で削除しないでください。削除すると、スクリプトが安全に対象を特定できなくなります。

## 困ったとき

- `python3: command not found`またはPython 3.10以前が表示される: AWS CloudShellでやり直すか、Python 3.11以降を用意します。
- `unknown scenario`が表示される: 上記に記載したシナリオ名と、現在のディレクトリを確認します。
- `Account mismatch`または`State Region does not match`が表示される: リソースを変更せず、ログイン中のアカウントと`AWS_REGION`を確認します。
- `State already exists`または`Tagged resource collision`が表示される: 重複作成はせず、保存されているIDを確認して後片付けへ進みます。
- `cleanup`でエラーになる: `.s03-state/aws-state.json`を残したまま、必要権限と表示されたリソースIDを確認してから同じコマンドを再実行します。
- `residual`でリソースが表示される: そのIDだけが演習で作成したものか確認し、`cleanup`を再実行します。AWS Consoleから名前だけで一括削除しないでください。

## 実装のテスト

スクリプトを変更した場合や、動作を自分で確認したい場合は次を実行します。

```bash
python3 -m unittest discover -s tests -v
```

`Ran 16 tests`に続いて`OK`と表示されれば、診断処理とAWS操作の安全機能が期待どおりに動いています。
