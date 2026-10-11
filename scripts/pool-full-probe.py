#!/usr/bin/env python3
"""What llama-server answers when a shared (--kv-unified) pool fills. #748.

Usage: scripts/with-gpu-lock scripts/pool-full-probe.py MODEL.gguf [POOL] [SLOTS] [PROMPT_TOKENS] [MAX_TOKENS]
"""
import concurrent.futures
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request

PORT = 18748


def ask(prompt_words: int, max_tokens: int) -> dict:
    body = {"messages": [{"role": "user", "content": "word " * prompt_words + "\nCount on."}],
            "max_tokens": max_tokens, "ignore_eos": True, "temperature": 0}
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/chat/completions",
                                 json.dumps(body).encode(), {"Content-Type": "application/json"})
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            got = json.load(r)
        return {"status": 200, "s": round(time.time() - t, 1), "finish": got["choices"][0].get("finish_reason"),
                "usage": got.get("usage")}
    except urllib.error.HTTPError as exc:
        return {"status": exc.code, "s": round(time.time() - t, 1), "body": exc.read().decode()[:600]}


def main() -> int:
    model = sys.argv[1]
    given = [int(a) for a in sys.argv[2:6]]
    pool, slots, prompt, max_tokens = given + [8192, 3, 2500, 3000][len(given):]
    log = open(f"/tmp/pool-full-probe-{PORT}.log", "w")
    server = subprocess.Popen(["llama-server", "-m", model, "--port", str(PORT), "-c", str(pool),
                               "--parallel", str(slots), "--kv-unified", "--jinja"],
                              stdout=log, stderr=subprocess.STDOUT)
    try:
        for _ in range(240):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=2)
                break
            except Exception:  # noqa: BLE001 - still loading
                time.sleep(1)
        with concurrent.futures.ThreadPoolExecutor(slots) as ex:
            out = list(ex.map(lambda _: ask(prompt, max_tokens), range(slots)))
        print(json.dumps({"pool": pool, "slots": slots, "prompt_words": prompt,
                          "max_tokens": max_tokens, "replies": out}, indent=1))
    finally:
        server.terminate()
        server.wait(30)
        log.close()
    with open(f"/tmp/pool-full-probe-{PORT}.log") as fh:
        print("".join(l for l in fh if any(w in l.lower() for w in ("kv", "slot context", "decode", "error", "n_ctx_slot", "full")))[-4000:])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
