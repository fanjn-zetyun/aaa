from app.core.config import Settings


def test_agent_runtime_v3_feature_flag_defaults_to_disabled():
    settings = Settings()

    assert settings.agent_runtime_v3_enabled is False
