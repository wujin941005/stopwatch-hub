#!/usr/bin/env python3
"""
CodexIsland StopWatch bridge — Mac side (Phase 1: data only).

Reads the same local credentials CodexIsland uses and queries the providers'
own usage endpoints, then prints the combined Claude + Codex usage. No secrets
ever leave this machine; later phases push the *computed* numbers to the
StopWatch over BLE.

Recipes mirror ericjypark/codex-island:
  - Codex : GET chatgpt.com/backend-api/wham/usage with the access_token from
            ~/.codex/auth.json.
  - Claude: GET api.anthropic.com/api/oauth/usage with a Claude Code token
            (env -> keychain -> refresh), CLI User-Agent + oauth beta header.

Phase 1 scope: the 5h / weekly utilization windows + reset times + plan.
Cost estimation (session-log parsing) is intentionally deferred to Phase 1b.

Usage:
    python3 codexisland_bridge.py            # human-readable
    python3 codexisland_bridge.py --json     # machine JSON (the BLE payload)
"""

import json
import os
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request

CLAUDE_OAUTH_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
CLAUDE_CODE_USER_AGENT = "claude-code/2.1.121"
HTTP_TIMEOUT = 15

# python.org's Python ships without a populated CA store, so the default
# context fails TLS verification. Prefer certifi's bundle; fall back to the
# system default if certifi isn't installed.
try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CTX = ssl.create_default_context()


# --------------------------------------------------------------------------- #
# HTTP helper
# --------------------------------------------------------------------------- #
def _http(method, url, headers=None, body=None):
    """Return (status, parsed_json_or_None). Never raises on HTTP errors."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT, context=_SSL_CTX) as resp:
            raw = resp.read()
            try:
                return resp.status, json.loads(raw)
            except json.JSONDecodeError:
                return resp.status, None
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return e.code, None
    except (urllib.error.URLError, TimeoutError) as e:
        return 0, {"_transport_error": str(e)}


def _window(used_percent, reset_at):
    """Normalize one window to {pct: 0-100 float, reset_at: epoch_s|None}."""
    return {"pct": round(max(0.0, min(100.0, float(used_percent))), 1),
            "reset_at": reset_at}


def _parse_reset(value):
    """reset_at may be epoch seconds or an ISO-8601 string."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    # ISO string
    try:
        from datetime import datetime
        s = value.replace("Z", "+00:00")
        return int(datetime.fromisoformat(s).timestamp())
    except (ValueError, TypeError):
        return None


# --------------------------------------------------------------------------- #
# Codex
# --------------------------------------------------------------------------- #
def fetch_codex():
    path = os.path.expanduser("~/.codex/auth.json")
    try:
        with open(path) as f:
            tokens = json.load(f).get("tokens") or {}
        token = tokens.get("access_token")
    except (OSError, json.JSONDecodeError):
        token = None
    if not token:
        return {"error": "no codex auth"}

    status, obj = _http(
        "GET", "https://chatgpt.com/backend-api/wham/usage",
        headers={"Authorization": f"Bearer {token}"},
    )
    if status == 401:
        return {"error": "auth expired — codex login"}
    if status != 200 or not isinstance(obj, dict):
        return {"error": f"http {status}"}

    rl = obj.get("rate_limit") or {}

    def win(w):
        d = rl.get(w) or {}
        return _window(d.get("used_percent", 0), _parse_reset(d.get("reset_at")))

    return {
        "plan": obj.get("plan_type"),
        "five_hour": win("primary_window"),
        "weekly": win("secondary_window"),
    }


# --------------------------------------------------------------------------- #
# Claude — keychain credential flow (mirrors CodexIsland's ClaudeCredentials)
# --------------------------------------------------------------------------- #
def _security(args):
    try:
        out = subprocess.run(
            ["/usr/bin/security", *args],
            capture_output=True, text=True, timeout=10,
        )
        return out
    except (OSError, subprocess.TimeoutExpired):
        return None


def _claude_keychain_account():
    """Pull the account name from the `"acct"...="value"` metadata line."""
    out = _security(["find-generic-password", "-s", "Claude Code-credentials"])
    if not out or out.returncode != 0:
        return None
    for line in out.stdout.splitlines():
        line = line.strip()
        if not line.startswith('"acct"'):
            continue
        if "=" not in line:
            return None
        value = line.split("=", 1)[1]
        if value.startswith('"') and value.endswith('"') and len(value) >= 2:
            inner = value[1:-1]
            return inner or None
    return None


