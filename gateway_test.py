"""Goi thang tool tren ClaimsGateway (khong qua LLM) de thay Policy quyet dinh Allow / Deny.
    uv run --with boto3 gateway_test.py
"""
import json, urllib.request, urllib.error
import boto3
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

REGION = "us-east-1"
GATEWAY_HINT = "claimsgateway"
TARGET = "ClaimsTools"

session = boto3.Session(region_name=REGION)
ctl = session.client("bedrock-agentcore-control")
match = [g for g in ctl.list_gateways().get("items", []) if GATEWAY_HINT in g["name"].lower()]
if not match:
    raise SystemExit("Khong tim thay ClaimsGateway. Da 'agentcore deploy' chua?")
url = ctl.get_gateway(gatewayIdentifier=match[0]["gatewayId"])["gatewayUrl"].rstrip("/")
if not url.endswith("/mcp"):
    url += "/mcp"
creds = session.get_credentials().get_frozen_credentials()


def call(tool, args, rid):
    body = json.dumps({"jsonrpc": "2.0", "id": rid, "method": "tools/call",
                       "params": {"name": f"{TARGET}___{tool}", "arguments": args}})
    req = AWSRequest(method="POST", url=url, data=body,
                     headers={"Content-Type": "application/json",
                              "Accept": "application/json, text/event-stream"})
    SigV4Auth(creds, "bedrock-agentcore", REGION).add_auth(req)
    http = urllib.request.Request(url, data=body.encode(), headers=dict(req.headers.items()), method="POST")
    try:
        with urllib.request.urlopen(http, timeout=30) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")


CASES = [
    ("get_policy", {"policy_id": "POL-1001"}, "Tra cuu hop dong -> mong doi ALLOW"),
    ("submit_claim", {"policy_id": "POL-1002", "amount_usd": 1500, "description": "Pipe burst"},
     "Claim 1500 USD -> mong doi ALLOW"),
    ("submit_claim", {"policy_id": "POL-1001", "amount_usd": 50000, "description": "Car destroyed"},
     "Claim 50000 USD -> mong doi DENY"),
    ("submit_claim", {"policy_id": "POL-1003", "amount_usd": 500, "description": "Broken window"},
     "Claim 500 USD tren POL-1003 -> mong doi DENY (forbid thang permit)"),
]

print(f"Gateway URL: {url}\n")
for i, (tool, args, label) in enumerate(CASES, 1):
    status, text = call(tool, args, i)
    print(f"=== {label}\n  tool : {tool} {json.dumps(args)}\n  HTTP : {status}\n  body : {text[:400]}\n")
