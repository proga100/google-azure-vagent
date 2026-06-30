# google-azure-vagent

**Real-time English voice agent demo** — talk to it and it talks back instantly.
Built on **Google Gemini Live** (speech-to-text + reasoning + voice) with a
switchable voice: Gemini Live timbres **or** **Microsoft Azure** en-US neural
voices. Public portfolio demo for [Flance](https://flance.info), deployed at
`google-azure-vagent.flance.info`.

> Sibling of the private `voiceagent-google` (Uzbek) project — same proven
> pipeline, re-skinned for English with a portfolio UI and an audio-reactive
> orb avatar.

## Highlights
- 🎙️ **Realtime voice↔voice** over WebSocket (Gemini Live, ~1.3s to first audio).
- 🗣️ **Two voice families, switchable live**: Google Gemini timbres and Azure
  en-US neural voices (Ava, Andrew, Emma, Brian) — accent-free native English.
- 🌀 **Animated orb avatar** that reacts to the agent's speech (Web Audio).
- 💸 **Public-demo cost guards**: a hard per-session cap of **15 user words**
  (server-enforced → popup), plus a concurrent-session cap.
- 🔎 A collapsible **developer panel**: live pipeline/model info + token cost + $/min.

## Run locally
```bash
cp .env.example .env          # set GEMINI_API_KEY (+ AZURE_SPEECH_KEY for Azure voices)
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8013 --env-file ../.env
# in another terminal — static client:
cd ../frontend/test-client && python -m http.server 3011
# open http://localhost:3011
```
Or `docker compose up --build` (backend 8013, client 3011).

## How the demo limit works
The server counts recognized **user words**; once the session reaches
`DEMO_WORD_LIMIT` (default 15) it emits a `demo.limit` event, the client shows a
“that's the demo” popup, and the backend **stops processing mic audio** (no more
API cost). The word count and concurrent-session cap are configured in `.env`.

## Voices
- **Gemini** timbres are language-agnostic; English comes from `language_code=en-US`.
- **Azure** mode (`azure:en-US-*Neural`): Gemini does STT + the reply text, Azure
  speaks it (native English, no accent). Reply is synthesized per sentence and
  streamed; Gemini's own audio is discarded in this mode.

## Deploy (follow-up)
See [deploy/nginx-google-azure-vagent.conf](deploy/nginx-google-azure-vagent.conf)
— TLS vhost + WSS proxy template for the subdomain. Set the client's WS URL to
`wss://google-azure-vagent.flance.info/ws/voice` before deploying. Keys live in
the server's `.env` (never committed).

## Layout
`backend/app/voice/providers/` — `gemini_live.py` (realtime session + demo word
cap + Azure-voice mode), `azure_tts.py` (Azure Neural TTS, locale-aware),
`google_*` (auth/STT/Gemini). `frontend/test-client/` — `index.html` (portfolio
UI + orb) and `worklet.js` (mic PCM). Cost guards in `backend/app/config.py`.
