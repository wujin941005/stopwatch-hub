#!/usr/bin/env python3
"""
CC Island StopWatch bridge — one bridge, two transports, three providers.

Data is always computed locally (credentials and logs never leave this
machine); only the *finished* numbers are sent to the watch — either pushed
over BLE (Nordic UART, the original transport) or served over HTTP for the
watch to poll over Wi-Fi.

Providers:
  - Claude  : GET api.anthropic.com/api/oauth/usage (env, macOS Keychain, or
              ~/.claude/.credentials.json OAuth) + today's local log cost.
  - Codex   : GET chatgpt.com/backend-api/wham/usage via ~/.codex/auth.json
              + today's cost from ~/.codex/sessions logs.
  - OpenCode: read-only SQLite from its XDG data directory — message token
              counters are repriced to the same API-equivalent basis.

API-equivalent values use OpenRouter's public model catalog, cached locally for
offline operation. No credentials, prompts, or usage data are sent to
OpenRouter.

Optional system stats (CPU / memory / disk / network) support native Windows,
macOS, and Linux; WSL reads the Windows host through PowerShell. Set
CC_SYSTEM_MONITOR=true to collect them and include the watch's system page.

Usage:
    python3 codexisland_bridge.py                 # human-readable one-shot
    python3 codexisland_bridge.py --json          # full machine JSON
    python3 codexisland_bridge.py --serve [port]  # WiFi polling server (default 8080)
    python3 codexisland_bridge.py --ble [mins]    # BLE push every N minutes (needs bleak)
"""

import argparse
import glob
import json
import math
import os
import platform
import re
import ssl
import subprocess
import sys
import threading
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

DEFAULT_OPENCODE_DB = "~/.local/share/opencode/opencode.db"

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


