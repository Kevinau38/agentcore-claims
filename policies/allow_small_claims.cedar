// Chi cho phep agent tu nop claim tu 10000 USD tro xuong.
// Claim lon hon khong khop policy nao -> mac dinh bi tu choi (default deny).
permit(
  principal,
  action == AgentCore::Action::"ClaimsTools___submit_claim",
  resource == AgentCore::Gateway::"arn:aws:bedrock-agentcore:us-east-1:<ACCOUNT_ID>:gateway/<GATEWAY_ID>"
)
when {
  context.input.amount_usd <= 10000
};
