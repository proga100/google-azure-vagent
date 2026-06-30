"""Gemini Live API — the ONLY Google path to spoken Uzbek.

Google Cloud Text-to-Speech has no Uzbek voice. The Gemini Live API, however,
lists Uzbek among its supported languages, and the **half-cascade** Live model
(``gemini-live-2.5-flash-preview``) honours an explicit ``language_code`` in its
``speech_config`` — so we drive Uzbek output by setting ``language_code=uz-UZ``.
The prebuilt voice name (e.g. ``Aoede``) is only a timbre; the language comes
from the language code, NOT from a Cloud TTS voice id.

This module exposes two entry points over one Live connection shape:

* :func:`synthesize_uzbek` — one-shot *text -> audio* (used by the staged TTS
  provider and by the ``poc_live_audio`` proof-of-concept).
* :class:`GeminiLiveSession` — a full realtime *audio-in -> audio-out*
  conversation with input/output transcription and built-in interruption,
  used directly by the WebSocket agent when ``USE_GEMINI_LIVE_AUDIO`` is on.

If the Live API / audio modality is unavailable on the account, region, or SDK,
calls raise a clear error rather than silently degrading to another language.
"""
from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator, Awaitable, Callable

from app.config import Settings
from app.voice.pipeline.chunker import SentenceChunker
from app.voice.providers.google_auth import GoogleAuth

logger = logging.getLogger("voice.gemini_live")


def _live_config(
    settings: Settings, *, system_prompt: str | None, with_transcription: bool,
    voice: str | None = None,
):
    from google.genai import types

    # Live models only accept the AUDIO modality (TEXT is rejected). In Azure mode
    # we still connect with AUDIO but read the reply from output_transcription and
    # voice it with Azure instead of playing Gemini's own audio.
    cfg: dict = {"response_modalities": ["AUDIO"]}

    # Both families accept a prebuilt voice (the timbre — try different voices to
    # reduce the Uzbek accent). Native-audio models auto-detect the spoken
    # language and REJECT an explicit language_code (they still speak Uzbek when
    # prompted in Uzbek); half-cascade models additionally honour language_code.
    voice_cfg = types.VoiceConfig(
        prebuilt_voice_config=types.PrebuiltVoiceConfig(
            voice_name=voice or settings.gemini_live_voice
        )
    )
    if "native-audio" in settings.gemini_live_model:
        cfg["speech_config"] = types.SpeechConfig(voice_config=voice_cfg)
    else:
        cfg["speech_config"] = types.SpeechConfig(
            language_code=settings.gemini_live_language,
            voice_config=voice_cfg,
        )

    if system_prompt:
        cfg["system_instruction"] = types.Content(
            role="user", parts=[types.Part(text=system_prompt)]
        )
    if with_transcription:
        cfg["input_audio_transcription"] = types.AudioTranscriptionConfig()
        cfg["output_audio_transcription"] = types.AudioTranscriptionConfig()
    return types.LiveConnectConfig(**cfg)


