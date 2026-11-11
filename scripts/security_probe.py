"""Black-box security probe against a RUNNING stack (docker compose up). Writes nothing except harmless rejected requests.
Usage: python scripts/security_probe.py > docs/security_probe_results.json   (needs at least one run to exist)
It reads LLM_API_KEY from .env only to prove the key never appears in any ops endpoint; the key is never printed."""
import json, os, httpx

A = os.environ.get("API_URL", "http://localhost:8000")
W = os.environ.get("WEB_URL", "http://localhost:8080") + "/api"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUN = httpx.get(f"{A}/v1/runs?limit=1").json()["runs"][0]["run_id"]
res = []


def rec(name, ok, detail=""):
    res.append({"check": name, "pass": bool(ok), "detail": detail})


c = httpx.Client(timeout=20)

# path traversal / id abuse
r = c.get(f"{A}/v1/runs/..%2F..%2Fetc%2Fpasswd/documents/1"); rec("traversal in run_id on download -> 404", r.status_code == 404, r.status_code)
r = c.get(f"{A}/v1/runs/{RUN}/documents/1%2F..%2F..%2Fx"); rec("traversal in doc_id -> 404/422", r.status_code in (404, 422), r.status_code)
r = c.get(f"{A}/v1/runs/{RUN}/documents/99999"); rec("unknown document -> 404", r.status_code == 404, r.status_code)
r = c.get(f"{A}/v1/runs/{RUN}/documents/-1"); rec("negative document id -> 404", r.status_code == 404, r.status_code)

# malformed / hostile bodies never produce a 500 or a stack trace
for name, body, ct in [("invalid json", b"{not json", "application/json"), ("json array", b"[1,2]", "application/json"),
                       ("sql-ish student_ref", json.dumps({"student_ref": "SYN-1'; DROP TABLE runs;--"}).encode(), "application/json"),
                       ("wrong content type", b"hello", "text/plain"), ("empty body", b"", "application/json")]:
    r = c.post(f"{A}/v1/petitions", content=body, headers={"content-type": ct})
    rec(f"malformed petition ({name}) -> 422 without traceback", r.status_code == 422 and "Traceback" not in r.text and "File \"" not in r.text, r.status_code)
r = c.get(f"{A}/v1/runs"); rec("runs table intact after the SQL-ish payload", r.status_code == 200 and r.json()["runs"], r.status_code)
big = json.dumps({"petition_text": "x" * 70000}).encode()
r = c.post(f"{A}/v1/petitions", content=big, headers={"content-type": "application/json"}); rec("oversized petition body -> 413", r.status_code == 413, r.status_code)
r = c.post(f"{W}/v1/petitions", content=b"x" * (4 * 1024 * 1024), headers={"content-type": "application/json"}); rec("4 MB body through nginx -> 413", r.status_code == 413, r.status_code)

# uploads
files = {
    "html disguised as pdf": ("a.pdf", b"<html><script>alert(1)</script>", "application/pdf"),
    "exe disguised as png": ("a.png", b"MZ\x90\x00", "image/png"),
    "svg": ("a.svg", b"<svg xmlns='http://www.w3.org/2000/svg'><script>1</script></svg>", "image/svg+xml"),
    "empty file": ("e.pdf", b"", "application/pdf"),
}
for name, f in files.items():
    r = c.post(f"{A}/v1/runs/{RUN}/documents", files={"file": f}); rec(f"upload {name} -> 415", r.status_code == 415, r.status_code)
r = c.post(f"{A}/v1/runs/{RUN}/documents", files={"file": ("big.pdf", b"%PDF-" + b"0" * (2 * 1024 * 1024 + 10), "application/pdf")}); rec("oversized upload -> 413", r.status_code == 413, r.status_code)
r = c.post(f"{A}/v1/runs/run_nope/documents", files={"file": ("a.pdf", b"%PDF-1", "application/pdf")}); rec("upload to unknown run -> 404", r.status_code == 404, r.status_code)
r = c.post(f"{A}/v1/runs/{RUN}/documents"); rec("upload without a file -> 422", r.status_code == 422, r.status_code)

# decision endpoint validation (no decision is written)
r = c.post(f"{A}/v1/runs/{RUN}/examiner-decision", json={"decision": "grant-under-provision", "note": "long enough note", "examiner_label": "ab"}); rec("AI route vocabulary rejected as a human decision -> 422", r.status_code == 422, r.status_code)
r = c.post(f"{A}/v1/runs/{RUN}/examiner-decision", json={"decision": "accept-petition", "note": "short", "examiner_label": "ab"}); rec("too-short note -> 422", r.status_code == 422, r.status_code)

# download headers
r = c.get(f"{A}/v1/runs/{RUN}/documents/1")
rec("download served as attachment with nosniff + CSP", r.status_code == 200 and "attachment" in r.headers.get("content-disposition", "") and r.headers.get("x-content-type-options") == "nosniff" and "default-src 'none'" in r.headers.get("content-security-policy", ""), dict(r.headers))

# web headers
r = c.get(W[:-4] + "/")
rec("web: nosniff + frame deny + referrer policy", r.headers.get("x-content-type-options") == "nosniff" and r.headers.get("x-frame-options") == "DENY" and r.headers.get("referrer-policy") == "no-referrer", {k: v for k, v in r.headers.items() if k.startswith("x-") or k == "referrer-policy"})

# data exposure: metrics / health / system never contain petition text, the key or the provider URL
env = {}
for l in open(os.path.join(ROOT, ".env")):
    if "=" in l and not l.startswith("#"):
        k, v = l.strip().split("=", 1); env[k] = v
key = env.get("LLM_API_KEY", "")
bodies = {p: c.get(f"{A}{p}").text for p in ("/metrics", "/readyz", "/v1/system", "/v1/stats", "/v1/corpus", "/openapi.json")}
rec("API key not present in any ops endpoint", key and all(key not in b for b in bodies.values()))
rec("LLM base URL not present in ops endpoints", all(env.get("LLM_BASE_URL", "zzz") not in b for b in bodies.values()))
rec("no petition text in /metrics", "hospitalised" not in bodies["/metrics"])

# CORS: no wildcard
r = c.options(f"{A}/v1/runs", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "GET"})
rec("CORS not enabled for arbitrary origins", "access-control-allow-origin" not in {k.lower() for k in r.headers}, r.status_code)

# rate limit on decision endpoint (uses a unique client id; stays below the limit with 422s which still count)
codes = [c.post(f"{A}/v1/runs/{RUN}/examiner-decision", json={"decision": "x"}, headers={"x-client-id": "sec-probe"}).status_code for _ in range(40)]
rec("decision endpoint rate-limited under bursts (429 seen)", 429 in codes, sorted(set(codes)))

print(json.dumps({"passed": sum(r["pass"] for r in res), "total": len(res), "results": res}, indent=1, default=str)[:6000])