def _env_bool(name, default=False):
    """Parse a conventional boolean environment variable."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    value = raw.strip().lower()
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    print(f"WARN: {name}={raw!r} is not a boolean; using {default}",
          file=sys.stderr)
    return default


def system_monitor_enabled():
    """Whether host metrics should be collected and sent to the watch."""
    return _env_bool("CC_SYSTEM_MONITOR", False)


# --------------------------------------------------------------------------- #
# Cross-platform host paths
# --------------------------------------------------------------------------- #
_WINDOWS_HOME_PROBED = False
_WINDOWS_HOME = None


def _is_wsl():
    if not sys.platform.startswith("linux"):
        return False
    if os.environ.get("WSL_DISTRO_NAME"):
        return True
    try:
        return "microsoft" in platform.release().lower()
    except OSError:
        return False


def _powershell_executable():
    wsl_path = "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
    return wsl_path if os.path.exists(wsl_path) else "powershell.exe"


def _windows_to_wsl_path(value):
    """Translate C:\\Users\\... paths when the bridge itself runs in WSL."""
    value = (value or "").strip().strip('"')
    if not _is_wsl():
        return value
    match = re.match(r"^([A-Za-z]):[\\/](.*)$", value)
    if not match:
        return value
    drive, tail = match.groups()
    tail = tail.replace("\\", "/")
    return f"/mnt/{drive.lower()}/{tail}"


def _expand_host_path(value):
    value = _windows_to_wsl_path(value)
    return os.path.normpath(os.path.expanduser(os.path.expandvars(value)))


def _windows_home():
    """Return the mounted Windows profile directory when running under WSL."""
    global _WINDOWS_HOME_PROBED, _WINDOWS_HOME
    if _WINDOWS_HOME_PROBED:
        return _WINDOWS_HOME
    _WINDOWS_HOME_PROBED = True
    if not _is_wsl():
        return None
    try:
        out = subprocess.run(
            [_powershell_executable(), "-NoProfile", "-NonInteractive",
             "-Command", "[Environment]::GetFolderPath('UserProfile')"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=8,
        )
        line = out.stdout.strip().splitlines()[-1] if out.stdout.strip() else ""
        path = _expand_host_path(line)
        if line and os.path.isdir(path):
            _WINDOWS_HOME = path
    except (OSError, subprocess.TimeoutExpired):
        pass
    return _WINDOWS_HOME


def _host_homes():
    """Local home plus the Windows profile mounted into WSL, without dupes."""
    values = [_expand_host_path("~")]
    windows = _windows_home()
    if windows:
        values.append(windows)
    out = []
    seen = set()
    for value in values:
        key = os.path.normcase(os.path.realpath(value))
        if key not in seen:
            seen.add(key)
            out.append(value)
    return out


def _unique_paths(paths):
    out = []
    seen = set()
    for path in paths:
        path = _expand_host_path(path)
        key = os.path.normcase(os.path.realpath(path))
        if key not in seen:
            seen.add(key)
            out.append(path)
    return out


def _codex_roots():
    roots = []
    configured = os.environ.get("CODEX_HOME", "").strip()
    if configured:
        roots.append(configured)
    roots.extend(os.path.join(home, ".codex") for home in _host_homes())
    return _unique_paths(roots)


def _claude_roots():
    roots = []
    configured = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    if configured:
        roots.append(configured)
    roots.extend(os.path.join(home, ".claude") for home in _host_homes())
    return _unique_paths(roots)


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
    token = None
    for root in _codex_roots():
        try:
            with open(os.path.join(root, "auth.json")) as f:
                tokens = json.load(f).get("tokens") or {}
            token = tokens.get("access_token")
        except (OSError, json.JSONDecodeError):
            continue
        if token:
            break
    if not token:
        return {"error": "no codex auth"}

    status, obj = _http(
        "GET", "https://chatgpt.com/backend-api/wham/usage",
        headers={"Authorization": f"Bearer {token}"},
    )
    if status == 401:
        return {"error": "auth expired — codex login"}
    if status == 0:
        detail = str((obj or {}).get("_transport_error", "")).lower()
        if "network is unreachable" in detail:
            return {"error": "network unreachable"}
        if "timed out" in detail:
            return {"error": "network timeout"}
        return {"error": "network unavailable"}
    if status != 200 or not isinstance(obj, dict):
        return {"error": f"http {status}"}

    rl = obj.get("rate_limit") or {}

    def win(w):
        d = rl.get(w)
        if not d:
            return None
        wnd = _window(d.get("used_percent", 0), _parse_reset(d.get("reset_at")))
        if d.get("limit_window_seconds"):
            wnd["window_seconds"] = d["limit_window_seconds"]
        return wnd

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


def _read_claude_keychain_creds():
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
    return {"source": "keychain", "account": account, "oauth": oauth}


def _write_claude_keychain_creds(account, oauth):
    payload = json.dumps({"claudeAiOauth": oauth})
    out = _security([
        "add-generic-password", "-U",
        "-s", "Claude Code-credentials", "-a", account, "-w", payload,
    ])
    return bool(out and out.returncode == 0)


def _read_claude_file_creds():
    """Claude Code stores OAuth here on Linux/Windows and some headless Macs."""
    for root in _claude_roots():
        path = os.path.join(root, ".credentials.json")
        try:
            with open(path) as f:
                outer = json.load(f)
            oauth = outer.get("claudeAiOauth") or {}
        except (OSError, json.JSONDecodeError, AttributeError):
            continue
        if oauth.get("accessToken") and oauth.get("refreshToken"):
            return {"source": "file", "path": path, "oauth": oauth}
    return None


def _read_claude_creds():
    # Claude Code normally uses Keychain on macOS and a credentials file on
    # Linux/Windows. Accept either so headless and migrated installs also work.
    if sys.platform == "darwin":
        return _read_claude_keychain_creds() or _read_claude_file_creds()
    return _read_claude_file_creds() or _read_claude_keychain_creds()


def _write_claude_file_creds(path, oauth):
    tmp = f"{path}.cc-island-{os.getpid()}.tmp"
    try:
        try:
            with open(path) as f:
                outer = json.load(f)
            if not isinstance(outer, dict):
                outer = {}
        except (OSError, json.JSONDecodeError):
            outer = {}
        outer["claudeAiOauth"] = oauth
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(tmp, "w") as f:
            json.dump(outer, f, separators=(",", ":"))
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, path)
        return True
    except OSError:
        return False
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        except OSError:
            # A failed cleanup must not hide the original credential result.
            pass


def _write_claude_creds(creds, oauth):
    if creds.get("source") == "keychain":
        return _write_claude_keychain_creds(creds["account"], oauth)
    if creds.get("source") == "file":
        return _write_claude_file_creds(creds["path"], oauth)
    return False


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

    env_token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN")
    if env_token:
        kind, val = _probe_claude(env_token, plan)
        if kind == "ok":
            return val
        if kind == "scope":
            last_error = val
        elif kind == "err":
            last_error = val

    if creds:
        oauth = creds["oauth"]
        kind, val = _probe_claude(oauth["accessToken"], plan)
        if kind == "ok":
            return val
        if kind == "scope":
            return {"error": val}
        if kind == "err":
            last_error = val

        refreshed = _refresh_claude(oauth["refreshToken"])
        if refreshed:
            oauth = dict(oauth)
            oauth["accessToken"] = refreshed["access_token"]
            oauth["refreshToken"] = refreshed["refresh_token"]
            oauth["expiresAt"] = refreshed["expires_at"]
            _write_claude_creds(creds, oauth)
            kind, val = _probe_claude(refreshed["access_token"], plan)
            if kind == "ok":
                return val
            if kind == "scope":
                return {"error": val}
            if kind == "err":
                last_error = val

    return {"error": last_error}


# --------------------------------------------------------------------------- #
# OpenCode — read-only SQLite, auto-detected from its cross-platform XDG data
# --------------------------------------------------------------------------- #
def _day_start_ms(days_ago=0):
    """Epoch milliseconds for local midnight `days_ago` calendar days back."""
    import datetime
    now = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    start = now - datetime.timedelta(days=days_ago)
    return int(start.timestamp() * 1000)


def _opencode_query(con, since_ms):
    """Legacy fallback for OpenCode databases without message-level usage."""
    row = con.execute(
        """
        SELECT COUNT(*),
               COALESCE(SUM(cost), 0),
               COALESCE(SUM(tokens_input), 0) + COALESCE(SUM(tokens_output), 0)
                 + COALESCE(SUM(tokens_reasoning), 0)
                 + COALESCE(SUM(tokens_cache_read), 0) + COALESCE(SUM(tokens_cache_write), 0)
        FROM session
        WHERE time_created >= ?
        """,
        (since_ms,),
    ).fetchone()
    return {"sessions": int(row[0]), "cost": float(row[1] or 0), "tokens": int(row[2] or 0)}


def _opencode_message_usage(con, today_ms, week_ms):
    """Aggregate and reprice OpenCode assistant messages.

    Session rows are lifetime aggregates, so filtering them by session creation
    time misses usage when an older session is continued today. Assistant
    messages carry token counters with their actual event time. OpenCode plan
    rows may record zero cost, so known models use OpenRouter's public prices;
    the recorded amount remains the fallback for an unrecognized model.

    Forked subagent sessions can record one upstream call under multiple message
    IDs. The `dedup` CTE mirrors tokscale/CodexIsland's timestamp + model + token
    fingerprint before aggregation. CROSS JOIN keeps `session` as the outer loop
    so OpenCode's `(session_id, time_created)` index serves the bounded lookup.
    """
    rows = con.execute(
        """
        WITH assistant AS (
            SELECT m.id,
                   m.session_id,
                   m.time_created,
                   COALESCE(json_extract(m.data, '$.providerID'), '') AS provider,
                   COALESCE(json_extract(m.data, '$.modelID'), '') AS model,
                   COALESCE(CAST(json_extract(m.data, '$.cost') AS REAL), 0) AS cost,
                   COALESCE(CAST(json_extract(m.data, '$.tokens.input') AS INTEGER), 0) AS input,
                   COALESCE(CAST(json_extract(m.data, '$.tokens.output') AS INTEGER), 0) AS output,
                   COALESCE(CAST(json_extract(m.data, '$.tokens.reasoning') AS INTEGER), 0) AS reasoning,
                   COALESCE(CAST(json_extract(m.data, '$.tokens.cache.read') AS INTEGER), 0) AS cache_read,
                   COALESCE(CAST(json_extract(m.data, '$.tokens.cache.write') AS INTEGER), 0) AS cache_write
            FROM session AS s
            CROSS JOIN message AS m
            WHERE s.time_updated >= :week
              AND m.session_id = s.id
              AND m.time_created >= :week
              AND CASE WHEN json_valid(m.data)
                       THEN json_extract(m.data, '$.role') END = 'assistant'
        ), dedup AS (
            SELECT MIN(session_id) AS session_id,
                   time_created, provider, model,
                   input, output, reasoning, cache_read, cache_write,
                   MAX(cost) AS cost
            FROM assistant
            GROUP BY time_created, provider, model,
                     input, output, reasoning, cache_read, cache_write
        )
        SELECT (SELECT COUNT(DISTINCT session_id)
                FROM assistant WHERE time_created >= :today) AS sessions,
               provider,
               model,
               COALESCE(SUM(CASE WHEN time_created >= :today THEN cost ELSE 0 END), 0),
               COALESCE(SUM(CASE WHEN time_created >= :today THEN input ELSE 0 END), 0),
               COALESCE(SUM(CASE WHEN time_created >= :today THEN output ELSE 0 END), 0),
               COALESCE(SUM(CASE WHEN time_created >= :today THEN reasoning ELSE 0 END), 0),
               COALESCE(SUM(CASE WHEN time_created >= :today THEN cache_read ELSE 0 END), 0),
               COALESCE(SUM(CASE WHEN time_created >= :today THEN cache_write ELSE 0 END), 0),
               COALESCE(SUM(cost), 0),
               COALESCE(SUM(input), 0),
               COALESCE(SUM(output), 0),
               COALESCE(SUM(reasoning), 0),
               COALESCE(SUM(cache_read), 0),
               COALESCE(SUM(cache_write), 0)
        FROM dedup
        GROUP BY provider, model
        """,
        {"today": today_ms, "week": week_ms},
    ).fetchall()

    sessions = 0
    today_cost = week_cost = 0.0
    today_tokens = 0
    actual_today = actual_week = 0.0
    cost_sources = set()
    for row in rows:
        sessions = max(sessions, int(row[0] or 0))
        provider, model = str(row[1] or ""), str(row[2] or "")
        actual_today += float(row[3] or 0)
        today = tuple(int(value or 0) for value in row[4:9])
        actual_week += float(row[9] or 0)
        week = tuple(int(value or 0) for value in row[10:15])
        today_tokens += sum(today)

        rates = _price_rates(provider, model)
        if rates is None:
            today_cost += float(row[3] or 0)
            week_cost += float(row[9] or 0)
            cost_sources.add("recorded")
            continue

        # OpenCode exposes reasoning separately; like the original CodexIsland
        # reader, bill it at the output rate and include it once in TOKENS.
        today_cost += _cost_with_rates(
            rates, today[0], today[1] + today[2], today[4], today[3]
        )
        week_cost += _cost_with_rates(
            rates, week[0], week[1] + week[2], week[4], week[3]
        )
        cost_sources.add("openrouter")

    return {
        "sessions": sessions,
        "cost": today_cost,
        "tokens": today_tokens,
        "week_cost": week_cost,
        "actual_cost": actual_today,
        "week_actual_cost": actual_week,
        "cost_source": "+".join(sorted(cost_sources)) if cost_sources else "none",
    }


def _opencode_db_candidates(db_path=None):
    """OpenCode uses XDG data paths on every OS, including native Windows."""
    configured = db_path or os.environ.get("OPENCODE_DB", "").strip()
    if configured:
        return [_expand_host_path(configured)]

    directories = []
    xdg = os.environ.get("XDG_DATA_HOME", "").strip()
    if xdg:
        directories.append(os.path.join(_expand_host_path(xdg), "opencode"))
    directories.extend(
        os.path.join(home, ".local", "share", "opencode")
        for home in _host_homes()
    )

    candidates = []
    for directory in _unique_paths(directories):
        candidates.append(os.path.join(directory, "opencode.db"))
        # Development/beta channels use opencode-<channel>.db. Prefer the most
        # recently modified one after the stable database.
        channel = glob.glob(os.path.join(directory, "opencode-*.db"))
        channel.sort(
            key=lambda path: os.path.getmtime(path) if os.path.exists(path) else 0,
            reverse=True,
        )
        candidates.extend(channel)
    return _unique_paths(candidates)


def _find_opencode_db(db_path=None):
    for candidate in _opencode_db_candidates(db_path):
        if os.path.isfile(candidate):
            return candidate
    return None


def fetch_opencode(db_path=None):
    """Return {t, T, s, d} — today cost, today tokens, today sessions, 7d cost."""
    path = _find_opencode_db(db_path)
    if not path:
        return {"error": "no opencode db"}
    try:
        import sqlite3
        from pathlib import Path
        con = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True)
        try:
            today_ms = _day_start_ms()
            week_ms = _day_start_ms(6)
            try:
                usage = _opencode_message_usage(con, today_ms, week_ms)
                source = "messages"
            except sqlite3.Error:
                # Older OpenCode schemas only expose lifetime session totals.
                today = _opencode_query(con, today_ms)
                week = _opencode_query(con, week_ms)
                usage = {
                    **today,
                    "week_cost": week["cost"],
                    "actual_cost": today["cost"],
                    "week_actual_cost": week["cost"],
                    "cost_source": "recorded",
                }
                source = "sessions"
        finally:
            con.close()
    except (OSError, sqlite3.Error):
        return {"error": "opencode db read failed"}
    return {
        "t": round(usage["cost"], 2),
        "T": int(usage["tokens"]),
        "s": int(usage["sessions"]),
        "d": round(usage["week_cost"], 2),
        "actual_t": round(usage["actual_cost"], 2),
        "actual_d": round(usage["week_actual_cost"], 2),
        "cost_source": usage["cost_source"],
        "source": source,
    }


# --------------------------------------------------------------------------- #
# System stats — native Windows, macOS, Linux, plus Windows-host metrics in WSL
# --------------------------------------------------------------------------- #
_SYS_STATS_CACHE = {}
_SYS_STATS_LOCK = threading.Lock()
_HOST_NAME = ""
_SYS_REFRESH_TTL = 4.0
_SYS_REFRESHER_STARTED = False

# Combined PowerShell query: CPU load, memory, C: disk (space + r/w rates),
# and network rates.
_POWERSHELL_STATS_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$cpu = [math]::Round((Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average, 1)
$os  = Get-CimInstance Win32_OperatingSystem
$mem = [math]::Round((1 - ($os.FreePhysicalMemory / $os.TotalVisibleMemorySize)) * 100, 1)
$d   = Get-CimInstance Win32_LogicalDisk -Filter 'DriveType=3' | Where-Object DeviceID -eq 'C:'
$disk = if ($d) { [math]::Round((1 - $d.FreeSpace / $d.Size) * 100, 1) } else { $null }
$dr  = (Get-Counter '\PhysicalDisk(*)\Disk Read Bytes/sec').CounterSamples | Measure-Object CookedValue -Sum
$dw  = (Get-Counter '\PhysicalDisk(*)\Disk Write Bytes/sec').CounterSamples | Measure-Object CookedValue -Sum
$rx  = (Get-Counter '\Network Interface(*)\Bytes Received/sec').CounterSamples | Measure-Object CookedValue -Sum
$tx  = (Get-Counter '\Network Interface(*)\Bytes Sent/sec').CounterSamples | Measure-Object CookedValue -Sum
[pscustomobject]@{
    name = [string]$env:COMPUTERNAME
    cpu  = $cpu
    mem  = $mem
    disk = $disk
    dr   = [math]::Round($dr.Sum / 1024, 1)
    dw   = [math]::Round($dw.Sum / 1024, 1)
    nup  = [math]::Round($tx.Sum / 1024, 1)
    ndn  = [math]::Round($rx.Sum / 1024, 1)
} | ConvertTo-Json -Compress
"""


