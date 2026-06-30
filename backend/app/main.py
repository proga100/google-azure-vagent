"""FastAPI app factory + WebSocket entry point.

``/health`` plus ``/ws/voice`` driving the English demo voice pipeline
(Gemini Live realtime; voice = Gemini timbre or Azure en-US neural) via
``run_voice_agent``. Binary WS frames are mic audio (PCM16 16k); JSON frames
are control events. Public-demo cost guards: a per-session word cap (enforced in
GeminiLiveSession) and a concurrent-session cap (enforced here).
"""
from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from app.auth import verify_token
from app.config import get_settings
from app.voice.pipeline.voice_agent import run_voice_agent

logger = logging.getLogger("voice")

# Gemini Live token prices (USD per 1M tokens), by model family. Audio in/out are
# billed far higher than text; 3.1 has pricier text than 2.5 native-audio.
_LIVE_PRICES = {
    "3.1-flash-live": {"textIn": 0.75, "audioIn": 3.00, "textOut": 4.50, "audioOut": 12.00},
    "native-audio":   {"textIn": 0.50, "audioIn": 3.00, "textOut": 2.00, "audioOut": 12.00},
}


def _pricing_for(model: str) -> dict:
    if "native-audio" in model:
        return _LIVE_PRICES["native-audio"]
    return _LIVE_PRICES["3.1-flash-live"]  # default (3.1 / other half-cascade)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Google+Azure English Voice Agent (demo)", version="0.1.0")
    app.state.active_sessions = 0

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health() -> dict:
        if settings.use_gemini_live_audio:
            native = "native-audio" in settings.gemini_live_model
            mode = "Gemini Live (native audio)" if native else "Gemini Live (half-cascade)"
            model = settings.gemini_live_model
            stt = f"{model} (built-in)"
            tts = f"{model} (built-in)"
        else:
            mode = f"Staged (TTS: {settings.tts_provider})"
            model = settings.gemini_model
            stt = f"Cloud STT {settings.google_stt_language}/{settings.google_stt_model}"
            tts = settings.tts_provider
        return {
            "status": "ok",
            "provider": settings.provider,
            "pipeline": settings.voice_pipeline_mode,
            "mode": mode,
            "model": model,
            "llm": model,
            "stt": stt,
            "tts": tts,
            "language": settings.google_stt_language,
            "voice": settings.tts_voice,
            # The brain used when an Azure voice is selected (client overrides the
            # display for azure: voices, since /health can't know the live choice).
            "azure_brain_model": settings.gemini_live_text_model,
            # Token prices (USD/1M) so the client's cost panel matches the model.
            "pricing": _pricing_for(model if settings.use_gemini_live_audio else settings.gemini_live_model),
            "azure_pricing": _pricing_for(settings.gemini_live_text_model),
            "azure_tts_price_per_1m_chars": settings.azure_tts_price_per_1m_chars,
            # Public demo guards (the client shows the word limit).
            "demo_mode": settings.demo_mode,
            "demo_word_limit": settings.demo_word_limit,
        }

    @app.websocket("/ws/voice")
    async def ws_voice(websocket: WebSocket) -> None:
        # Auth is optional: when VOICE_API_TOKEN is unset/empty the endpoint is
        # open (handy for local testing). Set a token to re-enable the gate.
        # Browsers can't set WS headers, so the token travels via ?token=.
        if settings.voice_api_token:
            token = websocket.query_params.get("token")
            if not verify_token(token, settings):
                await websocket.close(code=4401)  # 4401: app-level unauthorized
                return

        await websocket.accept()

        # Concurrent-session cap: protect the public demo's API keys.
        cap = settings.demo_max_concurrent_sessions
        if cap and app.state.active_sessions >= cap:
            await websocket.send_json({"type": "demo.busy", "message": "Demo is busy, please try again shortly."})
            await websocket.close(code=1013)  # 1013: try again later
            return

        app.state.active_sessions += 1
        session_id = uuid.uuid4().hex
        logger.info("ws/voice connected: %s (active=%d)", session_id, app.state.active_sessions)
        try:
            await run_voice_agent(websocket, settings, session_id)
        finally:
            app.state.active_sessions -= 1

    return app


app = create_app()
