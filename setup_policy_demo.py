"""Phan 2 (Policy): dua 3 tool cua Claims Agent ra Lambda sau AgentCore Gateway.
Chay tu thu muc ClaimsDemo, SAU KHI da chay: agentcore add gateway --name ClaimsGateway --authorizer-type AWS_IAM
    python setup_policy_demo.py
"""
import json, pathlib, re, sys

ROOT = pathlib.Path.cwd()
CFG = ROOT / "agentcore" / "agentcore.json"
AGENT_DIR = ROOT / "app" / "ClaimsAgent"
TOOLS_DIR = ROOT / "app" / "ClaimsTools"
GATEWAY = "ClaimsGateway"
TARGET = "ClaimsTools"

if not CFG.exists() or not AGENT_DIR.exists():
    sys.exit("Khong thay agentcore/agentcore.json hoac app/ClaimsAgent. Hay cd vao thu muc ClaimsDemo truoc.")

cfg = json.loads(CFG.read_text(encoding="utf-8"))
gw = next((g for g in cfg.get("agentCoreGateways", []) if g["name"] == GATEWAY), None)
if gw is None:
    sys.exit(f"Chua co gateway '{GATEWAY}'. Chay truoc: agentcore add gateway --name {GATEWAY} --authorizer-type AWS_IAM")

LAMBDA_PY = '"""Claims tools chay tren AWS Lambda, dat sau AgentCore Gateway (phan 2 - Policy)."""\nimport json\n\nPOLICIES = {\n    "POL-1001": {"holder": "Nguyen Van An", "type": "auto", "coverage_limit_usd": 5000,\n                 "deductible_usd": 200, "status": "active"},\n    "POL-1002": {"holder": "Tran Thi Binh", "type": "home", "coverage_limit_usd": 20000,\n                 "deductible_usd": 500, "status": "active"},\n    "POL-1003": {"holder": "Le Van Cuong", "type": "health", "coverage_limit_usd": 10000,\n                 "deductible_usd": 0, "status": "expired"},\n}\nCLAIMS = {\n    "CLM-5001": {"policy_id": "POL-1001", "amount_usd": 1200, "status": "approved"},\n    "CLM-5002": {"policy_id": "POL-1002", "amount_usd": 3400, "status": "under_review"},\n}\n_next_claim = [5003]\n\n\ndef get_policy(policy_id: str) -> dict:\n    policy = POLICIES.get(str(policy_id).strip().upper())\n    if not policy:\n        return {"error": f"Policy {policy_id} not found"}\n    return {"policy_id": str(policy_id).upper(), **policy}\n\n\ndef get_claim_status(claim_id: str) -> dict:\n    claim = CLAIMS.get(str(claim_id).strip().upper())\n    if not claim:\n        return {"error": f"Claim {claim_id} not found"}\n    return {"claim_id": str(claim_id).upper(), **claim}\n\n\ndef submit_claim(policy_id: str, amount_usd: int, description: str = "") -> dict:\n    pid = str(policy_id).strip().upper()\n    policy = POLICIES.get(pid)\n    if not policy:\n        return {"error": f"Policy {policy_id} not found"}\n    if policy["status"] != "active":\n        return {"error": f"Policy {pid} is {policy[\'status\']}, cannot submit claim"}\n    if int(amount_usd) <= 0:\n        return {"error": "Amount must be greater than 0"}\n    claim_id = f"CLM-{_next_claim[0]}"\n    _next_claim[0] += 1\n    CLAIMS[claim_id] = {"policy_id": pid, "amount_usd": int(amount_usd), "status": "submitted",\n                        "description": description}\n    return {"claim_id": claim_id, "status": "submitted"}\n\n\nTOOLS = {"get_policy": get_policy, "get_claim_status": get_claim_status, "submit_claim": submit_claim}\n\n\ndef handler(event, context):\n    full_name = context.client_context.custom["bedrockAgentCoreToolName"]\n    tool_name = full_name.split("___", 1)[-1]          # bo tien to "<target>___"\n    print(json.dumps({"tool": tool_name, "input": event}))\n    fn = TOOLS.get(tool_name)\n    if not fn:\n        return {"error": f"Unknown tool {tool_name}"}\n    try:\n        return fn(**event)\n    except TypeError as e:\n        return {"error": f"Bad arguments for {tool_name}: {e}"}\n'
MAIN_PY = 'import os\nfrom collections import OrderedDict\nfrom strands import Agent\nfrom strands.agent.conversation_manager.null_conversation_manager import NullConversationManager\nfrom strands.tools.mcp.mcp_client import MCPClient\nfrom mcp_proxy_for_aws.client import aws_iam_streamablehttp_client\nfrom bedrock_agentcore.runtime import BedrockAgentCoreApp\nfrom model.load import load_model\n\napp = BedrockAgentCoreApp()\nlog = app.logger\n\n# Phan 2: tool khong con nam trong code agent. Agent goi tool qua AgentCore Gateway (MCP),\n# Gateway hoi Policy Engine (Cedar) truoc khi cho phep goi Lambda.\nGATEWAY_URL_ENV = "AGENTCORE_GATEWAY_CLAIMSGATEWAY_URL"   # CLI tu bom bien nay vao Runtime khi deploy\n\n\ndef get_gateway_client():\n    url = os.environ.get(GATEWAY_URL_ENV)\n    if not url:\n        log.warning(f"{GATEWAY_URL_ENV} not set - gateway tools unavailable")\n        return None\n    region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))\n    return MCPClient(lambda: aws_iam_streamablehttp_client(url, aws_service="bedrock-agentcore",\n                                                           aws_region=region))\n\n\nDEFAULT_SYSTEM_PROMPT = """\nYou are an insurance claims assistant for Demo Insurance.\nHelp customers look up policies, check claim status and submit claims using the tools provided.\nIf a tool call is denied by policy, tell the customer the request cannot be completed automatically\nand that a human claims adjuster will review it.\n"""\n\ntools = [c for c in [get_gateway_client()] if c]\n\n\ndef agent_factory():\n    cache = OrderedDict()\n\n    def get_or_create_agent(session_id):\n        if session_id in cache:\n            cache.move_to_end(session_id)\n            return cache[session_id]\n        if len(cache) >= 128:\n            cache.popitem(last=False)\n        cache[session_id] = Agent(\n            model=load_model(),\n            system_prompt=DEFAULT_SYSTEM_PROMPT,\n            tools=tools,\n            conversation_manager=NullConversationManager(),\n        )\n        return cache[session_id]\n    return get_or_create_agent\n\n\nget_or_create_agent = agent_factory()\n\n\ndef _extract_prompt(payload: dict):\n    if not isinstance(payload, dict):\n        raise ValueError("payload must be a JSON object")\n    prompt = payload.get("prompt", "")\n    if not isinstance(prompt, str):\n        raise ValueError("prompt must be a string")\n    return prompt\n\n\n@app.entrypoint\nasync def invoke(payload, context):\n    log.info("Invoking ClaimsAgent (via Gateway)")\n    session_id = getattr(context, "session_id", "default-session")\n    agent = get_or_create_agent(session_id)\n    prompt = _extract_prompt(payload)\n    async for event in agent.stream_async(prompt):\n        if not isinstance(event, dict) or "event" not in event:\n            continue\n        cbs = event["event"].get("contentBlockStart")\n        if cbs is not None and not cbs.get("start"):\n            continue\n        yield event\n\n\nif __name__ == "__main__":\n    app.run()\n'

