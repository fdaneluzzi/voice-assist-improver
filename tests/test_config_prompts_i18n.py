from voice_assist_improver.config import Settings
from voice_assist_improver.i18n import normalize_language, t
from voice_assist_improver.prompts import load_voice_prompt
from voice_assist_improver.text import norm


def test_settings_load_from_environment(tmp_path):
    s = Settings.load(env_file=str(tmp_path / "none.env"), environ={
        "VAI_HA_URL": "http://ha:8123/", "VAI_PORT": "9999", "VAI_ALLOWED_NETWORKS": "10.0.0.0/24, 127.0.0.1/32",
        "VAI_MODELS": "a,b", "VAI_LANGUAGE": "pt-BR", "VAI_DATA_DIR": "x"})
    assert s.ha_url == "http://ha:8123" and s.port == 9999 and s.models == ("a", "b") and s.language == "pt-BR"
    assert s.allowed_networks == ("10.0.0.0/24", "127.0.0.1/32") and s.data_dir.is_absolute()


def test_defaults_are_safe_and_english():
    s = Settings()
    assert s.host == "127.0.0.1" and s.allowed_networks == ("127.0.0.0/8", "::1/128") and s.language == "en"


def test_language_normalization_and_messages():
    assert [normalize_language(x) for x in ("pt", "pt_BR", "PT-br", "en", "en-GB", "de", None, "")] == \
        ["pt-BR", "pt-BR", "pt-BR", "en", "en", "en", "en", "en"]
    assert "Sorry" in t("en", "backend_error") and "Desculpe" in t("pt", "backend_error")


def test_builtin_prompts_exist_in_both_languages_and_default_to_english():
    en, pt = load_voice_prompt("en"), load_voice_prompt("pt-BR")
    assert "voice assistant" in en and "assistente de voz" in pt
    assert load_voice_prompt(None) == en and load_voice_prompt("de") == en


def test_custom_prompt_file_wins_and_empty_file_falls_back(tmp_path):
    custom = tmp_path / "mine.md"
    custom.write_text("Answer like a pirate.")
    assert load_voice_prompt("en", custom) == "Answer like a pirate."
    custom.write_text("   ")
    assert "voice assistant" in load_voice_prompt("en", custom)


def test_prompts_keep_the_security_rule_about_web_content():
    for lang in ("en", "pt-BR"):
        text = load_voice_prompt(lang).lower()
        assert "never instructions" in text or "nunca instrução" in text


def test_norm():
    assert norm("  Luz da SUÍTE!! ") == "luz da suite"
