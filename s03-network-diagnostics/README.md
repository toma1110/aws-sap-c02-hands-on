# ルート・名前解決・到達性から通信障害を絞る

このハンズオンでは、通信障害を次の順で診断します。

1. ルート
2. 名前解決
3. セキュリティ制御
4. 到達性

前半は固定テストデータを使うため、AWS resourceを作成しません。後半は課金部品を含まない隔離VPCのコントロールプレーン設定だけを観察します。実際のpacket疎通やDNS queryの成功は証明しません。

## 所要時間

約18分です。準備2分、固定データ診断8分、AWS設定観察5分、cleanupと残存確認3分を目安にします。

## 準備

### 既定手順: AWS CloudShell

AWS ConsoleでRegionを`us-east-1`に切り替えてCloudShellを開き、次を実行します。

```bash
git clone https://github.com/toma1110/aws-sap-c02-hands-on.git
cd aws-sap-c02-hands-on/s03-network-diagnostics
python3 --version
```

検証済み出力例です。Pythonのpatch versionは環境により異なります。

```text
Cloning into 'aws-sap-c02-hands-on'...
Python 3.11.x
```

見る値は最後の`Python 3.11.x`です。3.11以降なら次へ進みます。clone、directory移動、version確認のどれかが失敗した場合は、修正するまでAWS resourceを作成しません。追加packageは不要です。

AWS操作のpublic entrypointは[shell wrapper](scripts/aws-control-plane.sh)です。wrapperは同じdirectoryの[Python source](scripts/aws_control_plane.py)を`PYTHON_SOURCE`として解決し、そのexact fileだけを`exec`します。Python sourceが欠けている場合は終了code 2で停止します。

Python 3.11以降があれば、前半の診断とunit testだけはローカルでも実行できます。AWS credentialをローカルへ追加する必要はありません。AWS設定の観察とcleanupはCloudShellで行います。

### 必要権限

- `sts:GetCallerIdentity`
- `ec2:CreateVpc`、`ec2:ModifyVpcAttribute`、`ec2:CreateSubnet`
- `ec2:CreateRouteTable`、`ec2:AssociateRouteTable`
- `ec2:CreateSecurityGroup`、`ec2:CreateTags`
- `ec2:DescribeAvailabilityZones`、`ec2:DescribeVpcs`、`ec2:DescribeVpcAttribute`
- `ec2:DescribeSubnets`、`ec2:DescribeRouteTables`、`ec2:DescribeSecurityGroups`
- `ec2:DisassociateRouteTable`、`ec2:DeleteRouteTable`、`ec2:DeleteSecurityGroup`、`ec2:DeleteSubnet`、`ec2:DeleteVpc`

## 料金と影響範囲

VPC、subnet、custom route table、security groupを各1個だけ作ります。EC2 instance、NAT Gateway、VPC endpoint、Route 53 private hosted zone、Reachability Analyzer、Internet Gatewayは作りません。既定構成のコントロールプレーンresource自体には時間課金を見込んでいません。

