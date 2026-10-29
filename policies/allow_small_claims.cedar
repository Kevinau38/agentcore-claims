// Allow the agent to submit claims of 10000 USD or less.
// Larger claims match no policy and are denied by default (default deny).
permit(
  principal,
  action == AgentCore::Action::"ClaimsTools___submit_claim",
  resource == AgentCore::Gateway::"arn:aws:bedrock-agentcore:us-east-1:<ACCOUNT_ID>:gateway/<GATEWAY_ID>"
)
when {
  context.input.amount_usd <= 10000
};