def _read_claude_creds():
    """Return dict of the claudeAiOauth keychain payload, or None."""
    account = _claude_keychain_account()
    if not account:
        return None
    out = _security([
        "find-generic-password", "-s", "Claude Code-credentials",
        "-a", account, "-w",
    ])
    if not out or out.returncode != 0:
        return None
    try:
        outer = json.loads(out.stdout.strip())
        oauth = outer.get("claudeAiOauth") or {}
    except json.JSONDecodeError:
        return None
    if not oauth.get("accessToken") or not oauth.get("refreshToken"):
        return None
    return {"account": account, "oauth": oauth}


def _write_claude_creds(account, oauth):
    """Persist rotated tokens back so Claude Code itself doesn't break."""
    payload = json.dumps({"claudeAiOauth": oauth})
    out = _security([
        "add-generic-password", "-U",
        "-s", "Claude Code-credentials", "-a", account, "-w", payload,
    ])
    return bool(out and out.returncode == 0)


def _refresh_claude(refresh_token):
    status, obj = _http(
        "POST", "https://platform.claude.com/v1/oauth/token",
        headers={"Content-Type": "application/json"},
        body={"grant_type": "refresh_token",
              "refresh_token": refresh_token,
              "client_id": CLAUDE_OAUTH_CLIENT_ID},
    )
    if status != 200 or not isinstance(obj, dict):
        return None
    if not obj.get("access_token") or not obj.get("refresh_token"):
        return None
    expires_in = obj.get("expires_in") or 28800
    return {
        "access_token": obj["access_token"],
        "refresh_token": obj["refresh_token"],
        "expires_at": int((time.time() + expires_in) * 1000),
    }


def _probe_claude(token, plan):
    """Single usage-endpoint probe. Returns ('ok', usage) or ('err', reason)."""
    status, obj = _http(
        "GET", "https://api.anthropic.com/api/oauth/usage",
        headers={
            "Authorization": f"Bearer {token}",
            "anthropic-beta": "oauth-2025-04-20",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": CLAUDE_CODE_USER_AGENT,
        },
    )
    if status == 401:
        return "unauthorized", "unauthorized"
    if status == 403:
        return "scope", "re-login: claude /login"
    if status == 429:
        return "err", "rate limited"
    if status != 200 or not isinstance(obj, dict):
        return "err", f"http {status}"
    if isinstance(obj.get("error"), dict) and obj["error"].get("type") == "rate_limit_error":
        return "err", "rate limited"

    def win(key):
        d = obj.get(key) or {}
        raw = d.get("utilization", d.get("used_percent", 0)) or 0
        return _window(raw, _parse_reset(d.get("resets_at")))

    return "ok", {"plan": plan, "five_hour": win("five_hour"), "weekly": win("seven_day")}


def fetch_claude():
    last_error = "auth required — run claude"
    creds = _read_claude_creds()
    plan = (creds["oauth"].get("subscriptionType") if creds else None)

    # 1) env token (set by Claude Desktop for child procs; always fresh)
    env_token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
    if env_token:
        kind, val = _probe_claude(env_token, plan)
        if kind == "ok":
            return val
        if kind == "scope":
            last_error = val  # env scope-insufficient does NOT short-circuit
        elif kind == "err":
            last_error = val

    if creds:
        oauth = creds["oauth"]
        # 2) keychain access token
        kind, val = _probe_claude(oauth["accessToken"], plan)
        if kind == "ok":
            return val
        if kind == "scope":
            return {"error": val}  # refresh can't fix a missing scope
        if kind == "err":
            last_error = val

        # 3) refresh + writeback, then retry
        refreshed = _refresh_claude(oauth["refreshToken"])
        if refreshed:
            oauth = dict(oauth)
            oauth["accessToken"] = refreshed["access_token"]
            oauth["refreshToken"] = refreshed["refresh_token"]
            oauth["expiresAt"] = refreshed["expires_at"]
            _write_claude_creds(creds["account"], oauth)
            kind, val = _probe_claude(refreshed["access_token"], plan)
            if kind == "ok":
                return val
            if kind == "scope":
                return {"error": val}
            if kind == "err":
                last_error = val

    return {"error": last_error}


