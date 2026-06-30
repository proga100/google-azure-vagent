"""Application settings, loaded from environment / .env.

Single ``Settings`` model plus a cached ``get_settings()`` accessor used as a
FastAPI dependency. Field names are provider-neutral on the pipeline side
(``tts_voice``, ``audio_input_sample_rate_hz``) so the orchestration code never
hard-codes a provider; Google-specific knobs are grouped under ``google_*`` /
``gemini_*``.

This is the PUBLIC English demo (Flance portfolio): Gemini Live (STT+LLM) with a
switchable voice — Gemini Live timbres or Azure en-US neural voices. Because it is
a public chat it is cost-guarded: a hard per-session cap of ``demo_word_limit``
user words, plus a concurrent-session cap.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    provider: Literal["google"] = "google"

    # ---- Google Cloud / Gemini auth ----
    # ADC service-account JSON path for Cloud Speech-to-Text (Vertex/Cloud APIs).
    google_application_credentials: str | None = None
    google_project_id: str = ""
    # API key for the Gemini Developer API (google-genai). If unset, google-genai
    # falls back to ADC / Vertex via google_genai_use_vertexai.
    gemini_api_key: str | None = None
    google_genai_use_vertexai: bool = False

    # ---- STT: Cloud Speech-to-Text v2 ----
    # chirp / chirp_2 are the Uzbek-capable models; they live in specific regions
    # (asia-southeast1, europe-west4). The region is part of the recognizer path
    # AND the client endpoint, so it must match a region that serves the model.
    google_stt_region: str = "europe-west4"
    google_stt_language: str = "en-US"
    google_stt_model: str = "chirp_2"

    # ---- LLM: Gemini (text) ----
    # gemini-3.5-flash is the newest text flash; thinking is disabled below for
    # voice latency (a thinking budget would eat the short max_tokens reply).
    gemini_model: str = "gemini-3.5-flash"
    gemini_temperature: float = 0.3
    gemini_max_tokens: int = 120

    # ---- Speech-out path selection ----
    # gemini_live  -> Gemini Live API native audio (ONLY Google path to Uzbek voice)
    # external     -> an external Uzbek TTS plugged into the staged pipeline
    # none         -> staged pipeline with NO voice; fails loudly when asked to speak
    tts_provider: Literal["gemini_live", "external", "none"] = "gemini_live"
    # When true, the whole conversation runs over the Gemini Live realtime session
    # (audio-in -> audio-out) instead of the staged STT->LLM->TTS pipeline.
    use_gemini_live_audio: bool = True

    # ---- Gemini Live API ----
    # Half-cascade Live model: ~1.3s to first audio vs ~3.7s for 2.5 native-audio
    # (measured), and it honours an explicit language_code. Default voice path.
    gemini_live_model: str = "gemini-3.1-flash-live-preview"
    # Brain for Azure-voice mode (STT + reply text); same half-cascade model.
    gemini_live_text_model: str = "gemini-3.1-flash-live-preview"
    gemini_live_language: str = "en-US"
    # Prebuilt Live HD voice (language-agnostic timbre). NOT a Cloud TTS voice id.
    gemini_live_voice: str = "Aoede"

    # ---- External Uzbek TTS fallback (only used when tts_provider=external) ----
    # e.g. an Azure uz-UZ voice or a self-hosted Chatterbox/FeruzaSpeech endpoint.
    external_tts_url: str | None = None
    external_tts_voice: str = ""

    # ---- Azure Neural TTS (native voice, accent-free) ----
    # Used when the client selects an "azure:<voice>" voice (e.g. en-US-AvaNeural):
    # Gemini Live does STT + reasoning, Azure speaks the reply. The SSML language
    # is derived from the voice locale (en-US-... -> en-US).
    azure_speech_key: str | None = None
    azure_speech_region: str = "eastus"
    azure_tts_format: str = "raw-24khz-16bit-mono-pcm"  # matches client 24 kHz
    # Azure Neural TTS price (USD per 1M characters) for the cost panel.
    azure_tts_price_per_1m_chars: float = 16.0
    # Speak the opening clause after this many chars (on the first comma) so the
    # first Azure audio starts sooner. Lower = faster first audio, choppier start.
    azure_first_clause_chars: int = 12

    # ---- Generic audio (provider-neutral) ----
    audio_input_sample_rate_hz: int = 16000   # mic -> STT / Live input
    audio_output_sample_rate_hz: int = 24000  # Gemini Live native audio is 24 kHz
    # Generic "current voice" surfaced to the pipeline (filler bank, /health).
    tts_voice: str = "Aoede"

    # ---- Optional translation bridge ----
    # Gemini handles Uzbek directly, so the bridge defaults OFF (unlike Yandex).
    voice_use_russian_bridge: bool = False
    bridge_user_lang: str = "uz"
    bridge_model_lang: str = "ru"

    # ---- Public demo cost guards ----
    # Hard per-session cap: after this many recognized USER words, the server
    # locks input and emits a "demo.limit" event (the client shows a popup).
    demo_mode: bool = True
    demo_word_limit: int = 15
    # Reject new sessions past this many concurrent ones (0 = unlimited) so the
    # public URL can't drain the API keys. Sent back as a "demo.busy" event.
    demo_max_concurrent_sessions: int = 8

    # ---- Voice pipeline ----
    voice_pipeline_mode: str = "google_azure_en_demo"
    voice_transport: Literal["websocket"] = "websocket"
    voice_enable_barge_in: bool = True
    voice_enable_filler: bool = True
    voice_endpoint_silence_ms: int = 500
    voice_input_gate_enabled: bool = True
    voice_input_gate_threshold: float = 0.02
    voice_input_gate_hangover_ms: int = 600

    # ---- App auth / CORS ----
    voice_api_token: str = ""  # empty = open (public demo)
    cors_origins: str = "http://localhost:3011,http://127.0.0.1:3011"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def stt_recognizer_path(self) -> str:
        """Inline recognizer resource for Cloud Speech-to-Text v2."""
        return (
            f"projects/{self.google_project_id}"
            f"/locations/{self.google_stt_region}/recognizers/_"
        )

    @property
    def stt_api_endpoint(self) -> str:
        """Regional Speech-to-Text endpoint (must match the chirp model region)."""
        return f"{self.google_stt_region}-speech.googleapis.com"


@lru_cache
def get_settings() -> Settings:
    return Settings()
