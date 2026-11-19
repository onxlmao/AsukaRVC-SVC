"""Smoke test for the Gradio-hosted AsukaRVC-SVC server (127.0.0.1:8777)."""
import json
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:8777"


def get(path):
    with urllib.request.urlopen(BASE + path, timeout=30) as r:
        return r.status, r.headers, r.read()


def post(path, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data, method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


status, headers, body = get("/api/health")
print("health", status, body.decode())

status, headers, body = get("/api/state")
state = json.loads(body)
print("state", status, "server=", state["engine"]["server"],
      "rvc=", state["rvc"].get("available"), "lexicon=", state["lexicon"])

project = state["defaultProject"]
job = post("/api/render", {"project": project, "options": {"mode": "auto"}})
print("render", job["id"], job["status"])

deadline = time.time() + 180
result = None
while time.time() < deadline:
    status, headers, body = get("/api/job?id=" + job["id"])
    job = json.loads(body)
    if job["status"] in ("done", "error", "cancelled"):
        result = job
        break
    time.sleep(1)

if not result:
    print("TIMEOUT")
    sys.exit(1)

print("job", result["status"], result["message"])
if result.get("error"):
    print("error:", result["error"])
    sys.exit(1)

res = result["result"]
print("audio", res["audioUrl"], "dur", res["duration"], "sr", res["sampleRate"],
      "elapsed", res["elapsed"])
print("rvc", res["rvc"])
print("warnings", res["warnings"])

status, headers, data = get(res["audioUrl"])
print("audio fetch", status, headers.get("Content-Type"), len(data), "bytes")
print("source fetch", get(res["sourceUrl"])[0])

# range request
req = urllib.request.Request(BASE + res["audioUrl"], headers={"Range": "bytes=0-1023"})
with urllib.request.urlopen(req, timeout=30) as r:
    print("range", r.status, r.headers.get("Content-Range"), len(r.read()))

print("g2p", json.loads(get("/api/g2p?text=hello%20world")[2])["phones"][:12])
print("manage", get("/manage")[0])
print("OK")
