"""Per-connection orchestrator entry point.

Owns the WebSocket receive loop and translates frames to session calls: binary
frames are mic audio; JSON frames are control events. Keeps the transport
(FastAPI WebSocket) at the edge so the sessions stay transport-agnostic.

Two session shapes are selected by ``USE_GEMINI_LIVE_AUDIO``:
  * **Gemini Live** (default) — one realtime audio-in/audio-out session. The only
    Google path that speaks Uzbek.
  * **Staged** — STT (uz-UZ) -> Gemini text -> TTS (per ``TTS_PROVIDER``), the
    same orchestrator as the Yandex pipeline.
"""
from __future__ import annotations

import json
import logging

from fastapi import WebSocket, WebSocketDisconnect

from app.config import Settings
from app.voice.pipeline.prompts import DEMO_SYSTEM_PROMPT_EN
from app.voice.pipeline.streaming_session import StreamingSession
from app.voice.providers.factory import (
    build_auth,
    build_gpt,
    build_stt,
    build_translate,
    build_tts,
)
from app.voice.providers.gemini_live import GeminiLiveSession

logger = logging.getLogger("voice.agent")


def _build_session(websocket: WebSocket, settings: Settings, session_id: str):
    auth = build_auth(settings)

    async def send_json(payload: dict) -> None:
        await websocket.send_json(payload)

    async def send_bytes(data: bytes) -> None:
        await websocket.send_bytes(data)

    if settings.use_gemini_live_audio:
        logger.info("voice agent: Gemini Live realtime path")
        return GeminiLiveSession(
            settings=settings,
            auth=auth,
            send_json=send_json,
            send_bytes=send_bytes,
            system_prompt=DEMO_SYSTEM_PROMPT_EN,
            session_id=session_id,
        )

    logger.info("voice agent: staged STT->Gemini->TTS path")
    return StreamingSession(
        settings=settings,
        stt=build_stt(settings, auth),
        gpt=build_gpt(settings, auth),
        tts=build_tts(settings, auth),
        translate=build_translate(settings, auth),
        send_json=send_json,
        send_bytes=send_bytes,
        session_id=session_id,
    )


async def run_voice_agent(websocket: WebSocket, settings: Settings, session_id: str) -> None:
    session = _build_session(websocket, settings, session_id)

    started = False
    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break

            if (data := message.get("bytes")) is not None:
                if not started:
                    # Allow audio before an explicit session.start for simple clients.
                    await session.start()
                    started = True
                await session.on_audio_chunk(data)
                continue

            text = message.get("text")
            if text is None:
                continue
            try:
                event = json.loads(text)
            except json.JSONDecodeError:
                continue
            etype = event.get("type")
            if etype == "session.start":
                if not started:
                    session.set_input_sample_rate(event.get("sample_rate"))
                    if hasattr(session, "set_voice"):
                        session.set_voice(event.get("voice"))
                    await session.start()
                    started = True
            elif etype == "user.interrupt":
                await session.on_user_interrupt()
            elif etype in ("audio.end", "session.end"):
                if etype == "session.end":
                    break
    except WebSocketDisconnect:
        logger.info("voice agent disconnected")
    finally:
        await session.close()