def _windows_sys_stats():
    """Query native Windows or the Windows host from WSL via PowerShell."""
    import base64
    try:
        encoded = base64.b64encode(_POWERSHELL_STATS_SCRIPT.encode("utf-16-le")).decode()
        out = subprocess.run(
            [_powershell_executable(), "-NoProfile", "-NonInteractive",
             "-EncodedCommand", encoded],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=15,
        )
        line = out.stdout.strip().splitlines()[-1] if out.stdout.strip() else ""
        d = json.loads(line)
        s = {k: (None if d.get(k) is None else float(d[k]))
             for k in ("cpu", "mem", "disk", "dr", "dw", "nup", "ndn")}
        if d.get("name"):
            s["name"] = str(d["name"]).strip()
        return s
    except (OSError, subprocess.TimeoutExpired, ValueError, json.JSONDecodeError):
        return None


# --------------------------------------------------------------------------- #
# Linux /proc fallback
# --------------------------------------------------------------------------- #
def _read_proc_lines(path):
    with open(path) as f:
        return f.readlines()


def _cpu_pct(sample_s=0.25):
    def _sample():
        line = _read_proc_lines("/proc/stat")[0].split()
        vals = [int(v) for v in line[1:8]]
        return sum(vals), vals[3]  # total, idle
    try:
        t0, i0 = _sample()
        time.sleep(sample_s)
        t1, i1 = _sample()
        delta = t1 - t0
        if delta <= 0:
            return 0.0
        return round(100.0 * (1 - (i1 - i0) / delta), 1)
    except (OSError, ValueError, IndexError):
        return None


def _mem_pct():
    try:
        mem = {}
        for line in _read_proc_lines("/proc/meminfo"):
            key, _, rest = line.partition(":")
            mem[key] = rest.split()[0]
        total = float(mem["MemTotal"])
        avail = float(mem["MemAvailable"])
        if total <= 0:
            return None
        return round(100.0 * (total - avail) / total, 1)
    except (OSError, ValueError, KeyError):
        return None


def _disk_pct(mount="/"):
    try:
        st = os.statvfs(mount)
        total = st.f_blocks * st.f_frsize
        avail = st.f_bavail * st.f_frsize
        if total <= 0:
            return None
        return round(100.0 * (total - avail) / total, 1)
    except (OSError, AttributeError):
        return None


def _net_bytes():
    rx = tx = 0
    for line in _read_proc_lines("/proc/net/dev")[2:]:
        if ":" not in line:
            continue
        iface, rest = line.split(":", 1)
        fields = rest.split()
        if iface.strip() == "lo" or not fields:
            continue
        rx += int(fields[0])  # receive bytes
        tx += int(fields[8])  # transmit bytes
    return rx, tx


def _net_rate_kbps(sample_s=0.5):
    try:
        r0, t0 = _net_bytes()
        time.sleep(sample_s)
        r1, t1 = _net_bytes()
        up = (t1 - t0) / 1024.0 / sample_s
        dn = (r1 - r0) / 1024.0 / sample_s
        return round(up, 1), round(dn, 1)
    except (OSError, ValueError, IndexError):
        return None, None


