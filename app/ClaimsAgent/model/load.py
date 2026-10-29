from strands.models.bedrock import BedrockModel


def load_model() -> BedrockModel:
    """Model Bedrock cho Claims Agent (Claude Haiku 4.5, re va nhanh)."""
    return BedrockModel(model_id="us.anthropic.claude-haiku-4-5-20251001-v1:0")
