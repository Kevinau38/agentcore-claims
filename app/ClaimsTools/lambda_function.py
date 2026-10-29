"""Claims tools chay tren AWS Lambda, dat sau AgentCore Gateway (phan 2 - Policy)."""
import json

POLICIES = {
    "POL-1001": {"holder": "Nguyen Van An", "type": "auto", "coverage_limit_usd": 5000,
                 "deductible_usd": 200, "status": "active"},
    "POL-1002": {"holder": "Tran Thi Binh", "type": "home", "coverage_limit_usd": 20000,
                 "deductible_usd": 500, "status": "active"},
    "POL-1003": {"holder": "Le Van Cuong", "type": "health", "coverage_limit_usd": 10000,
                 "deductible_usd": 0, "status": "expired"},
}
CLAIMS = {
    "CLM-5001": {"policy_id": "POL-1001", "amount_usd": 1200, "status": "approved"},
    "CLM-5002": {"policy_id": "POL-1002", "amount_usd": 3400, "status": "under_review"},
}
_next_claim = [5003]


def get_policy(policy_id: str) -> dict:
    policy = POLICIES.get(str(policy_id).strip().upper())
    if not policy:
        return {"error": f"Policy {policy_id} not found"}
    return {"policy_id": str(policy_id).upper(), **policy}


def get_claim_status(claim_id: str) -> dict:
    claim = CLAIMS.get(str(claim_id).strip().upper())
    if not claim:
        return {"error": f"Claim {claim_id} not found"}
    return {"claim_id": str(claim_id).upper(), **claim}


def submit_claim(policy_id: str, amount_usd: int, description: str = "") -> dict:
    pid = str(policy_id).strip().upper()
    policy = POLICIES.get(pid)
    if not policy:
        return {"error": f"Policy {policy_id} not found"}
    if policy["status"] != "active":
        return {"error": f"Policy {pid} is {policy['status']}, cannot submit claim"}
    if int(amount_usd) <= 0:
        return {"error": "Amount must be greater than 0"}
    claim_id = f"CLM-{_next_claim[0]}"
    _next_claim[0] += 1
    CLAIMS[claim_id] = {"policy_id": pid, "amount_usd": int(amount_usd), "status": "submitted",
                        "description": description}
    return {"claim_id": claim_id, "status": "submitted"}


TOOLS = {"get_policy": get_policy, "get_claim_status": get_claim_status, "submit_claim": submit_claim}


def handler(event, context):
    full_name = context.client_context.custom["bedrockAgentCoreToolName"]
    tool_name = full_name.split("___", 1)[-1]          # bo tien to "<target>___"
    print(json.dumps({"tool": tool_name, "input": event}))
    fn = TOOLS.get(tool_name)
    if not fn:
        return {"error": f"Unknown tool {tool_name}"}
    try:
        return fn(**event)
    except TypeError as e:
        return {"error": f"Bad arguments for {tool_name}: {e}"}
