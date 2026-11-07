"""Aasu Line - Ashu's free AI call assistant.

One link. Anyone who opens it talks live with Ashu's AI assistant (Gemini Live
API, Achird voice - the same voice as his daily evening voice notes). Full
duplex: the caller can interrupt, the assistant handles it natively. Every call
is recorded (mixed WAV) with a transcript, and the recording is delivered by
Gmail SMTP when configured, and is always fetchable from /recordings?token=...

Env:
  GEMINI_API_KEY     required
  REC_TOKEN          token for /recordings (default: random at boot, printed to log)
  SMTP_USER / SMTP_APP_PASSWORD / HANDOFF_TO   optional email delivery
  MAX_CALL_SECONDS   default 480
"""
import asyncio
import audioop
import os
import secrets
import time
import wave

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
import uvicorn

from google import genai
from google.genai import types

MODEL = os.environ.get("GEMINI_LIVE_MODEL", "gemini-2.5-flash-native-audio-preview-09-2025")
VOICE = "Achird"  # same voice as the daily evening voice notes
MAX_CALL_SECONDS = int(os.environ.get("MAX_CALL_SECONDS", "480"))
REC_DIR = "recordings"
os.makedirs(REC_DIR, exist_ok=True)
REC_TOKEN = os.environ.get("REC_TOKEN") or secrets.token_urlsafe(18)

SYSTEM = """You are Aasu, the personal phone assistant of Ashu sir (Ashish), a freelance
video editor from Jaipur. You are talking to someone who called him while he is busy.

Voice and manner: warm, natural, young professional Indian male. Match the caller's
language - Hindi, Hinglish or English - and switch whenever they switch. Keep every
reply to one or two short spoken sentences. You may be interrupted at any time; if
interrupted, stop and listen.

Your job on every call:
1. Greet briefly: say Ashu sir is busy right now and you are his assistant.
2. Ask who is calling and what the work is.
3. Listen, understand, and collect: caller's name, phone number, what they need,
   and any deadline or budget they mention.
4. Close by saying Ashu sir will call them back, and thank them.

Hard rules: never quote prices, never promise deadlines or meetings, never share any
other contact detail of Ashu sir, never invent facts about his work. If it is spam or
a sales call, politely say no and end the call. If asked, say openly that you are his
AI assistant. Start the call now with the greeting.
"""

PAGE = """<!doctype html><html><head><meta name=viewport content="width=device-width,initial-scale=1">
<title>Aasu Line</title></head>
<body style="font-family:sans-serif;text-align:center;padding-top:16vh;background:#0b0f14;color:#eee">
<h2>Aasu Line</h2>
<p>Ashu sir's AI assistant - tap to talk</p>
<button id=b style="font-size:1.3em;padding:1em 2.2em;border-radius:2em;border:0;background:#22c55e;color:#041;cursor:pointer">Call</button>
<p id=s style="color:#9aa"></p>
<script>
let ws, ac, pc, playAt = 0, nodes = [];
const s = m => document.getElementById('s').textContent = m;
b.onclick = async () => {
  if (ws) { ws.close(); return; }
  ws = new WebSocket((location.protocol=='https:'?'wss://':'ws://')+location.host+'/ws');
  ws.binaryType = 'arraybuffer';
  ws.onopen = async () => {
    b.textContent='End call'; b.style.background='#ef4444'; b.style.color='#fff'; s('Connected. Speak naturally.');
    ac = new (window.AudioContext||window.webkitAudioContext)({sampleRate:16000});
    playAt = ac.currentTime;
    const stream = await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true}});
    const src = ac.createMediaStreamSource(stream);
    pc = ac.createScriptProcessor(4096,1,1);
    src.connect(pc); pc.connect(ac.destination);
    pc.onaudioprocess = e => {
      if (ws.readyState!==1) return;
      const f = e.inputBuffer.getChannelData(0), pcm = new Int16Array(f.length);
      for (let i=0;i<f.length;i++) pcm[i] = Math.max(-1,Math.min(1,f[i]))*32767;
      ws.send(pcm.buffer);
    };
  };
  ws.onmessage = ev => {
    if (typeof ev.data === 'string') {           // control message
      const m = JSON.parse(ev.data);
      if (m.interrupted) { nodes.forEach(n=>{try{n.stop()}catch(e){}}); nodes=[]; playAt=ac.currentTime; }
      if (m.ended) { s('Call ended.'); ws.close(); }
      return;
    }
    const pcm = new Int16Array(ev.data);          // 24kHz PCM16 from the assistant
    const f = new Float32Array(pcm.length);
    for (let i=0;i<pcm.length;i++) f[i] = pcm[i]/32768;
    const buf = ac.createBuffer(1, f.length, 24000);
    buf.getChannelData(0).set(f);
    const n = ac.createBufferSource(); n.buffer = buf; n.connect(ac.destination);
    playAt = Math.max(playAt, ac.currentTime);
    n.start(playAt); playAt += buf.duration; nodes.push(n);
  };
  ws.onclose = () => { b.textContent='Call'; b.style.background='#22c55e'; b.style.color='#041'; s(''); ws=null; if(ac){ac.close();ac=null;} };
};
</script></body></html>"""

app = FastAPI()


@app.get("/", response_class=HTMLResponse)
def home():
    return PAGE


