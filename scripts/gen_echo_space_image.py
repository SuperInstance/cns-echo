import base64, json, os, re, sys, time, urllib.request

ACCOUNT = "049ff5e84ecf636b53b162cbb580aae6"
MODEL = "@cf/black-forest-labs/flux-1-schnell"
URL = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT}/ai/run/{MODEL}"

PROMPT = ("a dark hallway of many doors (the CNS bus), each door glowing with "
          "the warmth of the conversation behind it, one door glowing amber-red "
          "where the mood crossed a threshold, painterly")

# Read oauth token from wrangler config
token = None
cfg = os.path.expanduser("~/.config/.wrangler/config/default.toml")
try:
    with open(cfg) as f:
        for line in f:
            m = re.search(r'oauth_token\s*=\s*"([^"]+)"', line)
            if m:
                token = m.group(1)
                break
except OSError:
    pass

from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
out_dir = ROOT / "assets" / "images"
out_dir.mkdir(parents=True, exist_ok=True)
out_path = out_dir / "echo-space.png"


def save_png(b64):
    data = base64.b64decode(b64)
    if len(data) <= 1000:
        raise ValueError(f"decoded image too small: {len(data)} bytes")
    with open(out_path, "wb") as f:
        f.write(data)
    print(f"OK saved {len(data)} bytes -> {out_path}")


# 1) Cloudflare FLUX
if token:
    body = json.dumps({"prompt": PROMPT}).encode()
    req = urllib.request.Request(
        URL, data=body,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"})
    last_err = None
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                resp = json.loads(r.read().decode())
            img = resp.get("result", {}).get("image")
            if img:
                save_png(img)
                sys.exit(0)
            print("no image in result:", json.dumps(resp)[:300])
        except urllib.error.HTTPError as e:
            last_err = e
            detail = e.read().decode()[:300]
            print(f"CF attempt {attempt+1}: HTTP {e.code} {detail}")
            if e.code == 429:
                time.sleep(8)
                continue
            break
        except Exception as e:  # noqa: BLE001
            last_err = e
            print(f"CF attempt {attempt+1}: {e}")
            break
else:
    print("no oauth token found")

# 2) DeepInfra fallback
key = os.environ.get("DEEPINFRA_API_KEY")
if not key:
    # source from ~/.bashrc
    try:
        with open(os.path.expanduser("~/.bashrc")) as f:
            for line in f:
                m = re.search(r'DEEPINFRA_API_KEY=(\S+)', line)
                if m:
                    key = m.group(1).strip('"').strip("'")
                    break
    except OSError:
        pass
if key:
    body = json.dumps({
        "prompt": PROMPT,
        "width": 832, "height": 832,
        "num_inference_steps": 4, "seed": 777,
    }).encode()
    req = urllib.request.Request(
        "https://api.deepinfra.com/v1/inference/black-forest-labs/FLUX-1-schnell",
        data=body,
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            resp = json.loads(r.read().decode())
        b64 = resp["images"][0]
        save_png(b64)
        sys.exit(0)
    except Exception as e:  # noqa: BLE001
        print(f"DeepInfra failed: {e}")

print("FALLBACK FAILED — no image generated")
sys.exit(1)