def _proc_sys_stats():
    up, dn = _net_rate_kbps()
    return {
        "name": platform.node(),
        "cpu": _cpu_pct(),
        "mem": _mem_pct(),
        "disk": _disk_pct(),
        "dr": None,
        "dw": None,
        "nup": up,
        "ndn": dn,
    }


def _psutil_sys_stats():
    """Full cross-platform metrics when psutil is installed."""
    try:
        import psutil
    except ImportError:
        return None
    try:
        mount = (os.environ.get("SystemDrive", "C:") + "\\"
                 if os.name == "nt" else "/")
        cpu = round(float(psutil.cpu_percent(interval=0.2)), 1)
        mem = round(float(psutil.virtual_memory().percent), 1)
        disk = round(float(psutil.disk_usage(mount).percent), 1)
        disk0 = psutil.disk_io_counters()
        net0 = psutil.net_io_counters()
        sample_s = 0.3
        time.sleep(sample_s)
        disk1 = psutil.disk_io_counters()
        net1 = psutil.net_io_counters()
        dr = ((disk1.read_bytes - disk0.read_bytes) / 1024 / sample_s
              if disk0 and disk1 else None)
        dw = ((disk1.write_bytes - disk0.write_bytes) / 1024 / sample_s
              if disk0 and disk1 else None)
        up = ((net1.bytes_sent - net0.bytes_sent) / 1024 / sample_s
              if net0 and net1 else None)
        dn = ((net1.bytes_recv - net0.bytes_recv) / 1024 / sample_s
              if net0 and net1 else None)
        return {
            "name": platform.node(),
            "cpu": cpu,
            "mem": mem,
            "disk": disk,
            "dr": None if dr is None else round(max(0, dr), 1),
            "dw": None if dw is None else round(max(0, dw), 1),
            "nup": None if up is None else round(max(0, up), 1),
            "ndn": None if dn is None else round(max(0, dn), 1),
        }
    except (OSError, ValueError, AttributeError):
        return None


def _macos_cpu_pct():
    try:
        out = subprocess.run(
            ["ps", "-A", "-o", "%cpu="], capture_output=True, text=True,
            timeout=5,
        )
        total = sum(float(value) for value in out.stdout.split())
        return round(min(100.0, total / max(1, os.cpu_count() or 1)), 1)
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return None


def _parse_vm_stat(text, total_bytes):
    """Convert macOS vm_stat output to a practical used-memory percentage."""
    match = re.search(r"page size of (\d+) bytes", text)
    if not match or total_bytes <= 0:
        return None
    page_size = int(match.group(1))
    pages = {}
    for line in text.splitlines()[1:]:
        key, sep, raw = line.partition(":")
        if not sep:
            continue
        try:
            pages[key.strip()] = int(raw.strip().rstrip("."))
        except ValueError:
            continue
    available = sum(
        pages.get(key, 0)
        for key in ("Pages free", "Pages inactive", "Pages speculative")
    ) * page_size
    return round(max(0.0, min(100.0, 100 * (1 - available / total_bytes))), 1)


def _macos_mem_pct():
    try:
        total = subprocess.run(
            ["sysctl", "-n", "hw.memsize"], capture_output=True, text=True,
            timeout=5, check=True,
        )
        vm = subprocess.run(
            ["vm_stat"], capture_output=True, text=True, timeout=5, check=True,
        )
        return _parse_vm_stat(vm.stdout, int(total.stdout.strip()))
    except (OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError,
            ValueError):
        return None


def _macos_net_bytes():
    """Read interface counters without double-counting address-family rows."""
    try:
        out = subprocess.run(
            ["netstat", "-ibn"], capture_output=True, text=True, timeout=5,
            check=True,
        )
        header = None
        interfaces = {}
        for line in out.stdout.splitlines():
            fields = line.split()
            if not fields:
                continue
            if fields[0] == "Name" and "Ibytes" in fields and "Obytes" in fields:
                header = fields
                continue
            if (not header or fields[0].startswith("lo")
                    or len(fields) < len(header)):
                continue
            try:
                rx = int(fields[header.index("Ibytes")])
                tx = int(fields[header.index("Obytes")])
            except (ValueError, IndexError):
                continue
            old = interfaces.get(fields[0], (0, 0))
            interfaces[fields[0]] = max(old[0], rx), max(old[1], tx)
        return (
            sum(value[0] for value in interfaces.values()),
            sum(value[1] for value in interfaces.values()),
        )
    except (OSError, subprocess.TimeoutExpired, subprocess.CalledProcessError):
        return None


def _macos_sys_stats():
    full = _psutil_sys_stats()
    if full:
        return full
    first = _macos_net_bytes()
    time.sleep(0.5)
    second = _macos_net_bytes()
    up = dn = None
    if first and second:
        dn = round(max(0, second[0] - first[0]) / 1024 / 0.5, 1)
        up = round(max(0, second[1] - first[1]) / 1024 / 0.5, 1)
    return {
        "name": platform.node(),
        "cpu": _macos_cpu_pct(),
        "mem": _macos_mem_pct(),
        "disk": _disk_pct(),
        "dr": None,
        "dw": None,
        "nup": up,
        "ndn": dn,
    }


def _collect_system_stats():
    if os.name == "nt":
        # Native Windows is cheaper and more locale-independent through
        # psutil. PowerShell remains a dependency-free fallback. WSL keeps
        # PowerShell first because psutil there would describe only the VM.
        return _psutil_sys_stats() or _windows_sys_stats()
    if _is_wsl():
        stats = _windows_sys_stats()
        if stats:
            return stats
        return _psutil_sys_stats() or _proc_sys_stats()
    if sys.platform == "darwin":
        return _macos_sys_stats()
    if sys.platform.startswith("linux"):
        return _psutil_sys_stats() or _proc_sys_stats()
    return _psutil_sys_stats()


def _refresh_system_cache():
    global _HOST_NAME
    stats = _collect_system_stats()
    if not stats:
        return False
    name = stats.pop("name", None)
    with _SYS_STATS_LOCK:
        _SYS_STATS_CACHE.clear()
        _SYS_STATS_CACHE.update(stats)
        _SYS_STATS_CACHE["_at"] = time.time()
        if name:
            _HOST_NAME = str(name).strip()
    return True


def _sys_refresher():
    """Keep platform metrics warm so /stats never runs a blocking sampler."""
    while True:
        time.sleep(_SYS_REFRESH_TTL)
        try:
            _refresh_system_cache()
        except Exception:  # noqa: BLE001
            pass


def _ensure_sys_refresher():
    global _SYS_REFRESHER_STARTED
    if _SYS_REFRESHER_STARTED:
        return
    _SYS_REFRESHER_STARTED = True
    threading.Thread(target=_sys_refresher, daemon=True).start()


def sys_stats():
    """Return warm native host metrics on Windows, macOS, Linux, or WSL."""
    _ensure_sys_refresher()
    if not _SYS_STATS_CACHE:
        try:
            _refresh_system_cache()
        except Exception:  # noqa: BLE001
            pass
    with _SYS_STATS_LOCK:
        out = {
            key: _SYS_STATS_CACHE.get(key)
            for key in ("cpu", "mem", "disk", "dr", "dw", "nup", "ndn")
        }
    if _HOST_NAME:
        out["name"] = _HOST_NAME
    elif platform.node():
        out["name"] = platform.node()
    return out


# --------------------------------------------------------------------------- #
# Cost — OpenRouter pricing + local Claude/Codex session logs
# --------------------------------------------------------------------------- #
OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
_PRICE_CACHE_VERSION = 1
_PRICE_REFRESH_S = 6 * 60 * 60
_PRICE_RETRY_S = 5 * 60
_PRICE_UNKNOWN_REFRESH_S = 60 * 60

