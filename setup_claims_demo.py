"""Bien project vua tao bang `agentcore create` thanh Claims Agent cho demo.
Chay tu thu muc goc project (ClaimsDemo):  python setup_claims_demo.py
"""
import json, pathlib, subprocess, sys

ROOT = pathlib.Path.cwd()
APP = ROOT / "app" / "ClaimsAgent"
CFG = ROOT / "agentcore" / "agentcore.json"
TARGETS = ROOT / "agentcore" / "aws-targets.json"
REGION = "us-east-1"
MODEL_ID = "us.anthropic.claude-haiku-4-5-20251001-v1:0"

if not CFG.exists() or not APP.exists():
    sys.exit("Khong thay agentcore/agentcore.json hoac app/ClaimsAgent. Hay cd vao thu muc ClaimsDemo truoc.")

MAIN_PY = 'from collections import OrderedDict\nfrom strands import Agent, tool\nfrom strands.agent.conversation_manager.null_conversation_manager import NullConversationManager\nfrom bedrock_agentcore.runtime import BedrockAgentCoreApp\nfrom opentelemetry import trace\nfrom model.load import load_model\n\napp = BedrockAgentCoreApp()\nlog = app.logger\n\n# Phan 2 (Policy) se them MCP client tro toi AgentCore Gateway vao day.\nmcp_clients = []\n\nDEFAULT_SYSTEM_PROMPT = """\nYou are an insurance claims assistant for Demo Insurance.\nHelp customers look up policies, check claim status and submit claims using the tools provided.\n"""\n\n# ---------------------------------------------------------------------------\n# Du lieu gia lap (mock) cho demo\n# ---------------------------------------------------------------------------\nPOLICIES = {\n    "POL-1001": {"holder": "Nguyen Van An", "type": "auto", "coverage_limit_usd": 5000,\n                 "deductible_usd": 200, "status": "active"},\n    "POL-1002": {"holder": "Tran Thi Binh", "type": "home", "coverage_limit_usd": 20000,\n                 "deductible_usd": 500, "status": "active"},\n    "POL-1003": {"holder": "Le Van Cuong", "type": "health", "coverage_limit_usd": 10000,\n                 "deductible_usd": 0, "status": "expired"},\n}\nCLAIMS = {\n    "CLM-5001": {"policy_id": "POL-1001", "amount_usd": 1200, "status": "approved"},\n    "CLM-5002": {"policy_id": "POL-1002", "amount_usd": 3400, "status": "under_review"},\n}\n_next_claim = [5003]\n\n\ndef _tag(**attrs):\n    """Gan custom attribute vao span hien tai -> xem duoc trong CloudWatch (Observability)."""\n    span = trace.get_current_span()\n    for k, v in attrs.items():\n        span.set_attribute(f"claims.{k}", v)\n\n\ntools = []\n_INLINE_FUNCTION_NAMES = set()\n\n\n@tool\ndef get_policy(policy_id: str) -> dict:\n    """Look up an insurance policy by its ID (format POL-xxxx)."""\n    _tag(policy_id=policy_id, operation="get_policy")\n    policy = POLICIES.get(policy_id.strip().upper())\n    if not policy:\n        _tag(result="not_found")\n        return {"error": f"Policy {policy_id} not found"}\n    _tag(result="found", policy_type=policy["type"])\n    return {"policy_id": policy_id.upper(), **policy}\n\n\n@tool\ndef get_claim_status(claim_id: str) -> dict:\n    """Get the current status of a claim by its ID (format CLM-xxxx)."""\n    _tag(claim_id=claim_id, operation="get_claim_status")\n    claim = CLAIMS.get(claim_id.strip().upper())\n    if not claim:\n        _tag(result="not_found")\n        return {"error": f"Claim {claim_id} not found"}\n    _tag(result="found", claim_status=claim["status"])\n    return {"claim_id": claim_id.upper(), **claim}\n\n\n@tool\ndef submit_claim(policy_id: str, amount_usd: float, description: str) -> dict:\n    """Submit a new claim against a policy."""\n    pid = policy_id.strip().upper()\n    _tag(policy_id=pid, operation="submit_claim", amount_usd=float(amount_usd))\n    policy = POLICIES.get(pid)\n    if not policy:\n        _tag(result="rejected_not_found")\n        return {"error": f"Policy {policy_id} not found"}\n    if policy["status"] != "active":\n        _tag(result="rejected_inactive")\n        return {"error": f"Policy {pid} is {policy[\'status\']}, cannot submit claim"}\n    if amount_usd <= 0:\n        _tag(result="rejected_invalid_amount")\n        return {"error": "Amount must be greater than 0"}\n    claim_id = f"CLM-{_next_claim[0]}"\n    _next_claim[0] += 1\n    CLAIMS[claim_id] = {"policy_id": pid, "amount_usd": amount_usd, "status": "submitted",\n                        "description": description}\n    _tag(result="submitted", claim_id=claim_id)\n    return {"claim_id": claim_id, "status": "submitted"}\n\n\ntools.extend([get_policy, get_claim_status, submit_claim])\n\nfor mcp_client in mcp_clients:\n    if mcp_client:\n        tools.append(mcp_client)\n\n\ndef agent_factory():\n    cache = OrderedDict()\n\n    def get_or_create_agent(session_id):\n        if session_id in cache:\n            cache.move_to_end(session_id)\n            return cache[session_id]\n        if len(cache) >= 128:\n            cache.popitem(last=False)\n        cache[session_id] = Agent(\n            model=load_model(),\n            system_prompt=DEFAULT_SYSTEM_PROMPT,\n            tools=tools,\n            conversation_manager=NullConversationManager(),\n        )\n        return cache[session_id]\n    return get_or_create_agent\n\n\nget_or_create_agent = agent_factory()\n\n\ndef _extract_prompt(payload: dict):\n    if not isinstance(payload, dict):\n        raise ValueError("payload must be a JSON object")\n    prompt = payload.get("prompt", "")\n    if not isinstance(prompt, str):\n        raise ValueError("prompt must be a string")\n    return prompt\n\n\n@app.entrypoint\nasync def invoke(payload, context):\n    log.info("Invoking ClaimsAgent")\n    session_id = getattr(context, "session_id", "default-session")\n    agent = get_or_create_agent(session_id)\n    prompt = _extract_prompt(payload)\n    async for event in agent.stream_async(prompt):\n        if not isinstance(event, dict) or "event" not in event:\n            continue\n        cbs = event["event"].get("contentBlockStart")\n        if cbs is not None and not cbs.get("start"):\n            continue\n        yield event\n\n\nif __name__ == "__main__":\n    app.run()\n'

