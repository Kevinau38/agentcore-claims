from strands.models.bedrock import BedrockModel


def load_model() -> BedrockModel:
    """Bedrock model for the Claims Agent (Claude Haiku 4.5: fast and low cost)."""
    return BedrockModel(model_id="us.anthropic.claude-haiku-4-5-20251001-v1:0")