# --------------------------------------------------------------------------- #
# Cost — parse local session logs (mirrors CodexIsland Pricing + log readers)
# --------------------------------------------------------------------------- #
# Per-million-token USD rates: (input, output, cache_create, cache_read)
_PRICING = {
    "claude-opus-4-8": (5, 25, 6.25, 0.50),
    "claude-opus-4-7": (5, 25, 6.25, 0.50),
    "claude-opus-4-6": (5, 25, 6.25, 0.50),
    "claude-opus-4-5": (5, 25, 6.25, 0.50),
    "claude-sonnet-4-6": (3, 15, 3.75, 0.30),
    "claude-sonnet-4-5": (3, 15, 3.75, 0.30),
    "claude-haiku-4-5": (1, 5, 1.25, 0.10),
    "gpt-5.5": (5, 30, 5, 0.50),
    "gpt-5.4": (2.5, 15, 2.5, 0.25),
    "gpt-5.2": (1.75, 14, 1.75, 0.175),
    "gpt-5.4-mini": (0.75, 4.5, 0.75, 0.075),
    "gpt-5-codex": (1.25, 10, 1.25, 0.125),
}


def _canonical_model(raw):
    # Strip a trailing date suffix "-XXXXXXXX" (dash + 8 digits).
    if len(raw) > 9 and raw[-9] == "-" and raw[-8:].isdigit():
        return raw[:-9]
    return raw


def _cost(model, in_, out, cc, cr):
    r = _PRICING.get(_canonical_model(model))
    if not r:
        return 0.0
    return (in_ * r[0] + out * r[1] + cc * r[2] + cr * r[3]) / 1_000_000


def _today_midnight():
    import datetime
    return datetime.datetime.now().replace(
        hour=0, minute=0, second=0, microsecond=0).timestamp()


def _parse_ts(s):
    try:
        import datetime
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except (ValueError, AttributeError):
        return 0.0


def cost_claude(midnight):
    import glob
    cost, tokens, seen = 0.0, 0, set()
    pat = os.path.expanduser("~/.claude/projects/**/*.jsonl")
    for path in glob.glob(pat, recursive=True):
        try:
            if os.path.getmtime(path) < midnight - 86400:
                continue
            with open(path, "rb") as f:
                for line in f:
                    try:
                        o = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    if o.get("type") != "assistant":
                        continue
                    msg = o.get("message") or {}
                    u = msg.get("usage") or {}
                    model = msg.get("model") or ""
                    if not u or model == "<synthetic>" or model.startswith("synthetic"):
                        continue
                    if _parse_ts(o.get("timestamp", "")) < midnight:
                        continue
                    mid, rid = msg.get("id", ""), o.get("requestId", "")
                    if mid and rid:
                        key = mid + ":" + rid
                        if key in seen:
                            continue
                        seen.add(key)
                    i = u.get("input_tokens", 0) or 0
                    out = u.get("output_tokens", 0) or 0
                    cc = u.get("cache_creation_input_tokens", 0) or 0
                    cr = u.get("cache_read_input_tokens", 0) or 0
                    if not (i or out or cc or cr):
                        continue
                    cost += _cost(model, i, out, cc, cr)
                    tokens += i + out + cc + cr
        except OSError:
            continue
    return cost, tokens


def cost_codex(midnight):
    import glob
    cost, tokens = 0.0, 0
    pat = os.path.expanduser("~/.codex/sessions/**/rollout-*.jsonl")
    for path in glob.glob(pat, recursive=True):
        try:
            if os.path.getmtime(path) < midnight - 86400:
                continue
            cur_model = None
            with open(path, "rb") as f:
                for line in f:
                    try:
                        o = json.loads(line)
                    except (json.JSONDecodeError, ValueError):
                        continue
                    t = o.get("type")
                    if t == "turn_context":
                        m = (o.get("payload") or {}).get("model")
                        if m:
                            cur_model = m
                        continue
                    if t != "event_msg":
                        continue
                    p = o.get("payload") or {}
                    if p.get("type") != "token_count":
                        continue
                    last = (p.get("info") or {}).get("last_token_usage") or {}
                    if not last or _parse_ts(o.get("timestamp", "")) < midnight:
                        continue
                    ti = last.get("input_tokens", 0) or 0
                    cached = last.get("cached_input_tokens", 0) or 0
                    nonc = max(0, ti - cached)
                    out = last.get("output_tokens", 0) or 0
                    if not (nonc or cached or out):
                        continue
                    cost += _cost(cur_model or "gpt-5.4", nonc, out, 0, cached)
                    tokens += nonc + out + cached
        except OSError:
            continue
    return cost, tokens


