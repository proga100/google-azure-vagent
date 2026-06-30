# voiceagent-google

Uzbek voice agent on **Google** (Gemini Live + Cloud Speech-to-Text `uz-UZ`),
cloned from the Yandex `nigora` pipeline.

**Key fact:** Google Cloud TTS has no Uzbek voice — spoken Uzbek comes from the
**Gemini Live API** (`language_code=uz-UZ`). See [backend/README.md](backend/README.md)
and [MIGRATION_PLAN_GOOGLE.md](MIGRATION_PLAN_GOOGLE.md).

```bash
cp .env.example .env   # set GEMINI_API_KEY (+ GOOGLE_PROJECT_ID/ADC for STT), VOICE_API_TOKEN
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8012 --env-file ../.env   # 8012 avoids the Yandex agent (8000/8010)
```
