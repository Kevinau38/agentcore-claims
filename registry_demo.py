"""Part 3 (AWS Agent Registry): publish Claims Tools (MCP) and Claims Agent (Custom), approve, then search.
Phần 3 (AWS Agent Registry): đăng ký Claims Tools (MCP) và Claims Agent (Custom), duyệt, rồi tìm kiếm.

Usage, from the ClaimsDemo folder / Cách dùng, trong thư mục ClaimsDemo:
    uv run --with boto3 registry_demo.py create-registry     # Admin: create the registry, manual approval
    uv run --with boto3 registry_demo.py publish             # Publisher: create 2 records, submit for approval
    uv run --with boto3 registry_demo.py search "insurance claim tools"   # Consumer: search (nothing found yet)
    uv run --with boto3 registry_demo.py approve             # Admin: approve pending records
    uv run --with boto3 registry_demo.py search "insurance claim tools"   # Consumer: records found
    uv run --with boto3 registry_demo.py status              # Show status
    uv run --with boto3 registry_demo.py cleanup             # Delete the records and the registry
"""
import json, sys, time
import boto3
from botocore.exceptions import ClientError

REGION = "us-east-1"
REGISTRY_NAME = "claims-org-registry"
GATEWAY_HINT = "claimsgateway"
RUNTIME_HINT = "claimsagent"

session = boto3.Session(region_name=REGION)
ctl = session.client("agent-registry-control")      # Admin + Publisher (control plane)
disc = session.client("agent-registry")              # Consumer (search / discovery)
core = session.client("bedrock-agentcore-control")  # to read the Gateway URL and Runtime ARN


# ---------------------------------------------------------------- helpers
def find_registry():
    token = None
    while True:
        kw = {"nextToken": token} if token else {}
        resp = ctl.list_registries(**kw)
        for r in resp.get("registries", []):
            if r.get("name") == REGISTRY_NAME:
                return r
        token = resp.get("nextToken")
        if not token:
            return None


def registry_or_exit():
    r = find_registry()
    if not r:
        sys.exit(f"Registry '{REGISTRY_NAME}' not found. Run: registry_demo.py create-registry")
    return r


def wait_registry_ready(registry_id, timeout=300):
    t0 = time.time()
    while True:
        g = ctl.get_registry(registryId=registry_id)
        st = g["status"]
        print(f"  registry status: {st}")
        if st == "READY":
            return g
        if st.endswith("FAILED"):
            sys.exit(f"Registry failed: {g.get('statusReason')}")
        if time.time() - t0 > timeout:
            sys.exit("Timed out waiting for the registry to be READY")
        time.sleep(10)


def wait_record(registry_id, record_id, targets=("DRAFT",), timeout=300):
    t0 = time.time()
    while True:
        g = ctl.get_registry_record(registryId=registry_id, recordId=record_id)
        st = g["status"]
        if st in targets or st.endswith("FAILED"):
            return g
        if time.time() - t0 > timeout:
            sys.exit(f"Timed out waiting for record {record_id}")
        time.sleep(5)


def list_records(registry_id):
    out, token = [], None
    while True:
        kw = {"registryId": registry_id}
        if token:
            kw["nextToken"] = token
        resp = ctl.list_registry_records(**kw)
        out += resp.get("registryRecords", [])
        token = resp.get("nextToken")
        if not token:
            return out


def gateway_url():
    items = core.list_gateways().get("items", [])
    m = [g for g in items if GATEWAY_HINT in g["name"].lower()]
    if not m:
        sys.exit("ClaimsGateway (Part 2) not found. Did you deploy it?")
    url = core.get_gateway(gatewayIdentifier=m[0]["gatewayId"])["gatewayUrl"].rstrip("/")
    return url if url.endswith("/mcp") else url + "/mcp"


def runtime_arn():
    for rt in core.list_agent_runtimes().get("agentRuntimes", []):
        if RUNTIME_HINT in rt["agentRuntimeName"].lower():
            return rt["agentRuntimeArn"]
    return "unknown"


