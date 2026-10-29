"""Part 1 (Observability): send simulated customer traffic to the Claims Agent on AgentCore Runtime.
Phần 1 (Observability): tạo traffic giả lập cho Claims Agent, mỗi kịch bản là một session.

Usage / Cách dùng:
    uv run --with boto3 traffic.py             # 1 round, about 10 sessions
    uv run --with boto3 traffic.py --rounds 3  # 3 rounds
"""
import argparse, json, time, uuid
import boto3

REGION = "us-east-1"

SCENARIOS = [
    ["What does policy POL-1001 cover?"],
    ["What is the status of claim CLM-5001?"],
    ["Kiểm tra giúp tôi hợp đồng POL-1002 còn hiệu lực không?"],                # question in Vietnamese
    ["I want to file a claim on POL-1002 for 1500 USD, a pipe burst and flooded my kitchen."],
    ["Can you check policy POL-9999 for me?"],                                  # policy does not exist
    ["Submit a claim of 800 USD on POL-1003 for a hospital visit."],            # policy expired
    ["I had a car accident yesterday, what should I do?"],                      # missing details
    ["Submit a claim on POL-1001 for 50000 USD, my car was totally destroyed."],  # over the limit (blocked by Policy in Part 2)
    ["Write me a poem about cats."],                                            # out of scope
    ["Look up POL-1001 please.", "OK, file a claim on it for 1200 USD for a broken windshield.",
     "What is the status of the claim you just created?"],                     # several turns in one session
]


def find_runtime_arn(name_part: str) -> str:
    ctl = boto3.client("bedrock-agentcore-control", region_name=REGION)
    for rt in ctl.list_agent_runtimes().get("agentRuntimes", []):
        if name_part.lower() in rt["agentRuntimeName"].lower():
            return rt["agentRuntimeArn"]
    raise SystemExit(f"No runtime name contains '{name_part}'. Did you run 'agentcore deploy'?")


def read_text(response) -> str:
    """Collect the text from the SSE stream (data: {...}) returned by the agent."""
    body = response["response"].read().decode("utf-8", errors="replace")
    out = []
    for line in body.splitlines():
        if not line.startswith("data: "):
            continue
        try:
            evt = json.loads(line[6:])
        except json.JSONDecodeError:
            continue
        if isinstance(evt, dict) and "error" in evt:
            out.append(f"[ERROR] {evt['error']}")
            continue
        delta = (evt.get("event", {}) if isinstance(evt, dict) else {}).get("contentBlockDelta", {}).get("delta", {})
        if "text" in delta:
            out.append(delta["text"])
    return "".join(out).strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rounds", type=int, default=1)
    ap.add_argument("--runtime", default="ClaimsAgent", help="part of the runtime name")
    args = ap.parse_args()

    arn = find_runtime_arn(args.runtime)
    print(f"Runtime: {arn}\n")
    data = boto3.client("bedrock-agentcore", region_name=REGION)

    for r in range(args.rounds):
        for i, turns in enumerate(SCENARIOS, 1):
            session_id = f"demo-r{r+1}-s{i:02d}-{uuid.uuid4().hex}"[:64]
            print(f"=== Round {r+1} | Session {i:02d} | {session_id}")
            for prompt in turns:
                t0 = time.time()
                try:
                    resp = data.invoke_agent_runtime(
                        agentRuntimeArn=arn, runtimeSessionId=session_id, qualifier="DEFAULT",
                        payload=json.dumps({"prompt": prompt}).encode())
                    text = read_text(resp)
                except Exception as e:
                    text = f"[EXCEPTION] {type(e).__name__}: {e}"
                print(f"  USER : {prompt}\n  AGENT: {text[:220]}{'...' if len(text) > 220 else ''}"
                      f"\n  ({time.time() - t0:.1f}s)")
            print()
    print("Done. Wait 2-5 minutes, then open CloudWatch > GenAI Observability > Bedrock AgentCore.")


if __name__ == "__main__":
    main()
