"""Local end-to-end test: plays a pre-recorded Hindi caller line into the WS,
captures the assistant's audio replies, writes WAVs for inspection."""
import asyncio
import json
import sys
import time
import wave

import websockets

WS_URL = sys.argv[1] if len(sys.argv) > 1 else "ws://127.0.0.1:7860/ws"
CALLER_PCM = "/tmp/caller.pcm"


async def collect(ws, idle_s, max_s, sink, transcripts):
    last_audio = None
    start = time.time()
    while time.time() - start < max_s:
        try:
            msg = await asyncio.wait_for(ws.recv(), timeout=1.0)
        except asyncio.TimeoutError:
            if last_audio and time.time() - last_audio > idle_s:
                return
            continue
        if isinstance(msg, bytes):
            sink.append(msg)
            last_audio = time.time()
        else:
            m = json.loads(msg)
            transcripts.append(m)
            if m.get("ended"):
                return


async def main():
    greeting, reply, transcripts = [], [], []
    async with websockets.connect(WS_URL, max_size=None) as ws:
        await collect(ws, idle_s=3.0, max_s=30, sink=greeting, transcripts=transcripts)
        print(f"greeting: {len(greeting)} chunks")
        with open(CALLER_PCM, "rb") as f:
            pcm = f.read()
        for i in range(0, len(pcm), 3200):
            await ws.send(pcm[i:i + 3200])
            await asyncio.sleep(0.1)
        print("caller line sent")
        await collect(ws, idle_s=4.0, max_s=45, sink=reply, transcripts=transcripts)
        print(f"reply: {len(reply)} chunks")

    for name, chunks in (("greeting", greeting), ("reply", reply)):
        data = b"".join(chunks)
        with wave.open(f"/tmp/assistant_{name}.wav", "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(24000)
            w.writeframes(data)
        print(f"/tmp/assistant_{name}.wav: {len(data)/48000:.1f}s")
    print("control messages:", transcripts)


asyncio.run(main())