# ---------------------------------------------------------------- record content
TOOLS = [
    {"name": "get_policy", "description": "Look up an insurance policy by its ID (format POL-xxxx).",
     "inputSchema": {"type": "object", "properties": {"policy_id": {"type": "string"}}, "required": ["policy_id"]}},
    {"name": "get_claim_status", "description": "Get the current status of a claim by its ID (format CLM-xxxx).",
     "inputSchema": {"type": "object", "properties": {"claim_id": {"type": "string"}}, "required": ["claim_id"]}},
    {"name": "submit_claim", "description": "Submit a new insurance claim against a policy. Claims above 10,000 USD are blocked by policy.",
     "inputSchema": {"type": "object",
                     "properties": {"policy_id": {"type": "string"}, "amount_usd": {"type": "integer"},
                                    "description": {"type": "string"}},
                     "required": ["policy_id", "amount_usd", "description"]}},
]
# Tried in order: (tools schema version, include the "remotes" endpoint or not).
# None = no tools. The last attempt matches the minimal example in the AWS docs.
ATTEMPTS = [("2025-11-25", True), ("2025-06-18", True), ("2024-11-05", True), (None, True), (None, False)]
TOOLS_SCHEMA_VERSIONS = [a[0] for a in ATTEMPTS]


def mcp_descriptor(url, tools_version, with_remotes=True):
    server = {
        "name": "io.demo-insurance/claims-tools",
        # MCP server schema 2025-12-11: description is limited to 100 characters
        "description": "Insurance claims tools: policy lookup, claim status, claim submission",
        "version": "1.0.0",
    }
    if with_remotes:
        server["remotes"] = [{"type": "streamable-http", "url": url}]
    d = {"mcpServer": {"data": json.dumps(server), "dataSchemaVersion": "2025-12-11"}}
    if tools_version:
        d["mcpServer"]["additionalData"] = {"tools": {"data": json.dumps({"tools": TOOLS}),
                                                      "dataSchemaVersion": tools_version}}
    return d


def custom_descriptor(rt_arn):
    agent = {
        "name": "Claims Agent",
        "kind": "agent",
        "description": "Insurance claims assistant for Demo Insurance: looks up policies, checks claim "
                       "status and submits claims.",
        "hosting": {"service": "Amazon Bedrock AgentCore Runtime", "protocol": "HTTP", "runtimeArn": rt_arn},
        "framework": "Strands Agents",
        "model": "Claude Haiku 4.5 (Amazon Bedrock)",
        "uses_tools": ["io.demo-insurance/claims-tools"],
        "governance": {"observability": "AgentCore Observability (CloudWatch)",
                       "policy": "ClaimsPolicyEngine: claims above 10,000 USD denied"},
        "owner": "Claims team",
    }
    return {"custom": {"data": json.dumps(agent)}}


# ---------------------------------------------------------------- commands
def cmd_create_registry():
    existing = find_registry()
    if existing:
        print(f"Registry '{REGISTRY_NAME}' already exists: {existing['registryArn']}")
        wait_registry_ready(existing["registryArn"])
        return
    resp = ctl.create_registry(
        name=REGISTRY_NAME,
        description="Demo Insurance: shared catalog of agents and tools",
        discoveryConfiguration={"authorizerType": "AWS_IAM"},
        # No autoApprovalRules: records must be approved manually by an Admin
    )
    arn = resp["registryArn"]
    print(f"[OK] Created registry: {arn}")
    wait_registry_ready(arn)
    print("[OK] Registry READY. Search uses IAM, records need manual approval.")


def create_and_submit(reg, name, display, desc, rtype, descriptors):
    for r in list_records(reg):
        if r["name"] == name:
            print(f"  record '{name}' already exists (status {r['status']}), skipping")
            return r["recordId"], r["status"]
    resp = ctl.create_registry_record(registryId=reg, name=name, displayName=display, description=desc,
                                      recordType=rtype, descriptors=descriptors, recordVersion="1.0.0")
    rid = resp["recordArn"].split("/record/")[-1]
    print(f"  [Publisher] created record '{name}' ({rtype}) -> {resp['status']}")
    g = wait_record(reg, rid)
    if g["status"].endswith("FAILED"):
        return rid, f"{g['status']}: {g.get('statusReason')}"
    print(f"  record '{name}' -> {g['status']}")
    s = ctl.submit_registry_record_for_approval(registryId=reg, recordId=rid)
    print(f"  [Publisher] submitted '{name}' for approval -> {s['status']}")
    return rid, s["status"]


