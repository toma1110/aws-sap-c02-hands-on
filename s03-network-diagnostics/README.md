# ルート・名前解決・到達性から通信障害を絞る

このハンズオンでは、通信できないという症状を見たときに、サービスを無作為に変更せず、次の順番で証拠を確認します。

1. ルート
2. 名前解決
3. セキュリティ制御
4. 到達性

前半は固定テストデータを使うため、AWSリソースを作成せずに診断順序を練習できます。後半のAWS確認は、課金部品を含まない隔離されたVPCのコントロールプレーン設定だけを観察します。実際のパケット疎通やDNS問い合わせを成功させた証拠にはしません。

## 所要時間

約18分です。

- 準備: 2分
- 固定テストデータによる診断: 8分
- AWS設定の観察: 5分
- cleanupと残存確認: 3分

## 準備

### 既定手順: AWS CloudShell

AWS ConsoleでRegionを`us-east-1`に切り替えてCloudShellを開きます。CloudShell上でPublic repositoryを取得し、以降の固定テストデータ診断、AWS設定の観察、cleanupを同じdirectoryから続けます。

```bash
git clone https://github.com/toma1110/aws-sap-c02-hands-on.git
cd aws-sap-c02-hands-on/s03-network-diagnostics
python3 --version
```

追加packageは不要です。

### 任意の代替: ローカルで前半だけ実行

Python 3.11以降があれば、固定テストデータによる診断とunit testはローカルでも実行できます。AWS credentialをローカルへ追加する必要はありません。AWS設定の観察とcleanupは、既定手順どおり同じrepositoryを取得したCloudShellで行います。

### AWS権限

- 自分のAWS account IDを確認できること
- 次のAmazon EC2権限
  - `ec2:CreateVpc`、`ec2:ModifyVpcAttribute`、`ec2:CreateSubnet`
  - `ec2:CreateRouteTable`、`ec2:AssociateRouteTable`
  - `ec2:CreateSecurityGroup`、`ec2:CreateTags`
  - `ec2:DescribeAvailabilityZones`、`ec2:DescribeVpcs`、`ec2:DescribeVpcAttribute`
  - `ec2:DescribeSubnets`、`ec2:DescribeRouteTables`、`ec2:DescribeSecurityGroups`
  - `ec2:DisassociateRouteTable`、`ec2:DeleteRouteTable`、`ec2:DeleteSecurityGroup`、`ec2:DeleteSubnet`、`ec2:DeleteVpc`
  - `sts:GetCallerIdentity`

## 料金と影響範囲

既定のAWS手順は、VPC、subnet各1個、route table、security groupだけを作ります。EC2 instance、NAT Gateway、VPC endpoint、Route 53 private hosted zone、Reachability Analyzer、Internet Gatewayは作成しません。これらのコントロールプレーンresource自体には時間課金を見込んでいません。

実行前に[AWS公式のAmazon VPC料金](https://aws.amazon.com/vpc/pricing/)を確認してください。手順を変更して課金対象の接続や分析を追加した場合は、その料金が別途発生します。

作成するVPCは`10.63.0.0/24`で、Internet Gatewayや他VPCへの接続はありません。既存ネットワークのroute、DNS、security groupは変更しません。

## 1. 固定テストデータで症状を固定する

最初に正常系を確認します。

```bash
python3 diagnose.py fixtures/scenarios.json healthy
```

期待結果は`decision`が`HEALTHY`、`checked_stages`が4段階すべてを含むJSONです。

次に4種類の障害を一つずつ確認します。

```bash
python3 diagnose.py fixtures/scenarios.json route-missing
python3 diagnose.py fixtures/scenarios.json dns-forwarding-missing
python3 diagnose.py fixtures/scenarios.json security-blocked
python3 diagnose.py fixtures/scenarios.json reachability-blocked
```

期待する判断は順に`ROUTE`、`DNS`、`SECURITY`、`REACHABILITY`です。診断は最初に不一致が見つかった段階で止まります。たとえばrouteが不足している状態でsecurity groupを先に変更しないことが重要です。

想定と異なる場合は、JSONの`evidence`で、期待値と観測値のどちらが異なるかを確認します。入力項目が欠けている場合は推測せず、終了code 2で`INVALID_INPUT`になります。

## 2. AWSの設定を観察する

同じCloudShell directoryで、account IDを明示して実行します。

```bash
export EXPECTED_ACCOUNT_ID="123456789012"
bash scripts/aws-control-plane.sh create
bash scripts/aws-control-plane.sh observe
```

`123456789012`は自分のaccount IDへ置き換えてください。scriptは実際のaccountと一致しない場合、resourceを作らず停止します。

作成後のIDは`.s03-state/aws-state.json`へ保存されます。観察結果は`.s03-state/aws-observation.json`です。このdirectoryはGit管理対象外です。

確認する証拠は次のとおりです。

- custom route tableにはVPC内の`local` routeだけがある
- VPCのDNS supportとDNS hostnamesが有効である
- security groupのinbound ruleは空である
- `create`処理がInternet Gatewayや別VPCへの接続を作成していない

この観察から分かるのは設定状態です。実際の通信成功、名前解決成功、アプリケーション応答は証明していません。実通信の故障分岐は前半の固定テストデータで安全に練習します。

## 3. cleanupする

cleanupは作成時に記録したexact IDだけを対象にします。tag prefixによる一括削除は行いません。

```bash
bash scripts/aws-control-plane.sh cleanup
bash scripts/aws-control-plane.sh residual
```

削除順序はroute table association、custom route table、security group、subnet、VPCです。期待結果は`remaining`が空配列です。残存0を確認したときだけ、scriptが`.s03-state`を削除します。再実行時は、すでに削除済みのresourceを飛ばして残りを処理します。

cleanupが失敗した場合は`.s03-state/aws-state.json`を削除せず、表示されたexact IDをAWS Consoleで確認してください。state fileがない場合、scriptは残存0を自己判断せず停止します。依存resourceがある場合は、今回作成したIDと一致することを確認してから削除します。既存resourceや名前の似たresourceは削除しません。

## テスト

```bash
python3 -m unittest discover -s tests -v
```

正常系、4つの故障箇所、未知scenario、項目欠落のfail-closed動作を確認します。さらに、account/Region不一致、改変されたtag、state消失時の重複候補、部分cleanupの再実行、残存確認など、AWS resourceを誤って作成・削除しないための安全テストも実行します。