# --------------------------------------------------------------------------- #
# Combine + render
# --------------------------------------------------------------------------- #
def collect():
    midnight = _today_midnight()
    claude = fetch_claude()
    codex = fetch_codex()
    cc_cost, cc_tok = cost_claude(midnight)
    cx_cost, cx_tok = cost_codex(midnight)
    claude["cost_today"], claude["tokens_today"] = round(cc_cost, 2), cc_tok
    codex["cost_today"], codex["tokens_today"] = round(cx_cost, 2), cx_tok
    return {
        "ts": int(time.time()),
        "claude": claude,
        "codex": codex,
    }


def _fmt_window(w):
    if not w:
        return "—"
    pct = w["pct"]
    if w["reset_at"]:
        mins = max(0, int((w["reset_at"] - time.time()) / 60))
        reset = f"resets in {mins // 60}h{mins % 60:02d}m"
    else:
        reset = "reset ?"
    bar_n = int(round(pct / 5))
    bar = "█" * bar_n + "░" * (20 - bar_n)
    return f"{pct:5.1f}%  {bar}  {reset}"


def render(data):
    lines = []
    for name in ("claude", "codex"):
        p = data[name]
        title = "Claude Code" if name == "claude" else "Codex"
        if "error" in p:
            lines.append(f"{title:12} ⚠ {p['error']}")
            continue
        plan = f" [{p['plan']}]" if p.get("plan") else ""
        lines.append(f"{title:12}{plan}")
        lines.append(f"   5h   {_fmt_window(p.get('five_hour'))}")
        lines.append(f"   7d   {_fmt_window(p.get('weekly'))}")
        lines.append(f"   today  ${p.get('cost_today', 0):.2f}   {p.get('tokens_today', 0):,} tok")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# BLE push — send the compact payload to the StopWatch over Nordic UART Service
# --------------------------------------------------------------------------- #
NUS_RX_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"   # Mac -> watch (usage JSON)
NUS_TX_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"   # watch -> Mac (refresh request)
NUS_SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
BLE_DEVICE_NAME = "CC Island"
MANUAL_REFRESH_MIN_GAP = 5  # seconds — throttle button-triggered refreshes
SCAN_TIMEOUT_S = 20
RECONNECT_DELAY_S = 3
MAX_STALE_PROVIDER_S = 6 * 60 * 60


def _win_pct(w):
    return int(round(w["pct"])) if w else 0


def _reset_min(w):
    if not w or not w.get("reset_at"):
        return 0
    return max(0, int((w["reset_at"] - time.time()) / 60))


def compact(data):
    """Short-key one-line JSON for the watch: c/x -> {h,d,r,$,t}."""
    def prov(p):
        return {
            "h": _win_pct(p.get("five_hour")),
            "d": _win_pct(p.get("weekly")),
            "r": _reset_min(p.get("five_hour")),
            "$": round(p.get("cost_today", 0), 2),
            "t": int(p.get("tokens_today", 0)),
        }
    return json.dumps({"c": prov(data["claude"]), "x": prov(data["codex"])},
                      separators=(",", ":"))