def cmd_publish():
    reg = registry_or_exit()["registryArn"]
    url, rt = gateway_url(), runtime_arn()
    print(f"Gateway MCP URL: {url}\nRuntime ARN    : {rt}\n")

    # 1) MCP record for Claims Tools (tries other tools schema versions if rejected)
    for ver, remotes in ATTEMPTS:
        try:
            rid, st = create_and_submit(reg, "claims-tools", "Claims Tools (MCP)",
                                        "Policy lookup, claim status and claim submission tools behind ClaimsGateway.",
                                        "MCP", mcp_descriptor(url, ver, remotes))
        except ClientError as e:
            st = f"ERROR {e.response['Error']['Code']}: {e.response['Error'].get('Message', '')}"
            rid = None
        if not str(st).startswith(("CREATE_FAILED", "ERROR")):
            print(f"  (tools schema version: {ver or 'no tools'}, remotes: {remotes})")
            break
        print(f"  failed with tools schema {ver}, remotes {remotes}: {st}")
        if rid:
            ctl.delete_registry_record(registryId=reg, recordId=rid)
            time.sleep(5)

    # 2) CUSTOM record for Claims Agent (HTTP agent, not A2A)
    try:
        create_and_submit(reg, "claims-agent", "Claims Agent",
                          "Insurance claims assistant on AgentCore Runtime, governed by AgentCore Policy.",
                          "CUSTOM", custom_descriptor(rt))
    except ClientError as e:
        print(f"  ERROR claims-agent: {e.response['Error']['Code']}: {e.response['Error'].get('Message', '')}")
    print("\nDone. Records are waiting for Admin approval. Search now to see that nothing is found yet.")
    cmd_status()


def cmd_approve():
    reg = registry_or_exit()["registryArn"]
    pending = [r for r in list_records(reg) if r["status"] == "PENDING_APPROVAL"]
    if not pending:
        print("No records are pending approval.")
    for r in pending:
        resp = ctl.update_registry_record_status(registryId=reg, recordId=r["recordId"], status="APPROVED",
                                                 statusReason="Reviewed by platform admin for the demo")
        print(f"  [Admin] approved '{r['name']}' -> {resp['status']}")
    print("Search may take a few minutes to show newly approved records.")


def cmd_search(query):
    reg = registry_or_exit()["registryArn"]
    resp = disc.search_discoverable_registry_records(searchQuery=query, registryIds=[reg], maxResults=10)
    recs = resp.get("registryRecords", [])
    print(f"[Consumer] search: \"{query}\" -> {len(recs)} result(s)")
    for r in recs:
        print(f"  - {r.get('displayName') or r['name']}  [{r['recordType']}]  v{r['recordVersion']}  {r['status']}")
        if r.get("description"):
            print(f"    {r['description']}")


def cmd_status():
    r = registry_or_exit()
    print(f"\nRegistry: {r['name']}  ({r.get('status', '')})")
    for rec in list_records(r["registryArn"]):
        print(f"  - {rec['name']:<14} {rec['recordType']:<7} v{rec['recordVersion']:<6} {rec['status']}")


def cmd_cleanup():
    r = find_registry()
    if not r:
        print("No registry to delete.")
        return
    for rec in list_records(r["registryArn"]):
        ctl.delete_registry_record(registryId=r["registryArn"], recordId=rec["recordId"])
        print(f"  deleted record {rec['name']}")
    time.sleep(10)
    ctl.delete_registry(registryId=r["registryArn"])
    print(f"  deleted registry {r['name']}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd = sys.argv[1]
    if cmd == "create-registry":
        cmd_create_registry()
    elif cmd == "publish":
        cmd_publish()
    elif cmd == "approve":
        cmd_approve()
    elif cmd == "search":
        cmd_search(" ".join(sys.argv[2:]) or "insurance claim tools")
    elif cmd == "status":
        cmd_status()
    elif cmd == "cleanup":
        cmd_cleanup()
    else:
        sys.exit(__doc__)