# Last-good offline snapshot in USD per million tokens:
# (input, output, cache_write, cache_read). OpenRouter is the live source; this
# table only keeps the display useful on first launch without network access.
_FALLBACK_PRICING = {
    "openai/gpt-5.6-sol": (5, 30, 6.25, 0.50),
    "openai/gpt-5.6-terra": (1, 6, 1.25, 0.10),
    "openai/gpt-5.6-luna": (0.10, 0.60, 0.125, 0.01),
    "anthropic/claude-opus-4-8": (5, 25, 6.25, 0.50),
    "anthropic/claude-opus-4-7": (5, 25, 6.25, 0.50),
    "anthropic/claude-opus-4-6": (5, 25, 6.25, 0.50),
    "anthropic/claude-opus-4-5": (5, 25, 6.25, 0.50),
    "anthropic/claude-sonnet-4-6": (3, 15, 3.75, 0.30),
    "anthropic/claude-sonnet-4-5": (3, 15, 3.75, 0.30),
    "anthropic/claude-haiku-4-5": (1, 5, 1.25, 0.10),
    "openai/gpt-5.5": (5, 30, 5, 0.50),
    "openai/gpt-5.4": (2.5, 15, 2.5, 0.25),
    "openai/gpt-5.2": (1.75, 14, 1.75, 0.175),
    "openai/gpt-5.4-mini": (0.75, 4.5, 0.75, 0.075),
    "openai/gpt-5-codex": (1.25, 10, 1.25, 0.125),
    "deepseek/deepseek-v4-flash": (0.14, 0.28, 0.14, 0.028),
    "moonshotai/kimi-k3": (3, 15, 3, 0.30),
}

_PRICE_LOCK = threading.Lock()
_PRICE_CATALOG = {}
_PRICE_CATALOG_FETCHED_AT = 0.0
_PRICE_CATALOG_LOADED = False
_PRICE_CATALOG_SOURCE = "embedded"
_PRICE_LAST_ATTEMPT = 0.0
_PRICE_LAST_ERROR = None
_PRICE_UNKNOWN_ATTEMPTS = {}
_PRICE_FALLBACK_MODELS = set()
_PRICE_UNPRICED_MODELS = set()


def _price_cache_path():
    override = os.environ.get("CC_PRICING_CACHE", "").strip()
    if override:
        return os.path.expanduser(override)
    root = os.environ.get("XDG_CACHE_HOME", "").strip()
    if root:
        return os.path.join(
            os.path.expanduser(root), "cc-island", "openrouter-pricing.json"
        )
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Caches/cc-island/openrouter-pricing.json")
    return os.path.expanduser("~/.cache/cc-island/openrouter-pricing.json")


def _price_refresh_seconds():
    try:
        hours = float(os.environ.get("CC_PRICING_REFRESH_HOURS", "6"))
        if not math.isfinite(hours):
            return _PRICE_REFRESH_S
        return max(5 * 60, hours * 60 * 60)
    except ValueError:
        return _PRICE_REFRESH_S


def _parse_openrouter_pricing(obj):
    """Return model rates per million tokens from OpenRouter /api/v1/models."""
    if not isinstance(obj, dict) or not isinstance(obj.get("data"), list):
        return {}

    def per_token(value):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return number if number >= 0 and math.isfinite(number) else None

    result = {}
    for model in obj["data"]:
        if not isinstance(model, dict):
            continue
        model_id = model.get("id")
        if not isinstance(model_id, str) or "/" not in model_id:
            continue
        pricing = model.get("pricing") or {}
        prompt = per_token(pricing.get("prompt"))
        completion = per_token(pricing.get("completion"))
        if prompt is None or completion is None:
            continue
        cache_read = per_token(pricing.get("input_cache_read"))
        cache_write = per_token(pricing.get("input_cache_write"))
        # If OpenRouter does not publish a separate cache category, charge it
        # as ordinary input rather than silently treating those tokens as free.
        cache_read = prompt if cache_read is None else cache_read
        cache_write = prompt if cache_write is None else cache_write
        result[model_id] = tuple(
            value * 1_000_000
            for value in (prompt, completion, cache_write, cache_read)
        )
    return result


def _load_price_cache_unlocked():
    global _PRICE_CATALOG, _PRICE_CATALOG_FETCHED_AT
    global _PRICE_CATALOG_LOADED, _PRICE_CATALOG_SOURCE
    _PRICE_CATALOG_LOADED = True
    try:
        with open(_price_cache_path()) as f:
            saved = json.load(f)
        if not isinstance(saved, dict):
            return
        if saved.get("version") != _PRICE_CACHE_VERSION:
            return
        models = {}
        for model_id, values in (saved.get("models") or {}).items():
            valid_shape = (
                isinstance(model_id, str)
                and isinstance(values, list)
                and len(values) == 4
            )
            if not valid_shape:
                continue
            rates = tuple(float(value) for value in values)
            if all(value >= 0 and math.isfinite(value) for value in rates):
                models[model_id] = rates
        if models:
            _PRICE_CATALOG = models
            _PRICE_CATALOG_FETCHED_AT = float(saved.get("fetched_at") or 0)
            _PRICE_CATALOG_SOURCE = "disk-cache"
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return


def _save_price_cache_unlocked():
    path = _price_cache_path()
    tmp = f"{path}.tmp-{os.getpid()}"
    try:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(tmp, "w") as f:
            json.dump({
                "version": _PRICE_CACHE_VERSION,
                "source": OPENROUTER_MODELS_URL,
                "fetched_at": _PRICE_CATALOG_FETCHED_AT,
                "models": {key: list(value) for key, value in _PRICE_CATALOG.items()},
            }, f, separators=(",", ":"), sort_keys=True)
        os.replace(tmp, path)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _ensure_price_catalog(force=False):
    """Load the last-good catalog and refresh it at most every six hours."""
    global _PRICE_CATALOG, _PRICE_CATALOG_FETCHED_AT, _PRICE_CATALOG_SOURCE
    global _PRICE_LAST_ATTEMPT, _PRICE_LAST_ERROR
    now = time.time()
    with _PRICE_LOCK:
        if not _PRICE_CATALOG_LOADED:
            _load_price_cache_unlocked()
        fresh = (_PRICE_CATALOG and
                 now - _PRICE_CATALOG_FETCHED_AT < _price_refresh_seconds())
        if fresh and not force:
            return _PRICE_CATALOG
        if now - _PRICE_LAST_ATTEMPT < _PRICE_RETRY_S:
            return _PRICE_CATALOG
        _PRICE_LAST_ATTEMPT = now
        status, obj = _http(
            "GET", OPENROUTER_MODELS_URL,
            headers={"Accept": "application/json", "User-Agent": "cc-island/1"},
        )
        models = _parse_openrouter_pricing(obj)
        if status == 200 and models:
            _PRICE_CATALOG = models
            _PRICE_CATALOG_FETCHED_AT = now
            _PRICE_CATALOG_SOURCE = "openrouter"
            _PRICE_LAST_ERROR = None
            _save_price_cache_unlocked()
        else:
            detail = (obj or {}).get("_transport_error") if isinstance(obj, dict) else None
            _PRICE_LAST_ERROR = detail or f"OpenRouter HTTP {status}"
        return _PRICE_CATALOG


def _strip_model_date(model):
    return re.sub(r"-(?:\d{8}|\d{4}-\d{2}-\d{2})$", "", model)


def _openrouter_claude_id(model):
    # Anthropic logs use claude-opus-4-6 / claude-3-5-sonnet while OpenRouter
    # uses claude-opus-4.6 / claude-3.5-sonnet.
    model = re.sub(r"^(claude-(?:opus|sonnet|haiku)-\d+)-(\d+)", r"\1.\2", model)
    return re.sub(r"^(claude-\d+)-(\d+)(-.+)$", r"\1.\2\3", model)


