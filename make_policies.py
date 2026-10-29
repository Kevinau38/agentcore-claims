"""Tao 2 file Cedar policy cho ClaimsGateway (tu tim gateway ARN trong tai khoan).
Chay sau lan 'agentcore deploy' dau tien cua phan 2:
    uv run --with boto3 make_policies.py
"""
import pathlib
import boto3

REGION = "us-east-1"
GATEWAY_HINT = "claimsgateway"
TARGET = "ClaimsTools"
LIMIT_USD = 10000

ctl = boto3.client("bedrock-agentcore-control", region_name=REGION)
items = ctl.list_gateways().get("items", [])
match = [g for g in items if GATEWAY_HINT in g["name"].lower()]
if not match:
    raise SystemExit("Khong tim thay gateway nao ten chua 'ClaimsGateway'. Da 'agentcore deploy' chua?")
gw = ctl.get_gateway(gatewayIdentifier=match[0]["gatewayId"])
arn = gw["gatewayArn"]
print(f"Gateway: {gw['name']}\nARN    : {arn}")

out = pathlib.Path("policies")
out.mkdir(exist_ok=True)

(out / "allow_read_tools.cedar").write_text(f'''// Cho phep agent tra cuu hop dong va trang thai claim
permit(
  principal,
  action in [
    AgentCore::Action::"{TARGET}___get_policy",
    AgentCore::Action::"{TARGET}___get_claim_status"
  ],
  resource == AgentCore::Gateway::"{arn}"
);
''', encoding="utf-8")

(out / "allow_small_claims.cedar").write_text(f'''// Chi cho phep agent tu nop claim tu {LIMIT_USD} USD tro xuong.
// Claim lon hon khong khop policy nao -> mac dinh bi tu choi (default deny).
permit(
  principal,
  action == AgentCore::Action::"{TARGET}___submit_claim",
  resource == AgentCore::Gateway::"{arn}"
)
when {{
  context.input.amount_usd <= {LIMIT_USD}
}};
''', encoding="utf-8")

print("\n[OK] policies/allow_read_tools.cedar")
print("[OK] policies/allow_small_claims.cedar")
