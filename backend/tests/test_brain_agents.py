from app.brain import AGENT_PROFILES, agent_provider, default_provider
from app.config import settings


def test_agent_provider_uses_configured_model_for_all_roles() -> None:
    for agent_name in AGENT_PROFILES:
        provider = agent_provider(agent_name)

        assert provider.agent_name == agent_name
        assert provider.model == settings.deepseek_model


def test_agent_provider_returns_isolated_instances() -> None:
    first = agent_provider("director")
    second = agent_provider("director")

    first.temperature = 9.9

    assert first is not second
    assert second.temperature == AGENT_PROFILES["director"].temperature


def test_default_provider_remains_backward_compatible() -> None:
    provider = default_provider()

    assert provider.agent_name == "default"
    assert provider.model == settings.deepseek_model
