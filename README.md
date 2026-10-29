# Claims Agent: Amazon Bedrock AgentCore Observability, Policy, Registry

A hands-on demo of three Amazon Bedrock AgentCore capabilities, built on one insurance claims agent:

| Part | Service | What the demo shows |
|---|---|---|
| 1 | **AgentCore Observability** | Every session, trace and span of the agent in CloudWatch GenAI Observability, with no instrumentation code. The trace reveals the agent submitting a 50,000 USD claim on a policy capped at 5,000 USD. |
| 2 | **AgentCore Policy** | Tools moved behind AgentCore Gateway and guarded by Cedar policies: default deny, a `permit` for claims up to 10,000 USD, and a `forbid` rule generated from a plain-English sentence ("forbid wins"). Every denial is visible in the trace. |
| 3 | **AWS Agent Registry** | The tools (MCP record) and the agent (Custom record) published to a private registry, with the Publisher → Admin approval → Consumer search flow. Records are not discoverable until approved. |

## The agent

- **Claims Agent**, an insurance assistant written with [Strands Agents](https://strandsagents.com), model Claude Haiku 4.5 on Amazon Bedrock.
- Runs on **AgentCore Runtime** (`us-east-1`), deployed with the AgentCore CLI (CodeZip build, no Docker).
- Three tools on mock data: `get_policy`, `get_claim_status`, `submit_claim`.

Mock data: `POL-1001` (auto, limit 5,000 USD), `POL-1002` (home, 20,000 USD), `POL-1003` (expired).

## Architecture (after Part 2)

```
Customer ──> AgentCore Runtime (Claims Agent, Strands + Claude Haiku 4.5)
                 │  MCP, SigV4
                 ▼
             AgentCore Gateway (ClaimsGateway) ── Policy Engine (Cedar, ENFORCE)
                 │  only allowed calls
                 ▼
             AWS Lambda (ClaimsTools: get_policy, get_claim_status, submit_claim)

Runtime, Gateway ──> CloudWatch (traces, logs, metrics)       [Part 1]
Gateway URL, Runtime ARN ──> AWS Agent Registry (MCP + Custom records)   [Part 3]
```

## Repository layout

```
├── app/
│   ├── ClaimsAgent/          # Agent code (main.py is the Part 2 version: tools via Gateway)
│   └── ClaimsTools/          # Lambda with the 3 tools (Part 2)
├── agentcore/                # AgentCore CLI project config (agentcore.json, aws-targets.json, CDK)
├── policies/                 # Cedar policies (Part 2), ARNs replaced by placeholders
├── setup_claims_demo.py      # Part 1: turns a fresh `agentcore create` project into Claims Agent
├── traffic.py                # Part 1: 10 simulated customers, one session each
├── setup_policy_demo.py      # Part 2: adds the Lambda target and rewires the agent to the Gateway
├── make_policies.py          # Part 2: writes the 2 Cedar policies with your Gateway ARN
├── gateway_test.py           # Part 2: calls the Gateway directly (no model) to show Allow / Deny
└── registry_demo.py          # Part 3: create registry, publish, search, approve, cleanup
```

`agentcore/agentcore.json` is committed in its reset state (all resources removed after the demo). The steps below rebuild everything.

## Prerequisites

- AWS account with Bedrock model access to Claude Haiku 4.5 in `us-east-1`, and an IAM user with CLI credentials (`aws configure`)
- Node.js 20+, Python 3.10+, [uv](https://docs.astral.sh/uv/), AWS CLI v2
- AgentCore CLI **0.31.1** (`npm install -g @aws/agentcore@0.31.1`). Version 1.0.0 changed the command syntax used here.

## Run it

All commands run from the project root in PowerShell or bash.

### Part 1: Observability

```
agentcore create --project-name ClaimsDemo --name ClaimsAgent --language Python --framework Strands --model-provider Bedrock --memory none --build CodeZip
cd ClaimsDemo
# copy the *.py scripts from this repo into ClaimsDemo
python setup_claims_demo.py
agentcore validate
agentcore deploy
agentcore invoke --prompt "My car was destroyed in a flood. Please submit a claim of 50000 USD on policy POL-1001."
uv run --with boto3 traffic.py
```

Then open **CloudWatch > GenAI Observability > Bedrock AgentCore** (sessions, traces, spans, metrics) and the runtime log group under **Logs**. The first deploy enables CloudWatch Transaction Search; spans can take about 10 minutes to appear the first time.

### Part 2: Policy

```
agentcore add gateway --name ClaimsGateway --authorizer-type AWS_IAM
python setup_policy_demo.py
agentcore add policy-engine --name ClaimsPolicyEngine --attach-to-gateways ClaimsGateway --attach-mode ENFORCE
agentcore deploy
uv run --with boto3 gateway_test.py          # default deny: every call is blocked

uv run --with boto3 make_policies.py
agentcore add policy --name AllowReadTools --engine ClaimsPolicyEngine --source policies/allow_read_tools.cedar
agentcore add policy --name AllowSmallClaims --engine ClaimsPolicyEngine --source policies/allow_small_claims.cedar
agentcore deploy
uv run --with boto3 gateway_test.py          # lookups and 1,500 USD allowed, 50,000 USD denied

agentcore add policy --name NoClaimsOnPol1003 --engine ClaimsPolicyEngine --gateway ClaimsGateway --generate "Never allow submit_claim when policy_id is POL-1003"
agentcore deploy
uv run --with boto3 gateway_test.py          # 500 USD on POL-1003 denied: forbid wins
```

### Part 3: Registry

```
uv run --with boto3 registry_demo.py create-registry
uv run --with boto3 registry_demo.py publish
uv run --with boto3 registry_demo.py search "insurance claim tools"   # 0 results while pending
uv run --with boto3 registry_demo.py approve
# wait 2-3 minutes for search to index the approved records
uv run --with boto3 registry_demo.py search "insurance claim tools"   # 2 results
```

## Results

| Request | Part 1 (no policy) | Part 2 (Cedar at the Gateway) |
|---|---|---|
| Look up POL-1001 | Allowed | Allowed (`AllowReadTools`) |
| Claim 1,500 USD on POL-1002 | Submitted | Allowed (`AllowSmallClaims`) |
| Claim 50,000 USD on POL-1001 | **Submitted by the model** | Denied: no policy applies (default deny) |
| Claim 500 USD on POL-1003 | Rejected by tool code (expired) | Denied: `NoClaimsOnPol1003` (forbid wins) |

## Lessons learned

- **CloudShell is too small** for this stack (CLI about 650 MB plus CDK about 300 MB against a 1 GB limit); run from a local machine.
- **Pin the AgentCore CLI** to 0.31.1; 1.0.0 changed the syntax.
- **Agent Registry moved to its own API namespace**: use `agent-registry-control` (admin, publisher) and `agent-registry` (search). The older `bedrock-agentcore-control` registry calls returned `AccessDenied`.
- **MCP records are schema-validated**: under MCP server schema `2025-12-11` the server `description` is limited to 100 characters.
- **Registry search is eventually consistent**: newly approved records take a few minutes to show up.
- With the CLI 0.31.1, `agentcore deploy` refuses an empty project after `agentcore remove all`; delete the CloudFormation stack from the console if it remains.

## Cleanup

```
uv run --with boto3 registry_demo.py cleanup
agentcore remove all
agentcore deploy
```

If the stack is still listed in CloudFormation, delete it there. Then delete the CloudWatch log groups created by the demo and deactivate the IAM access key.

## References

- [Amazon Bedrock AgentCore developer guide](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/)
- [Policy in Amazon Bedrock AgentCore](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy.html)
- [Get started with AWS Agent Registry](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/registry-get-started.html)
- [AgentCore CLI](https://github.com/aws/agentcore-cli)