TOOLS_PYPROJECT = '''[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "ClaimsTools"
version = "0.1.0"
description = "Claims tools for AgentCore Gateway (Lambda target)"
requires-python = ">=3.10"
dependencies = []

[tool.hatch.build.targets.wheel]
packages = ["."]
'''

TOOL_DEFS = [
    {"name": "get_policy",
     "description": "Look up an insurance policy by its ID (format POL-xxxx).",
     "inputSchema": {"type": "object",
                     "properties": {"policy_id": {"type": "string", "description": "Policy ID, e.g. POL-1001"}},
                     "required": ["policy_id"]}},
    {"name": "get_claim_status",
     "description": "Get the current status of a claim by its ID (format CLM-xxxx).",
     "inputSchema": {"type": "object",
                     "properties": {"claim_id": {"type": "string", "description": "Claim ID, e.g. CLM-5001"}},
                     "required": ["claim_id"]}},
    {"name": "submit_claim",
     "description": "Submit a new claim against a policy.",
     "inputSchema": {"type": "object",
                     "properties": {
                         "policy_id": {"type": "string", "description": "Policy ID, e.g. POL-1001"},
                         "amount_usd": {"type": "integer", "description": "Claim amount in whole US dollars"},
                         "description": {"type": "string", "description": "What happened"}},
                     "required": ["policy_id", "amount_usd", "description"]}},
]

# 1) Code Lambda chua 3 tool
TOOLS_DIR.mkdir(parents=True, exist_ok=True)
(TOOLS_DIR / "lambda_function.py").write_text(LAMBDA_PY, encoding="utf-8")
(TOOLS_DIR / "pyproject.toml").write_text(TOOLS_PYPROJECT, encoding="utf-8")
print("[OK] Tao app/ClaimsTools (Lambda chua get_policy, get_claim_status, submit_claim)")

# 2) Gateway target kieu Lambda (CLI tu build + deploy Lambda tu code o tren)
target = {
    "name": TARGET,
    "targetType": "lambda",
    "toolDefinitions": TOOL_DEFS,
    "compute": {
        "host": "Lambda",
        "implementation": {"language": "Python", "path": "app/ClaimsTools", "handler": "lambda_function.handler"},
        "pythonVersion": "PYTHON_3_12",
        "timeout": 30,
    },
}
gw["targets"] = [t for t in gw.get("targets", []) if t["name"] != TARGET] + [target]
CFG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"[OK] Them target '{TARGET}' vao gateway '{GATEWAY}' trong agentcore.json")

# 3) Agent: bo tool noi bo, goi tool qua Gateway bang MCP + SigV4 (AWS_IAM)
(AGENT_DIR / "main.py").write_text(MAIN_PY, encoding="utf-8")
pp = AGENT_DIR / "pyproject.toml"
text = pp.read_text(encoding="utf-8")
if "mcp-proxy-for-aws" not in text:
    text = re.sub(r"dependencies\s*=\s*\[", 'dependencies = [\n    "mcp-proxy-for-aws >= 1.1.0",', text, count=1)
    pp.write_text(text, encoding="utf-8")
print("[OK] Cap nhat app/ClaimsAgent/main.py va them mcp-proxy-for-aws vao pyproject.toml")
print("\nXong. Buoc tiep theo: agentcore add policy-engine ... (xem huong dan)")