LOAD_PY = f'''from strands.models.bedrock import BedrockModel


def load_model() -> BedrockModel:
    """Model Bedrock cho Claims Agent (Claude Haiku 4.5, re va nhanh)."""
    return BedrockModel(model_id="{MODEL_ID}")
'''


# 1) Code agent
(APP / "main.py").write_text(MAIN_PY, encoding="utf-8")
(APP / "model" / "load.py").write_text(LOAD_PY, encoding="utf-8")
print("[OK] Ghi app/ClaimsAgent/main.py va model/load.py")

# 2) (Khong dung config bundle: Optimization thuoc phan cua ban khac)
# 3) Deployment target: tai khoan hien tai + us-east-1
try:
    account = subprocess.check_output(
        ["aws", "sts", "get-caller-identity", "--query", "Account", "--output", "text"],
        text=True, shell=(sys.platform == "win32")).strip()
except Exception as e:
    sys.exit(f"Khong lay duoc Account ID qua AWS CLI ({e}). Kiem tra 'aws sts get-caller-identity'.")
TARGETS.write_text(json.dumps([{"name": "default", "account": account, "region": REGION}], indent=2),
                   encoding="utf-8")
print(f"[OK] aws-targets.json -> account {account}, region {REGION}")
print("\nXong. Buoc tiep theo: agentcore deploy")