def _model_price_candidates(provider, raw):
    raw = (raw or "").strip().lstrip("~")
    if not raw:
        return []
    if "/" in raw:
        provider_id, model = raw.split("/", 1)
    else:
        provider_id, model = provider, raw
    candidates = []

    def add(model_id):
        key = f"{provider_id}/{model_id}"
        if key not in candidates:
            candidates.append(key)
        if provider_id == "anthropic":
            key = f"{provider_id}/{_openrouter_claude_id(model_id)}"
            if key not in candidates:
                candidates.append(key)

    add(model)
    canonical = _strip_model_date(model)
    if canonical != model:
        add(canonical)
    if provider_id == "openai" and model == "codex-auto-review":
        fallback = os.environ.get("CC_CODEX_FALLBACK_MODEL", "gpt-5.6-sol").strip()
        if fallback and fallback != model:
            if "/" in fallback:
                fallback_provider, fallback = fallback.split("/", 1)
                provider_id = fallback_provider
            add(fallback)
    return candidates


def _catalog_rate(table, candidates):
    """Resolve exact ids first, then one unambiguous model-name alias.

    OpenCode provider IDs often describe the subscription/router (for example
    ``opencode-go`` or ``tu-zi``), not the model publisher used by OpenRouter.
    A unique catalog suffix lets those installations resolve without a growing
    hard-coded provider map. ``coding-`` is an OpenCode channel prefix rather
    than part of the public model id.
    """
    for candidate in candidates:
        if candidate in table:
            return candidate, table[candidate]

    names = []
    for candidate in candidates:
        model = candidate.split("/", 1)[-1]
        for alias in (model, _strip_model_date(model)):
            if alias and alias not in names:
                names.append(alias)
            if alias.startswith("coding-"):
                plain = alias[len("coding-"):]
                if plain and plain not in names:
                    names.append(plain)

    for name in names:
        matches = [key for key in table if key.split("/", 1)[-1] == name]
        if len(matches) == 1:
            key = matches[0]
            return key, table[key]
    return None, None


def _price_rates(provider, model):
    candidates = _model_price_candidates(provider, model)
    catalog = _ensure_price_catalog()
    _, rates = _catalog_rate(catalog, candidates)
    if rates is not None:
        return rates

    # A newly released model should not wait for the normal six-hour refresh.
    key = candidates[0] if candidates else f"{provider}/{model}"
    now = time.time()
    if catalog and now - _PRICE_UNKNOWN_ATTEMPTS.get(key, 0) >= _PRICE_UNKNOWN_REFRESH_S:
        _PRICE_UNKNOWN_ATTEMPTS[key] = now
        catalog = _ensure_price_catalog(force=True)
        _, rates = _catalog_rate(catalog, candidates)
        if rates is not None:
            return rates

    fallback_key, rates = _catalog_rate(_FALLBACK_PRICING, candidates)
    if rates is not None:
        _PRICE_FALLBACK_MODELS.add(fallback_key)
        return rates
    if key not in _PRICE_UNPRICED_MODELS:
        _PRICE_UNPRICED_MODELS.add(key)
        print(f"WARN: no OpenRouter price for {key}; dollar estimate excludes it",
              file=sys.stderr)
    return None


def _cost_with_rates(rates, in_, out, cache_write, cache_read):
    return (in_ * rates[0] + out * rates[1]
            + cache_write * rates[2] + cache_read * rates[3]) / 1_000_000


def _cost(provider, model, in_, out, cache_write, cache_read):
    rates = _price_rates(provider, model)
    if rates is None:
        return 0.0
    return _cost_with_rates(rates, in_, out, cache_write, cache_read)


def pricing_status():
    catalog = _ensure_price_catalog()
    out = {
        "source": _PRICE_CATALOG_SOURCE if catalog else "embedded",
        "url": OPENROUTER_MODELS_URL,
        "updated_at": (
            int(_PRICE_CATALOG_FETCHED_AT) if _PRICE_CATALOG_FETCHED_AT else None
        ),
        "models": len(catalog),
    }
    if _PRICE_FALLBACK_MODELS:
        out["fallback_models"] = sorted(_PRICE_FALLBACK_MODELS)
    if _PRICE_UNPRICED_MODELS:
        out["unpriced_models"] = sorted(_PRICE_UNPRICED_MODELS)
    if _PRICE_LAST_ERROR:
        out["refresh_error"] = _PRICE_LAST_ERROR
    return out


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


def _glob_unique(patterns):
    paths = []
    seen = set()
    for pattern in patterns:
        for path in glob.glob(pattern, recursive=True):
            key = os.path.normcase(os.path.realpath(path))
            if key not in seen:
                seen.add(key)
                paths.append(path)
    return paths


def cost_claude(midnight):
    cost, tokens, seen = 0.0, 0, set()
    paths = _glob_unique(
        os.path.join(root, "projects", "**", "*.jsonl")
        for root in _claude_roots()
    )
    for path in paths:
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
                    cost += _cost("anthropic", model, i, out, cc, cr)
                    tokens += i + out + cc + cr
        except OSError:
            continue
    return cost, tokens


def cost_codex(midnight):
    cost, tokens = 0.0, 0
    snapshot_fields = (
        "input_tokens", "cached_input_tokens", "cache_write_input_tokens",
        "output_tokens", "reasoning_output_tokens", "total_tokens",
    )
    paths = _glob_unique(
        os.path.join(root, "sessions", "**", "rollout-*.jsonl")
        for root in _codex_roots()
    )
    for path in paths:
        try:
            if os.path.getmtime(path) < midnight - 86400:
                continue
            cur_model = None
            previous_usage_snapshot = None
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
                    info = p.get("info") or {}
                    last = info.get("last_token_usage") or {}
                    total = info.get("total_token_usage") or {}
                    if not last:
                        continue
                    # Codex can emit the same cumulative usage snapshot again
                    # after status/tool events. Count each completed model call
                    # once, while still allowing identical per-call usage when
                    # the cumulative total has advanced.
                    if total:
                        snapshot = tuple(int(total.get(k, 0) or 0)
                                         for k in snapshot_fields)
                        if snapshot == previous_usage_snapshot:
                            continue
                        previous_usage_snapshot = snapshot
                    if _parse_ts(o.get("timestamp", "")) < midnight:
                        continue
                    ti = last.get("input_tokens", 0) or 0
                    cached = last.get("cached_input_tokens", 0) or 0
                    cache_write = last.get("cache_write_input_tokens", 0) or 0
                    nonc = max(0, ti - cached - cache_write)
                    out = last.get("output_tokens", 0) or 0
                    if not (nonc or cached or cache_write or out):
                        continue
                    cost += _cost("openai", cur_model or "gpt-5.4",
                                  nonc, out, cache_write, cached)
                    tokens += nonc + cached + cache_write + out
        except OSError:
            continue
    return cost, tokens


# --------------------------------------------------------------------------- #
# OpenCode Go — dashboard scrape for subscription quota (5h / weekly / monthly)
#
# OpenCode has no public usage API; the community approach is to scrape the
# workspace Go dashboard, which embeds the numbers in SolidJS SSR hydration
# output. Needs an `auth` cookie from your logged-in browser session — it
# expires periodically, so re-export it when auth fails.
# --------------------------------------------------------------------------- #
_OC_GO_URL = "https://opencode.ai/workspace/{ws}/go"
_OC_GO_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
             "Gecko/20100101 Firefox/148.0")
_OC_GO_REFRESH_TTL = 5 * 60
_OC_GO_CACHE = {}
_OC_GO_CACHE_AT = 0.0
_OC_GO_CACHE_KEY = None
_OC_GO_LOCK = threading.Lock()


