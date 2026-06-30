# Backend — Google + Azure English voice agent (demo)

FastAPI + WebSocket. Gemini Live does STT + reasoning + voice; an Azure Neural
TTS path provides accent-free en-US voices. Public-demo cost guards (per-session
word cap + concurrency) live in `app/config.py` and are enforced in
`app/voice/providers/gemini_live.py` / `app/main.py`.

See the repository root [README.md](../README.md) for setup, run, and the demo
behaviour. Run: `uvicorn app.main:app --reload --port 8013 --env-file ../.env`.
