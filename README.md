# Aasu Line — Ashu's free AI call assistant

One link. Anyone who opens it talks live with Ashu sir's AI assistant:
the same Achird voice as his daily evening voice notes, Hindi/Hinglish/English,
real turn-taking with interruptions, professional and brief. Every call is
recorded; the recording is uploaded to gofile and a notification with the link
and full transcript is published to a private ntfy.sh topic, which the
assistant polls and forwards into Ashu's WhatsApp.

## How a real call reaches it (fully free)

1. Someone calls Ashu's mobile. He doesn't / can't pick up.
2. His phone auto-SMSes the caller the Aasu Line link (MacroDroid macro below).
3. The caller taps the link, taps Call, and talks to the assistant in the browser.
4. Recording + transcript land in Ashu's WhatsApp via the assistant.

Clients who message first (WhatsApp/Instagram/email) can get the link directly.

## Stack (all free, no card)

- Brain: Gemini Live API (free tier, existing key) — speech-to-speech, native
  VAD + barge-in, voice Achird.
- Server: this FastAPI app on Render free web service (no card; sleeps after
  15 min idle, wakes in ~1 min on tap).
- Delivery: gofile upload + ntfy.sh topic (both free, no account, HTTPS only —
  Render blocks SMTP ports).
- Code: github.com/ashuerror/aasu-line

## Render deploy

1. New → Web Service → Public Git repository: the repo URL.
2. Runtime Python; build `pip install -r requirements.txt`; start `python server.py`.
3. Instance type: Free.
4. Env vars: `GEMINI_API_KEY`, `NTFY_TOPIC` (random unguessable string).
5. Live URL: `https://<service>.onrender.com`.

## Ashu's one-time phone steps (MacroDroid, free)

1. Install MacroDroid from Play Store.
2. New macro → Trigger: Call Missed.
3. Action: Send SMS → number `{call_number}` (magic text) → message:
   "Namaste, Ashu sir abhi busy hain. Aap unke assistant se abhi free me baat
   kar sakte hain: <link> — baat ki recording unhe mil jayegi."
4. Allow SMS + phone permissions; exclude MacroDroid from battery optimization.

## Local test

```
pip install -r requirements.txt
GEMINI_API_KEY=... NTFY_TOPIC=test python server.py
python test_client.py   # plays a recorded Hindi caller line end to end
```