def _extract_go_window(html, field):
    """Pull `usagePercent` + `resetInSec` out of a SolidJS `$R[n]={...}` literal."""
    import re
    m = re.search(re.escape(field) + r'\s*:\s*\$R\[\d+\]\s*=\s*\{', html)
    if not m:
        return None
    start = m.end() - 1
    depth, i, in_str, esc = 0, start, None, False
    while i < len(html):
        c = html[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == in_str:
                in_str = None
        elif c in ("\"", "'", "`"):
            in_str = c
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                lit = html[start:i + 1]
                break
        i += 1
    else:
        return None
    up = re.search(r'usagePercent\s*:\s*(-?\d+(?:\.\d+)?)', lit)
    rs = re.search(r'resetInSec\s*:\s*(-?\d+(?:\.\d+)?)', lit)
    if not up or not rs:
        return None
    return float(up.group(1)), float(rs.group(1))


def fetch_opencode_go(workspace_id, auth_cookie):
    """Return h/hr, w/wr, m/mr — quota percentages and reset minutes."""
    if not workspace_id or not auth_cookie:
        return {"error": "go config missing"}
    url = _OC_GO_URL.format(ws=workspace_id)
    req = urllib.request.Request(url, headers={
        "Cookie": f"auth={auth_cookie}",
        "User-Agent": _OC_GO_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    try:
        with urllib.request.urlopen(req, timeout=15, context=_SSL_CTX) as resp:
            html = resp.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return {"error": f"go: {e}"}
    out = {}
    for field, key in (("rollingUsage", "h"), ("weeklyUsage", "w"),
                       ("monthlyUsage", "m")):
        win = _extract_go_window(html, field)
        if win:
            pct, reset = win
            out[key] = int(round(max(0.0, min(100.0, pct))))
            out[key + "r"] = int(max(0, round(reset / 60)))
    if not out:
        return {"error": "go: parse failed (page format changed?)"}
    return out


def _cached_opencode_go(config):
    """Avoid scraping the OpenCode Go dashboard on every 30-second refresh."""
    global _OC_GO_CACHE, _OC_GO_CACHE_AT, _OC_GO_CACHE_KEY
    workspace_id = config.get("workspace_id")
    auth_cookie = config.get("auth_cookie")
    cache_key = (workspace_id, auth_cookie)
    now = time.time()
    with _OC_GO_LOCK:
        if (_OC_GO_CACHE_KEY == cache_key and _OC_GO_CACHE
                and now - _OC_GO_CACHE_AT < _OC_GO_REFRESH_TTL):
            return dict(_OC_GO_CACHE)
        result = fetch_opencode_go(workspace_id, auth_cookie)
        _OC_GO_CACHE = dict(result)
        _OC_GO_CACHE_AT = now
        _OC_GO_CACHE_KEY = cache_key
        return result


# --------------------------------------------------------------------------- #
# Combine + render
# --------------------------------------------------------------------------- #
_DATA_CACHE = {}
_DATA_CACHE_LOCK = threading.Lock()
_LAST_GOOD_PROVIDERS = {}
_DATA_REFRESH_TTL = 30
_DATA_REFRESHER_STARTED = False
_opencode_db_arg = None
_opencode_go_arg = None
MAX_STALE_PROVIDER_S = 6 * 60 * 60
_PROVIDER_NAMES = ("claude", "codex", "opencode")


def _collect_providers(opencode_db, opencode_go):
    """Fetch providers + local costs only (no sys). Can take many seconds."""
    midnight = _today_midnight()
    claude = fetch_claude()
    codex = fetch_codex()
    cc_cost, cc_tok = cost_claude(midnight)
    cx_cost, cx_tok = cost_codex(midnight)
    claude["cost_today"], claude["tokens_today"] = round(cc_cost, 2), cc_tok
    codex["cost_today"], codex["tokens_today"] = round(cx_cost, 2), cx_tok
    opencode = fetch_opencode(opencode_db)
    if opencode_go is not None:
        opencode["go"] = _cached_opencode_go(opencode_go)
    return {
        "ts": int(time.time()),
        "claude": claude,
        "codex": codex,
        "opencode": opencode,
        "pricing": pricing_status(),
    }


def _store_provider_cache(fresh, now=None):
    """Publish a refresh without replacing good data with transient errors.

    Provider endpoints fail independently, so one temporary auth/network/API
    error must not blank a watch page that already has a recent good reading.
    Local counters from the failed refresh are still copied onto the cached
    provider value because those do not depend on the remote endpoint.
    """
    global _DATA_CACHE
    now = time.time() if now is None else now
    merged = dict(fresh)

    with _DATA_CACHE_LOCK:
        for name in _PROVIDER_NAMES:
            current = dict(fresh.get(name) or {})
            if "error" not in current:
                _LAST_GOOD_PROVIDERS[name] = (dict(current), now)
                merged[name] = current
                continue

            saved = _LAST_GOOD_PROVIDERS.get(name)
            if not saved or now - saved[1] > MAX_STALE_PROVIDER_S:
                merged[name] = current
                continue

            restored = dict(saved[0])
            restored.update({key: value for key, value in current.items()
                             if key != "error"})
            restored["cached"] = True
            restored["cache_age_s"] = max(0, int(now - saved[1]))
            restored["refresh_error"] = current["error"]
            merged[name] = restored

        _DATA_CACHE = merged
        return dict(_DATA_CACHE)


def _read_provider_cache():
    with _DATA_CACHE_LOCK:
        return dict(_DATA_CACHE)


def _data_refresher():
    while True:
        time.sleep(_DATA_REFRESH_TTL)
        try:
            fresh = _collect_providers(_opencode_db_arg, _opencode_go_arg)
            _store_provider_cache(fresh)
        except Exception:  # noqa: BLE001
            pass


def _ensure_data_refresher():
    global _DATA_REFRESHER_STARTED
    if _DATA_REFRESHER_STARTED:
        return
    _DATA_REFRESHER_STARTED = True
    threading.Thread(target=_data_refresher, daemon=True).start()


def collect(opencode_db=None, opencode_go=None):
    """Providers come from the background-refreshed cache (instant); sys comes
    from the warm PC-stats cache when enabled. Only the very first call may
    block on a slow network fetch."""
    global _opencode_db_arg, _opencode_go_arg
    _opencode_db_arg = opencode_db
    _opencode_go_arg = opencode_go
    _ensure_data_refresher()
    data = _read_provider_cache()
    if data:
        if system_monitor_enabled():
            data["sys"] = sys_stats()
        data["ts"] = int(time.time())
        return data
    data = _store_provider_cache(_collect_providers(opencode_db, opencode_go))
    if system_monitor_enabled():
        data["sys"] = sys_stats()
    return data


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
        lines.append(f"   today  ~${p.get('cost_today', 0):.2f}   {p.get('tokens_today', 0):,} tok")

    oc = data["opencode"]
    if "error" in oc:
        lines.append(f"{'OpenCode':10} ⚠ {oc['error']}")
    else:
        go = oc.get("go")
        if isinstance(go, dict) and "h" in go:
            h, w, m = go.get("h", 0), go.get("w", 0), go.get("m", 0)
            reset = go.get("hr", 0)
            lines.append("OpenCode Go  ")
            lines.append(f"   5h   {h}%   reset {reset // 60}h{reset % 60:02d}m")
            lines.append(f"   weekly {w}%   monthly {m}%")
        else:
            lines.append("OpenCode  ")
        lines.append(f"   today  ~${oc.get('t', 0):.2f}   {oc.get('T', 0):,} tok   {oc.get('s', 0)} ses")
        lines.append(f"   7d     ~${oc.get('d', 0):.2f}")
    if go_err := (oc.get("go") or {}).get("error"):
        lines.append(f"   (go: {go_err})")

    s = data.get("sys")
    if isinstance(s, dict):
        lines.append("  System")
        lines.append(
            f"   cpu {s.get('cpu')}%  mem {s.get('mem')}%  disk {s.get('disk')}%"
        )
        lines.append(f"   net up {s.get('nup')}K/s  dn {s.get('ndn')}K/s")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Watch payload — compact JSON the firmware understands
# --------------------------------------------------------------------------- #
def _win_pct(w):
    return int(round(w["pct"])) if w else 0


def _reset_min(w):
    if not w or not w.get("reset_at"):
        return 0
    return max(0, int((w["reset_at"] - time.time()) / 60))


def _window_prov(p, include_cost=True):
    if "error" in p:
        return {"error": p["error"][:24]}
    fh = p.get("five_hour")
    wk = p.get("weekly")
    out = {
        "h": _win_pct(fh),
        "hr": _reset_min(fh),
        "hw": int(fh.get("window_seconds", 0)) if fh else 0,
        "w": _win_pct(wk) if wk else -1,   # -1 = no secondary window
        "wr": _reset_min(wk) if wk else 0,
        "ww": int(wk.get("window_seconds", 0)) if wk else 0,
    }
    if include_cost:
        out["$"] = round(p.get("cost_today", 0), 2)
        out["t"] = int(p.get("tokens_today", 0))
    return out


def compact(data):
    """Short-key one-line JSON for the watch.

      c, x  window-based providers (Claude/Codex): {h: 5h pct, w: 7d pct,
            hr: 5h reset mins, wr: 7d reset mins, $: today $, t: today tok}
      o     OpenCode: {t: today $, T: today tok, s: sessions, d: 7d $,
            plus h/hr/w/wr/m/mr when the Go quota scrape is configured
            (5h/weekly/monthly usage % and per-window reset mins)}
      sys   system: {name, cpu, mem, disk, dr, dw, nup, ndn}  (rates in KB/s)
    """
    raw_o = data["opencode"]
    if "error" in raw_o:
        o = {"error": raw_o["error"][:24]}
    else:
        # Whitelist watch fields and never mutate the shared provider cache.
        o = {key: raw_o[key] for key in ("t", "T", "s", "d") if key in raw_o}
        go = raw_o.get("go")
        if isinstance(go, dict):
            for k in ("h", "hr", "w", "wr", "m", "mr"):
                if k in go:
                    o[k] = go[k]
    payload = {
        "c": _window_prov(data["claude"]),
        "x": _window_prov(data["codex"]),
        "o": o,
    }
    s = data.get("sys")
    if isinstance(s, dict):
        system = {}
        for k, v in s.items():
            if k == "name":
                system["name"] = v if isinstance(v, str) else str(v)
            else:
                system[k] = (None if v is None else round(v, 1))
        payload["sys"] = system
    return json.dumps(payload, separators=(",", ":"))


# --------------------------------------------------------------------------- #
# WiFi polling server
# --------------------------------------------------------------------------- #
def serve(port, host="0.0.0.0", opencode_db=None, opencode_go=None):
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass  # quiet — the poll loop is chatty enough

        def _send(self, code, body, ctype="application/json"):
            data = body.encode() if isinstance(body, str) else body
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            try:
                data = collect(opencode_db, opencode_go)
            except Exception as e:  # noqa: BLE001 — keep the server alive
                return self._send(500, json.dumps({"error": str(e)}))
            path = self.path.split("?", 1)[0]
            if path == "/stats":
                return self._send(200, compact(data))
            if path == "/json":
                return self._send(200, json.dumps(data, indent=2))
            return self._send(200, render(data), "text/plain")

    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"serving WiFi polling on http://{host}:{port}  (Ctrl-C to stop)")
    print("  GET /stats → compact watch JSON")
    print("  GET /json  → full JSON")
    print("  GET /      → human readable")
    # Warm the caches once before serving so the watch never hits a cold,
    # multi-second poll (first network fetch can take a while).
    print("warming caches...")
    try:
        collect(opencode_db, opencode_go)
        if system_monitor_enabled():
            sys_stats()
        print("caches warm")
    except Exception as e:  # noqa: BLE001
        print("warm-up failed (will retry in background):", e)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


# --------------------------------------------------------------------------- #
# BLE push — Nordic UART Service (the original transport)
# --------------------------------------------------------------------------- #
NUS_RX_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"   # Mac -> watch (usage JSON)
NUS_TX_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"   # watch -> Mac (refresh request)
NUS_SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
BLE_DEVICE_NAME = "CC Island"
MANUAL_REFRESH_MIN_GAP = 5  # seconds — throttle button-triggered refreshes
SCAN_TIMEOUT_S = 20
RECONNECT_DELAY_S = 3


async def ble_loop(interval_s, opencode_db=None, opencode_go=None):
    import asyncio
    from bleak import BleakClient, BleakScanner

    refresh = asyncio.Event()   # set when the watch's button asks for a refresh
    disconnected = asyncio.Event()
    last_push = [0.0]

    async def find_watch():
        target_uuid = NUS_SERVICE_UUID.lower()

        def match(device, adv):
            name = device.name or adv.local_name or ""
            service_uuids = [u.lower() for u in (adv.service_uuids or [])]
            return name == BLE_DEVICE_NAME or target_uuid in service_uuids

        return await BleakScanner.find_device_by_filter(match, timeout=SCAN_TIMEOUT_S)

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
        data = collect(opencode_db, opencode_go)
        payload = compact(data)
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


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _load_env_file():
    """Load a gitignored .env from the repo root (or CWD) if present. Keys set
    in the real environment win — .env only fills the gaps."""
    for base in (os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 os.getcwd()):
        path = os.path.join(base, ".env")
        if not os.path.exists(path):
            continue
        try:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    key, val = key.strip(), val.strip()
                    if key and key not in os.environ:
                        os.environ[key] = val
            print(f"loaded env from {path}")
        except OSError:
            pass
        break


def _resolve_opencode_go(args):
    """Prefer --go-* flags, fall back to OPENCODE_GO_* env vars."""
    ws = args.go_workspace or os.environ.get("OPENCODE_GO_WORKSPACE_ID", "").strip()
    ck = args.go_cookie or os.environ.get("OPENCODE_GO_AUTH_COOKIE", "").strip()
    if ws and ck:
        return {"workspace_id": ws, "auth_cookie": ck}
    if ws or ck:
        print("WARN: need BOTH OPENCODE_GO_WORKSPACE_ID and OPENCODE_GO_AUTH_COOKIE "
              "to fetch the Go quota (falling back to local usage only)",
              file=sys.stderr)
    return None


def main():
    _load_env_file()

    parser = argparse.ArgumentParser(description="CC Island StopWatch bridge")
    parser.add_argument("--json", action="store_true", help="one-shot full JSON")
    parser.add_argument("--serve", nargs="?", const=8080, type=int, metavar="PORT",
                        help="WiFi polling HTTP server (default port 8080)")
    parser.add_argument("--ble", nargs="?", const=5, type=float, metavar="MINS",
                        help="BLE push every N minutes (needs bleak)")
    parser.add_argument("--db", metavar="PATH", default=None,
                        help=("OpenCode SQLite path (auto-detected; stable "
                              f"default {DEFAULT_OPENCODE_DB})"))
    parser.add_argument("--go-workspace", metavar="WRK_ID", default=None,
                        help="OpenCode Go workspace id (or OPENCODE_GO_WORKSPACE_ID)")
    parser.add_argument("--go-cookie", metavar="AUTH_COOKIE", default=None,
                        help="OpenCode Go 'auth' cookie from the browser (or OPENCODE_GO_AUTH_COOKIE)")
    args = parser.parse_args()

    go = _resolve_opencode_go(args)

    if args.serve is not None:
        serve(args.serve, opencode_db=args.db, opencode_go=go)
        return

    if args.ble is not None:
        print(f"BLE push every {args.ble:g} min (Ctrl-C to stop)")
        import asyncio
        asyncio.run(ble_loop(int(args.ble * 60), opencode_db=args.db, opencode_go=go))
        return

    data = collect(args.db, go)
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print(render(data))


if __name__ == "__main__":
    main()