async def synthesize_uzbek(
    settings: Settings,
    auth: GoogleAuth,
    text: str,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> AsyncIterator[bytes]:
    """Yield raw PCM (24 kHz) audio for ``text`` via a one-shot Live turn."""
    if not text.strip():
        return
    from google.genai import types

    client = auth.genai_client()
    config = _live_config(settings, system_prompt=None, with_transcription=False)
    async with client.aio.live.connect(
        model=settings.gemini_live_model, config=config
    ) as session:
        await session.send_client_content(
            turns=types.Content(role="user", parts=[types.Part(text=text)]),
            turn_complete=True,
        )
        async for response in session.receive():
            if cancelled and cancelled():
                break
            data = getattr(response, "data", None)
            if data:
                yield data
            sc = getattr(response, "server_content", None)
            if sc is not None and getattr(sc, "turn_complete", False):
                break


class GeminiLiveSession:
    """Full realtime Uzbek voice conversation over the Gemini Live API.

    Drop-in alternative to the staged ``StreamingSession``: mic PCM in -> Uzbek
    audio out, with input/output transcripts surfaced as ``stt.*`` / ``llm.token``
    events so the existing test client renders unchanged. Interruption is handled
    natively by the Live server (it stops generating when the user speaks).
    """

    def __init__(
        self,
        *,
        settings: Settings,
        auth: GoogleAuth,
        send_json: Callable[[dict], Awaitable[None]],
        send_bytes: Callable[[bytes], Awaitable[None]],
        system_prompt: str,
        session_id: str = "default",
    ) -> None:
        self._s = settings
        self._auth = auth
        self._send_json = send_json
        self._send_bytes = send_bytes
        self._system_prompt = system_prompt
        self._session_id = session_id
        self._input_sample_rate = settings.audio_input_sample_rate_hz
        self._voice = settings.gemini_live_voice
        self._azure_mode = False
        self._azure_voice = ""
        self._azure = None  # lazy AzureTTSProvider
        self._chunker = None  # SentenceChunker for per-sentence Azure synthesis
        self._spoke = False   # sent tts.started for the current Azure turn?
        # Azure runs in its own task so synthesis never blocks reading the Gemini
        # socket (which would trip its keepalive ping timeout). Sentences flow
        # through a queue; a generation counter drops stale work on barge-in.
        self._azure_q: asyncio.Queue | None = None
        self._azure_task: asyncio.Task | None = None
        self._azure_chars = 0  # cumulative chars synthesized (for cost panel)
        self._gen = 0
        # Public-demo cap: count recognized USER words; lock input past the limit.
        self._user_words = 0
        self._turn_text = ""   # accumulates the user's speech for the current turn
        self._demo_locked = False
        self._session = None
        self._cm = None
        self._recv_task: asyncio.Task | None = None

    def set_input_sample_rate(self, sample_rate: int | None) -> None:
        if sample_rate and 8000 <= sample_rate <= 48000:
            self._input_sample_rate = sample_rate

    def set_voice(self, voice: str | None) -> None:
        """Pick the voice. ``azure:<locale-Voice>`` routes the reply through Azure
        Neural TTS (native, accent-free); anything else is a Gemini Live timbre."""
        if not voice:
            return
        if voice.startswith("azure:"):
            self._azure_mode = True
            self._azure_voice = voice.split(":", 1)[1] or "en-US-AvaNeural"
        else:
            self._azure_mode = False
            self._voice = voice

    async def start(self) -> None:
        client = self._auth.genai_client()
        config = _live_config(
            self._s, system_prompt=self._system_prompt, with_transcription=True,
            voice=self._voice,
        )
        # Azure mode uses the half-cascade model (faster reply transcription, its
        # own audio is discarded); native-audio is for the Gemini-voice path.
        model = self._s.gemini_live_model
        if self._azure_mode:
            from app.voice.providers.azure_tts import AzureTTSProvider
            self._azure = AzureTTSProvider(self._s)
            # Smaller first-clause threshold => first Azure audio starts sooner.
            self._chunker = SentenceChunker(
                first_clause_min_chars=self._s.azure_first_clause_chars
            )
            self._azure_q = asyncio.Queue()
            asyncio.create_task(self._azure.prewarm())  # open TLS early
            self._azure_task = asyncio.create_task(self._azure_speak_loop())
            model = self._s.gemini_live_text_model
        self._cm = client.aio.live.connect(model=model, config=config)
        self._session = await self._cm.__aenter__()
        self._recv_task = asyncio.create_task(self._receive_loop())

    async def on_audio_chunk(self, chunk: bytes) -> None:
        # Demo cap reached: drop mic audio so no further Gemini/Azure cost accrues.
        if self._session is None or self._demo_locked:
            return
        from google.genai import types

        await self._session.send_realtime_input(
            audio=types.Blob(
                data=chunk,
                mime_type=f"audio/pcm;rate={self._input_sample_rate}",
            )
        )

    async def on_user_interrupt(self) -> None:
        # Live handles barge-in server-side from the audio stream; nothing to do.
        await self._send_json({"type": "agent.interrupted"})

    @staticmethod
    def _usage_payload(um) -> dict:
        """Flatten Gemini Live ``usage_metadata`` into a ``usage`` event the client
        can price. Token counts are cumulative for the session; modality detail
        (AUDIO vs TEXT) matters because Live bills them at very different rates."""
        def by_modality(details) -> dict:
            out: dict[str, int] = {}
            for d in (details or []):
                mod = getattr(d, "modality", None)
                name = str(getattr(mod, "name", mod) or "").upper() or "OTHER"
                out[name] = out.get(name, 0) + int(getattr(d, "token_count", 0) or 0)
            return out

        prompt = getattr(um, "prompt_token_count", 0) or 0
        response = (
            getattr(um, "response_token_count", None)
            or getattr(um, "candidates_token_count", None)
            or 0
        )
        return {
            "type": "usage",
            "total": int(getattr(um, "total_token_count", 0) or 0),
            "prompt": int(prompt),
            "response": int(response),
            "prompt_modalities": by_modality(getattr(um, "prompt_tokens_details", None)),
            "response_modalities": by_modality(getattr(um, "response_tokens_details", None)),
        }

    async def _receive_loop(self) -> None:
        # google-genai's session.receive() generator ENDS at each turn_complete,
        # so it must be re-entered for the next turn. If we don't, nothing keeps
        # reading the upstream socket and it dies with a keepalive ping timeout
        # (1011) — which is why only the first turn worked. Loop until close().
        try:
            while True:
                async for response in self._session.receive():
                    data = getattr(response, "data", None)
                    # In Azure mode we discard Gemini's own audio — Azure voices
                    # the reply instead (from the output transcription below).
                    if data and not self._azure_mode:
                        await self._send_bytes(data)
                    um = getattr(response, "usage_metadata", None)
                    if um is not None:
                        await self._send_json(self._usage_payload(um))
                    sc = getattr(response, "server_content", None)
                    if sc is None:
                        continue
                    it = getattr(sc, "input_transcription", None)
                    if it is not None and getattr(it, "text", None):
                        await self._send_json({"type": "stt.partial", "text": it.text})
                        # Accumulate the user's speech for this turn (incremental
                        # transcription deltas) to enforce the demo word cap.
                        self._turn_text += it.text
                    ot = getattr(sc, "output_transcription", None)
                    if ot is not None and getattr(ot, "text", None):
                        await self._send_json({"type": "llm.token", "token": ot.text})
                        # Azure mode: queue each completed sentence for the speak
                        # task (non-blocking) as the reply transcription streams.
                        if self._azure_mode:
                            for sentence in self._chunker.push(ot.text):
                                self._azure_q.put_nowait((self._gen, sentence))
                    if getattr(sc, "interrupted", False):
                        if self._azure_mode:
                            self._barge_in_azure()
                        else:
                            self._spoke = False
                        await self._send_json({"type": "agent.interrupted"})
                    if getattr(sc, "turn_complete", False):
                        if self._azure_mode:
                            for sentence in self._chunker.flush():
                                self._azure_q.put_nowait((self._gen, sentence))
                            self._azure_q.put_nowait((self._gen, None))  # turn end
                        else:
                            self._spoke = False
                            await self._send_json({"type": "tts.finished"})
                        # End of exchange: tally the user's words and enforce the cap.
                        await self._check_demo_limit()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("gemini live receive failed")
            await self._send_json(
                {"type": "error", "code": "live", "message": str(exc)}
            )

    async def _check_demo_limit(self) -> None:
        """Tally this turn's user words; lock input once the demo cap is hit."""
        if not self._s.demo_mode or self._demo_locked:
            self._turn_text = ""
            return
        self._user_words += len(self._turn_text.split())
        self._turn_text = ""
        if self._user_words >= self._s.demo_word_limit:
            self._demo_locked = True
            await self._send_json({
                "type": "demo.limit",
                "limit": self._s.demo_word_limit,
                "used": self._user_words,
            })

    def _barge_in_azure(self) -> None:
        """Drop everything queued/in-flight for the current turn (barge-in)."""
        self._gen += 1  # stale items (older gen) are skipped by the speak loop
        if self._azure_q is not None:
            while not self._azure_q.empty():
                try:
                    self._azure_q.get_nowait()
                except asyncio.QueueEmpty:
                    break
        self._spoke = False

    async def _azure_speak_loop(self) -> None:
        """Consume queued sentences and voice them with Azure, in order. Runs in
        its own task so Azure latency never blocks reading the Gemini socket."""
        try:
            while True:
                gen, sentence = await self._azure_q.get()
                if gen != self._gen:
                    continue  # stale (superseded by a barge-in)
                if sentence is None:  # end-of-turn marker
                    self._spoke = False
                    await self._send_json({"type": "tts.finished"})
                    continue
                if not sentence.strip():
                    continue
                if not self._spoke:
                    self._spoke = True
                    await self._send_json({"type": "tts.started"})
                # Azure bills per character; report the running total for the panel.
                self._azure_chars += len(sentence)
                await self._send_json(
                    {"type": "usage_azure", "chars": self._azure_chars}
                )
                try:
                    async for frame in self._azure.synthesize_chunk(
                        sentence, self._azure_voice
                    ):
                        if gen != self._gen:  # barge-in mid-sentence
                            break
                        await self._send_bytes(frame)
                except Exception as exc:  # noqa: BLE001
                    logger.exception("azure tts failed")
                    await self._send_json(
                        {"type": "error", "code": "azure_tts", "message": str(exc)}
                    )
        except asyncio.CancelledError:
            raise

    async def close(self) -> None:
        if self._recv_task:
            self._recv_task.cancel()
        if self._azure_task:
            self._azure_task.cancel()
        if self._cm is not None:
            try:
                await self._cm.__aexit__(None, None, None)
            except Exception:  # noqa: BLE001
                pass
        if self._azure is not None:
            await self._azure.aclose()
        self._session = None
        self._cm = None