実行前に[AWS公式のAmazon VPC料金](https://aws.amazon.com/vpc/pricing/)を確認してください。手順を変えて課金対象の接続や分析を加えた場合は別途料金が発生します。

VPCは`10.63.0.0/24`、subnetは`10.63.0.0/28`です。他VPCやInternet Gatewayへの接続はなく、既存networkのroute、DNS、security groupは変更しません。

## 1. 固定データで診断する

### 正常系

```bash
python3 diagnose.py fixtures/scenarios.json healthy
```

検証済み出力です。

```json
{
  "dataset_version": "network-diagnostics-v1",
  "scenario": "healthy",
  "decision": "HEALTHY",
  "checked_stages": ["route", "dns", "security", "reachability"],
  "evidence": [
    {"stage": "route", "passed": true, "detail": "宛先CIDRに一致するルートと転送先がある"},
    {"stage": "dns", "passed": true, "detail": "期待するプライベート名が想定したIPアドレスへ解決される"},
    {"stage": "security", "passed": true, "detail": "セキュリティグループとネットワークACLが確認対象の通信を許可している"},
    {"stage": "reachability", "passed": true, "detail": "固定した到達性の観測結果が宛先まで到達している"}
  ]
}
```

見るfield pathは`.decision`、`.checked_stages`、`.evidence[*].passed`です。`HEALTHY`、4段階、すべて`true`なら次へ進みます。一つでも違う場合はfixtureと実行directoryを確認し、AWS側は変更しません。

### ルート不足

```bash
python3 diagnose.py fixtures/scenarios.json route-missing
```

検証済み出力です。

```json
{
  "dataset_version": "network-diagnostics-v1",
  "scenario": "route-missing",
  "decision": "ROUTE",
  "checked_stages": ["route"],
  "evidence": [
    {"stage": "route", "passed": false, "detail": "宛先CIDRに一致するルートがない"}
  ]
}
```

見るfield pathは`.decision`と`.evidence[0]`です。`ROUTE`かつ`stage=route`、`passed=false`なら次へ進みます。それ以外なら停止します。

### DNS転送不足

```bash
python3 diagnose.py fixtures/scenarios.json dns-forwarding-missing
```

検証済み出力です。

```json
{
  "dataset_version": "network-diagnostics-v1",
  "scenario": "dns-forwarding-missing",
  "decision": "DNS",
  "checked_stages": ["route", "dns"],
  "evidence": [
    {"stage": "route", "passed": true, "detail": "宛先CIDRに一致するルートと転送先がある"},
    {"stage": "dns", "passed": false, "detail": "オンプレミス側のドメイン名に一致するDNS転送ルールがない"}
  ]
}
```

見るfield pathは`.decision`と`.evidence[1]`です。`DNS`かつ`stage=dns`、`passed=false`なら次へ進みます。それ以外なら停止します。

### セキュリティ制御の拒否

```bash
python3 diagnose.py fixtures/scenarios.json security-blocked
```

検証済み出力です。

```json
{
  "dataset_version": "network-diagnostics-v1",
  "scenario": "security-blocked",
  "decision": "SECURITY",
  "checked_stages": ["route", "dns", "security"],
  "evidence": [
    {"stage": "route", "passed": true, "detail": "宛先CIDRに一致するルートと転送先がある"},
    {"stage": "dns", "passed": true, "detail": "期待するプライベート名が想定したIPアドレスへ解決される"},
    {"stage": "security", "passed": false, "detail": "宛先のセキュリティグループが確認対象のポートを許可していない"}
  ]
}
```

見るfield pathは`.decision`と`.evidence[2]`です。`SECURITY`かつ`stage=security`、`passed=false`なら次へ進みます。それ以外なら停止します。

### 到達性の失敗

```bash
python3 diagnose.py fixtures/scenarios.json reachability-blocked
```

検証済み出力です。

```json
{
  "dataset_version": "network-diagnostics-v1",
  "scenario": "reachability-blocked",
  "decision": "REACHABILITY",
  "checked_stages": ["route", "dns", "security", "reachability"],
  "evidence": [
    {"stage": "route", "passed": true, "detail": "宛先CIDRに一致するルートと転送先がある"},
    {"stage": "dns", "passed": true, "detail": "期待するプライベート名が想定したIPアドレスへ解決される"},
    {"stage": "security", "passed": true, "detail": "セキュリティグループとネットワークACLが確認対象の通信を許可している"},
    {"stage": "reachability", "passed": false, "detail": "固定した経路の中継先が利用できないと観測された"}
  ]
}
```

見るfield pathは`.decision`と`.evidence[3]`です。`REACHABILITY`かつ`stage=reachability`、`passed=false`なら固定データの診断は完了です。終了code 2と`INVALID_INPUT`が出た場合は、欠けた入力を推測せずfixtureを確認します。

## 2. AWS設定を観察する

### accountとRegionを固定する

現在ログイン中のaccount IDをAWS STSから取得します。IDを手入力しません。

```bash
export AWS_REGION="us-east-1"
export EXPECTED_ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
printf 'Account=%s Region=%s\n' "$EXPECTED_ACCOUNT_ID" "$AWS_REGION"
```

実値を伏せた検証済み出力例です。

```text
Account=111122223333 Region=us-east-1
```

見る値はSTS応答の`Account`を入れた`EXPECTED_ACCOUNT_ID`と`AWS_REGION`です。account IDが12桁でRegionが`us-east-1`なら次へ進みます。空、`None`、12桁以外、別Regionならresourceを作成しません。wrapperも実accountとの不一致を検出すると終了code 2で停止します。

### 作成する

```bash
bash scripts/aws-control-plane.sh create
```

IDとaccountを伏せた検証済み出力例です。

```json
{
  "created": {
    "schema_version": 1,
    "name": "sapc02-s03-network-diag",
    "account_id": "111122223333",
    "region": "us-east-1",
    "vpc_id": "vpc-<redacted>",
    "subnet_ids": ["subnet-<redacted>"],
    "route_table_id": "rtb-<redacted>",
    "association_id": "rtbassoc-<redacted>",
    "security_group_id": "sg-<redacted>"
  }
}
```

見るfield pathは`.created.account_id`、`.created.region`、`.created.vpc_id`、`.created.subnet_ids[0]`、`.created.route_table_id`、`.created.association_id`、`.created.security_group_id`です。accountとRegionが一致し、IDがすべて空でなければ観察へ進みます。終了code 2、`error`、ID欠落、collisionの場合は再実行せず、`.s03-state/aws-state.json`を保持してexact IDを確認します。

### 観察する

```bash
bash scripts/aws-control-plane.sh observe
```

既存のAWS検証結果から再現した、IDを含まない検証済み出力です。

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

同時に`.s03-state/aws-observation.json`へ保存されるraw JSONの、IDを伏せた検証済み抜粋です。

```json
{
  "vpc": {"Vpcs": [{"CidrBlock": "10.63.0.0/24", "State": "available", "VpcId": "vpc-<redacted>"}]},
  "dns_support": {"EnableDnsSupport": {"Value": true}},
  "dns_hostnames": {"EnableDnsHostnames": {"Value": true}},
  "subnet": {"Subnets": [{"CidrBlock": "10.63.0.0/28", "State": "available", "SubnetId": "subnet-<redacted>"}]},
  "route_table": {"RouteTables": [{"Routes": [{"DestinationCidrBlock": "10.63.0.0/24", "GatewayId": "local", "State": "active"}]}]},
  "security_group": {"SecurityGroups": [{"IpPermissions": []}]}
}
```

見るfield pathは`vpc.Vpcs[0].CidrBlock`、`subnet.Subnets[0].CidrBlock`、`dns_support.EnableDnsSupport.Value`、`dns_hostnames.EnableDnsHostnames.Value`、`route_table.RouteTables[0].Routes`、`security_group.SecurityGroups[0].IpPermissions`です。CIDRが`10.63.0.0/24`と`10.63.0.0/28`、DNSの2値が`true`、routeが`10.63.0.0/24 → local / active`の1件、inboundが空ならcleanupへ進みます。一つでも違う場合は設定変更で合わせず、state fileを保持してcleanupを優先します。

## 3. cleanupする

作成時のstateに記録したexact IDだけを削除します。tag prefixによる一括削除は行いません。

```bash
bash scripts/aws-control-plane.sh cleanup
```

検証済み出力です。

```json
{
  "cleanup_requests_completed": true
}
```

見るfield pathは`.cleanup_requests_completed`です。`true`は削除requestの完了であり、残存0の証明ではありません。終了code 0と`true`を確認したら必ず`residual`へ進みます。終了code 2または`error`ならstate fileを削除せず、exact IDを確認して同じcleanupを再開します。

```bash
bash scripts/aws-control-plane.sh residual
```

IDを伏せた検証済み出力です。

```json
{
  "remaining": []
}
```

見るfield pathは`.remaining`です。空配列かつ終了code 0ならcleanup完了で、scriptが`.s03-state`を削除します。要素が残る場合は終了code 1となるため完了扱いにせず、表示されたexact IDだけを確認してcleanupを再実行します。state fileがない場合は残存0を推測せず、終了code 2で停止します。

削除順序はroute table association、custom route table、security group、subnet、VPCです。削除済みresourceは飛ばして残りを処理します。既存resourceや名前の似たresourceは削除しません。

## テスト

```bash
python3 -m unittest discover -s tests -v
```

検証済み出力の末尾です。

```text
Ran 16 tests

OK
```

見る値は`Ran 16 tests`、`OK`、終了code 0です。そろえば完了です。`FAILED`、`ERROR`、終了code非0なら公開やAWS操作へ進みません。診断の正常・故障・fail-closedに加え、account/Region不一致、tag改変、collision、部分cleanup、残存確認、CIDR、wrapperとPython sourceのexact対応も検査します。