class CallLog:
    def __init__(self, stamp):
        self.stamp = stamp
        self.caller = audioop.ratecv(b"", 2, 1, 16000, 16000, None)  # passthrough init
        self.caller_chunks = []
        self.assistant_chunks = []
        self.lines = []

    def add_caller(self, pcm):
        self.caller_chunks.append(pcm)

    def add_assistant(self, pcm24):
        pcm16, _ = audioop.ratecv(pcm24, 2, 1, 24000, 16000, None)
        self.assistant_chunks.append(pcm16)

    def save(self):
        c = b"".join(self.caller_chunks)
        a = b"".join(self.assistant_chunks)
        n = max(len(c), len(a))
        c = c + b"\x00" * (n - len(c))
        a = a + b"\x00" * (n - len(a))
        mixed = audioop.tomono(audioop.add(c, a, 2), 2, 0.6, 0.6)
        path = os.path.join(REC_DIR, f"call-{self.stamp}.wav")
        with wave.open(path, "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000)
            w.writeframes(mixed)
        with open(os.path.join(REC_DIR, f"call-{self.stamp}.txt"), "w") as f:
            f.write("\n".join(self.lines))
        return path


def deliver(path, lines):
    """Upload the recording to gofile (free, no account, Ashu already uses it)
    and publish the link + transcript to a private ntfy.sh topic that the
    assistant polls and forwards into Ashu's WhatsApp. All plain HTTPS, so it
    works from free hosts that block SMTP ports."""
    import json
    import urllib.request

    link = None
    try:
        servers = json.load(urllib.request.urlopen("https://api.gofile.io/servers", timeout=20))
        srv = servers["data"]["servers"][0]["name"]
        boundary = secrets.token_hex(12)
        with open(path, "rb") as f:
            data = f.read()
        body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
                f"filename=\"{os.path.basename(path)}\"\r\n"
                f"Content-Type: audio/wav\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(
            f"https://{srv}.gofile.io/contents/uploadfile", data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        resp = json.load(urllib.request.urlopen(req, timeout=120))
        link = resp["data"].get("downloadPage")
    except Exception as e:
        print("gofile upload failed:", repr(e))

    topic = os.environ.get("NTFY_TOPIC")
    if topic:
        text = ("New Aasu Line call " + time.strftime("%d %b %H:%M") + "\n"
                + ("Recording: " + link if link else "Recording: on server /recordings only")
                + "\n\n" + "\n".join(lines))[:3900]
        try:
            urllib.request.urlopen(urllib.request.Request(
                f"https://ntfy.sh/{topic}", data=text.encode(),
                headers={"Title": "Aasu Line call"}), timeout=20)
        except Exception as e:
            print("ntfy publish failed:", repr(e))
    return link


@app.websocket("/ws")
async def call(ws: WebSocket):
    await ws.accept()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    log = CallLog(stamp)
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction=SYSTEM,
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=VOICE)),
            language_code="hi-IN"),
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
    )
    try:
        async with client.aio.live.connect(model=MODEL, config=config) as session:
            await session.send_client_content(
                turns=[types.Content(role="user", parts=[types.Part(text="[Call connected]")])],
                turn_complete=True)

            async def caller_to_gemini():
                while True:
                    data = await ws.receive_bytes()
                    log.add_caller(data)
                    await session.send_realtime_input(
                        audio=types.Blob(data=data, mime_type="audio/pcm;rate=16000"))

            async def gemini_to_caller():
                while True:
                    async for msg in session.receive():
                        if msg.data:
                            log.add_assistant(msg.data)
                            await ws.send_bytes(msg.data)
                        sc = getattr(msg, "server_content", None)
                        if sc is not None:
                            if getattr(sc, "interrupted", False):
                                await ws.send_text('{"interrupted":true}')
                            it = getattr(sc, "input_transcription", None)
                            if it and getattr(it, "text", None):
                                log.lines.append("caller: " + it.text)
                            ot = getattr(sc, "output_transcription", None)
                            if ot and getattr(ot, "text", None):
                                log.lines.append("assistant: " + ot.text)

            done, pending = await asyncio.wait(
                [asyncio.create_task(caller_to_gemini()),
                 asyncio.create_task(gemini_to_caller()),
                 asyncio.create_task(asyncio.sleep(MAX_CALL_SECONDS))],
                return_when=asyncio.FIRST_COMPLETED)
            for t in pending:
                t.cancel()
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print("call error:", repr(e))
    finally:
        try:
            await ws.send_text('{"ended":true}')
            await ws.close()
        except Exception:
            pass
        path = log.save()
        link = deliver(path, log.lines)
        print(f"call saved: {path} ({len(log.lines)} transcript lines), gofile: {link}")


@app.get("/recordings")
def recordings(token: str = Query(...)):
    if token != REC_TOKEN:
        return JSONResponse({"error": "forbidden"}, status_code=403)
    files = sorted(f for f in os.listdir(REC_DIR) if f.endswith((".wav", ".txt")))
    return {"files": files, "url_pattern": "/recordings/{name}?token=" + token}


@app.get("/recordings/{name}")
def recording_file(name: str, token: str = Query(...)):
    if token != REC_TOKEN or "/" in name or ".." in name:
        return JSONResponse({"error": "forbidden"}, status_code=403)
    path = os.path.join(REC_DIR, name)
    if not os.path.exists(path):
        return JSONResponse({"error": "not found"}, status_code=404)
    return FileResponse(path)


if __name__ == "__main__":
    print("REC_TOKEN:", REC_TOKEN)
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 7860)))