async def ble_loop(interval_s):
    import asyncio
    from bleak import BleakClient, BleakScanner

    refresh = asyncio.Event()   # set when the watch's button asks for a refresh
    disconnected = asyncio.Event()
    last_push = [0.0]
    last_good = {}

    def remember_good(data):
        now = time.time()
        for name in ("claude", "codex"):
            provider = data.get(name) or {}
            if "error" not in provider and provider.get("five_hour") and provider.get("weekly"):
                cached = dict(provider)
                cached["_cached_at"] = now
                last_good[name] = cached

    def with_cached_windows(data):
        now = time.time()
        merged = dict(data)
        for name in ("claude", "codex"):
            provider = dict(data.get(name) or {})
            cached = last_good.get(name)
            if "error" in provider and cached and now - cached.get("_cached_at", 0) <= MAX_STALE_PROVIDER_S:
                restored = {k: v for k, v in cached.items() if not k.startswith("_")}
                restored["cost_today"] = provider.get("cost_today", restored.get("cost_today", 0))
                restored["tokens_today"] = provider.get("tokens_today", restored.get("tokens_today", 0))
                restored["stale"] = True
                merged[name] = restored
            else:
                merged[name] = provider
        return merged

    async def find_watch():
        target_uuid = NUS_SERVICE_UUID.lower()

        def match(device, adv):
            name = device.name or adv.local_name or ""
            service_uuids = [u.lower() for u in (adv.service_uuids or [])]
            return name == BLE_DEVICE_NAME or target_uuid in service_uuids

        dev = await BleakScanner.find_device_by_filter(match, timeout=SCAN_TIMEOUT_S)
        if dev:
            return dev

        # Diagnostic fallback: list visible named devices without failing the loop.
        try:
            seen = await BleakScanner.discover(timeout=5, return_adv=True)
            names = []
            for _, (device, adv) in seen.items():
                name = device.name or adv.local_name
                if name:
                    names.append(name)
            if names:
                print("  visible BLE names:", ", ".join(sorted(set(names))[:12]))
        except Exception as e:  # noqa: BLE001
            print("  scan diagnostic failed:", e)
        return None

    async def connect_watch(dev):
        disconnected.clear()
        client = BleakClient(
            dev,
            disconnected_callback=lambda _client: disconnected.set(),
            services=[NUS_SERVICE_UUID],
            timeout=20,
        )
        await client.connect()
        print(f"connected to {dev.address}")
        try:
            await client.start_notify(NUS_TX_UUID, lambda _h, _d: refresh.set())
        except Exception as e:  # noqa: BLE001
            print("  (button refresh unavailable:", e, ")")
        return client

    async def push(client, tag):
        data = collect()
        remember_good(data)
        payload = compact(with_cached_windows(data))
        try:
            await client.write_gatt_char(NUS_RX_UUID, (payload + "\n").encode(), response=True)
        except Exception:
            await asyncio.sleep(0.5)
            await client.write_gatt_char(NUS_RX_UUID, (payload + "\n").encode(), response=False)
        last_push[0] = time.time()
        print(f"pushed ({tag}):", payload)

    client = None
    while True:
        try:
            if client is None or not client.is_connected:
                print(f"scanning for '{BLE_DEVICE_NAME}'...")
                dev = await find_watch()
                if not dev:
                    print("  not found — is the CC Island app open on the watch? retrying")
                    await asyncio.sleep(5)
                    continue
                client = await connect_watch(dev)
                await push(client, "connect")

            # Wake on either the periodic timer or a button-triggered refresh.
            try:
                refresh_task = asyncio.create_task(refresh.wait())
                disconnect_task = asyncio.create_task(disconnected.wait())
                done, pending = await asyncio.wait(
                    {refresh_task, disconnect_task},
                    timeout=interval_s,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                if disconnect_task in done:
                    print("disconnected")
                    client = None
                    refresh.clear()
                    continue
                if refresh_task in done:
                    refresh.clear()
                    if time.time() - last_push[0] >= MANUAL_REFRESH_MIN_GAP:
                        await push(client, "button")
                    else:
                        print("  refresh throttled (too soon)")
                else:
                    await push(client, "auto")
            except asyncio.TimeoutError:
                await push(client, "auto")
        except Exception as e:  # noqa: BLE001 — keep the loop alive across BLE hiccups
            print("ble error:", e)
            try:
                if client:
                    await client.disconnect()
            except Exception:
                pass
            client = None
            refresh.clear()
            disconnected.clear()
            await asyncio.sleep(RECONNECT_DELAY_S)


def main():
    if "--ble" in sys.argv:
        import asyncio
        i = sys.argv.index("--ble")
        mins = 5.0
        if i + 1 < len(sys.argv):
            try:
                mins = float(sys.argv[i + 1])
            except ValueError:
                pass
        print(f"BLE push every {mins:g} min (Ctrl-C to stop)")
        asyncio.run(ble_loop(int(mins * 60)))
        return

    data = collect()
    if "--json" in sys.argv:
        print(json.dumps(data, indent=2))
    else:
        print(render(data))


if __name__ == "__main__":
    main()
