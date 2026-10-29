"""Part 2 (Policy): write the two Cedar policies for ClaimsGateway (looks up the Gateway ARN in your account).
Phần 2 (Policy): tạo 2 file Cedar policy cho ClaimsGateway (tự tìm ARN của Gateway trong tài khoản).

Run after the first `agentcore deploy` of Part 2 / Chạy sau lần deploy đầu tiên của phần 2:
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
    raise SystemExit("No gateway name contains 'ClaimsGateway'. Did you run 'agentcore deploy'?")
gw = ctl.get_gateway(gatewayIdentifier=match[0]["gatewayId"])
arn = gw["gatewayArn"]
print(f"Gateway: {gw['name']}\nARN    : {arn}")

out = pathlib.Path("policies")
out.mkdir(exist_ok=True)

(out / "allow_read_tools.cedar").write_text(f'''// Allow the agent to look up policies and claim status
permit(
  principal,
  action in [
    AgentCore::Action::"{TARGET}___get_policy",
    AgentCore::Action::"{TARGET}___get_claim_status"
  ],
  resource == AgentCore::Gateway::"{arn}"
);
''', encoding="utf-8")

(out / "allow_small_claims.cedar").write_text(f'''// Allow the agent to submit claims of {LIMIT_USD} USD or less.
// Larger claims match no policy and are denied by default (default deny).
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
