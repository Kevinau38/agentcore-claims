// Cho phep agent tra cuu hop dong va trang thai claim
permit(
  principal,
  action in [
    AgentCore::Action::"ClaimsTools___get_policy",
    AgentCore::Action::"ClaimsTools___get_claim_status"
  ],
  resource == AgentCore::Gateway::"arn:aws:bedrock-agentcore:us-east-1:<ACCOUNT_ID>:gateway/<GATEWAY_ID>"
);
