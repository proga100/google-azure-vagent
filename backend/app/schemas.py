"""WebSocket control-event schemas (JSON).

Audio travels as raw binary WebSocket frames (PCM16) and is NOT modelled here:
inbound binary = mic audio (16k), outbound binary = TTS audio (48k). Only the
JSON control plane is validated by these pydantic models.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Client -> Server
# ---------------------------------------------------------------------------


class SessionStart(BaseModel):
    type: Literal["session.start"] = "session.start"
    sample_rate: int = 16000
    language: str = "en-US"
    voice: str = "Aoede"


class AudioEnd(BaseModel):
    type: Literal["audio.end"] = "audio.end"


class UserInterrupt(BaseModel):
    type: Literal["user.interrupt"] = "user.interrupt"


class SessionEnd(BaseModel):
    type: Literal["session.end"] = "session.end"


# ---------------------------------------------------------------------------
# Server -> Client
# ---------------------------------------------------------------------------


class STTPartial(BaseModel):
    type: Literal["stt.partial"] = "stt.partial"
    text: str


class STTFinal(BaseModel):
    type: Literal["stt.final"] = "stt.final"
    text: str


class IntentPartial(BaseModel):
    type: Literal["intent.partial"] = "intent.partial"
    data: dict[str, Any] = Field(default_factory=dict)


class LLMToken(BaseModel):
    type: Literal["llm.token"] = "llm.token"
    token: str


class TTSStarted(BaseModel):
    type: Literal["tts.started"] = "tts.started"


class TTSFinished(BaseModel):
    type: Literal["tts.finished"] = "tts.finished"


class AgentInterrupted(BaseModel):
    type: Literal["agent.interrupted"] = "agent.interrupted"


class LatencyMetrics(BaseModel):
    type: Literal["latency.metrics"] = "latency.metrics"
    marks: dict[str, float] = Field(default_factory=dict)
    deltas: dict[str, float] = Field(default_factory=dict)


class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    code: str
    message: str


class DemoLimit(BaseModel):
    """Sent when the per-session user-word cap is reached; client shows a popup."""
    type: Literal["demo.limit"] = "demo.limit"
    limit: int
    used: int


class DemoBusy(BaseModel):
    """Sent when the concurrent-session cap rejects a new connection."""
    type: Literal["demo.busy"] = "demo.busy"
    message: str = "Demo is busy, please try again shortly."
