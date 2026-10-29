import os
from collections import OrderedDict
from strands import Agent
from strands.agent.conversation_manager.null_conversation_manager import NullConversationManager
from strands.tools.mcp.mcp_client import MCPClient
from mcp_proxy_for_aws.client import aws_iam_streamablehttp_client
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from model.load import load_model

app = BedrockAgentCoreApp()
log = app.logger

# Part 2: the tools are no longer in the agent code. The agent calls them through AgentCore Gateway (MCP),
# and the Gateway asks the Policy Engine (Cedar) before allowing the Lambda call.
GATEWAY_URL_ENV = "AGENTCORE_GATEWAY_CLAIMSGATEWAY_URL"   # injected into the Runtime by the CLI at deploy time


def get_gateway_client():
    url = os.environ.get(GATEWAY_URL_ENV)
    if not url:
        log.warning(f"{GATEWAY_URL_ENV} not set - gateway tools unavailable")
        return None
    region = os.environ.get("AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1"))
    return MCPClient(lambda: aws_iam_streamablehttp_client(url, aws_service="bedrock-agentcore",
                                                           aws_region=region))


DEFAULT_SYSTEM_PROMPT = """
You are an insurance claims assistant for Demo Insurance.
Help customers look up policies, check claim status and submit claims using the tools provided.
If a tool call is denied by policy, tell the customer the request cannot be completed automatically
and that a human claims adjuster will review it.
"""

tools = [c for c in [get_gateway_client()] if c]


def agent_factory():
    cache = OrderedDict()

    def get_or_create_agent(session_id):
        if session_id in cache:
            cache.move_to_end(session_id)
            return cache[session_id]
        if len(cache) >= 128:
            cache.popitem(last=False)
        cache[session_id] = Agent(
            model=load_model(),
            system_prompt=DEFAULT_SYSTEM_PROMPT,
            tools=tools,
            conversation_manager=NullConversationManager(),
        )
        return cache[session_id]
    return get_or_create_agent


get_or_create_agent = agent_factory()


def _extract_prompt(payload: dict):
    if not isinstance(payload, dict):
        raise ValueError("payload must be a JSON object")
    prompt = payload.get("prompt", "")
    if not isinstance(prompt, str):
        raise ValueError("prompt must be a string")
    return prompt


@app.entrypoint
async def invoke(payload, context):
    log.info("Invoking ClaimsAgent (via Gateway)")
    session_id = getattr(context, "session_id", "default-session")
    agent = get_or_create_agent(session_id)
    prompt = _extract_prompt(payload)
    async for event in agent.stream_async(prompt):
        if not isinstance(event, dict) or "event" not in event:
            continue
        cbs = event["event"].get("contentBlockStart")
        if cbs is not None and not cbs.get("start"):
            continue
        yield event


if __name__ == "__main__":
    app.run()
