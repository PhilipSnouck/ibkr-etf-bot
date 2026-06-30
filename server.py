import asyncio
import json
import re
import subprocess
import sys
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

app = FastAPI()

BOT_DIR = Path(__file__).parent
CONFIG_PATH = BOT_DIR / "config_store.json"
DASHBOARD_DIR = BOT_DIR / "dashboard"

ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def strip_ansi(text: str) -> str:
    return ANSI_ESCAPE.sub("", text)


# ------------------------------------------------------------
# PAGES
# ------------------------------------------------------------

@app.get("/")
async def dashboard():
    return FileResponse(DASHBOARD_DIR / "index.html")


@app.get("/settings")
async def settings_page():
    return FileResponse(DASHBOARD_DIR / "settings.html")


# ------------------------------------------------------------
# CONFIG API
# ------------------------------------------------------------

@app.get("/api/config")
async def get_config():
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


@app.put("/api/config")
async def save_config(request: Request):
    data = await request.json()
    CONFIG_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"ok": True}


# ------------------------------------------------------------
# SHUTDOWN
# ------------------------------------------------------------

@app.post("/api/shutdown")
async def shutdown_gateway():
    subprocess.run(["taskkill", "/F", "/IM", "IBGateway.exe"], capture_output=True)
    return {"ok": True}


# ------------------------------------------------------------
# BOT OUTPUT PARSER
# ------------------------------------------------------------

def parse_line(line: str, state: dict) -> list:
    """
    Parses a single line of bot output and returns structured SSE events.
    state is mutated to track current account and table context.
    """
    events = []
    clean = strip_ansi(line).strip()
    if not clean:
        return events

    # Account header: ACCOUNT: Pension
    m = re.match(r"ACCOUNT:\s+(.+)", clean)
    if m:
        state["account"] = m.group(1).strip()
        state["in_preview"] = False
        state["in_exec"] = False
        events.append({"type": "account_start", "name": state["account"]})
        return events

    # Execution-phase header: "Executing account: Pension". The execution
    # summary uses this header (not "ACCOUNT:"), so switch the active account
    # here too; otherwise fills get attributed to the last preview account
    # and that card never flips to "Filled".
    m = re.match(r"Executing account:\s+(.+)", clean)
    if m:
        state["account"] = m.group(1).strip()
        state["in_preview"] = False
        state["in_exec"] = False
        return events

    acc = state.get("account")

    # Usable cash line: "Pension usable cash for this run: EUR 1240.00"
    m = re.match(r".+ usable cash for this run:\s+(\w+)\s+([\d.]+)", clean)
    if m and acc:
        events.append({
            "type": "cash",
            "account": acc,
            "currency": m.group(1),
            "amount": float(m.group(2)),
        })
        return events

    # Section markers
    if "--- ORDER PREVIEW ---" in clean:
        state["in_preview"] = True
        state["in_exec"] = False
        return events

    if "--- EXECUTION SUMMARY ---" in clean:
        state["in_exec"] = True
        state["in_preview"] = False
        return events

    # Section-style --- headers (e.g. "--- MARKET STATUS ---") reset table context.
    # Plain divider lines (e.g. "--------------------") are ignored so they don't
    # interrupt table parsing mid-section.
    if re.match(r"^---\s+\S", clean):
        state["in_preview"] = False
        state["in_exec"] = False
        return events

    # SUMMARY and Top-up must be checked BEFORE the in_preview block because
    # the SUMMARY line contains | and would otherwise be consumed as a table row.

    # SUMMARY line: SUMMARY | VUAA: 60.00% | ... | TOTAL: 536.52 EUR | LEFT: 703.48 EUR
    m = re.match(r"SUMMARY \| (.+)", clean)
    if m and acc:
        state["in_preview"] = False
        parts_str = m.group(1)
        total_m = re.search(r"TOTAL:\s*([\d.]+)\s+(\w+)", parts_str)
        left_m = re.search(r"LEFT:\s*([\d.]+)\s+(\w+)", parts_str)
        if total_m and left_m:
            events.append({
                "type": "summary",
                "account": acc,
                "total_spent": float(total_m.group(1)),
                "leftover": float(left_m.group(1)),
                "currency": total_m.group(2),
            })
        return events

    # Top-up triggered: YES / NO
    m = re.match(r"Top-up triggered:\s*(YES|NO)", clean)
    if m and acc:
        events.append({"type": "topup", "account": acc, "needed": m.group(1) == "YES"})
        return events

    # Preview table data rows: VUAA  |   60.0% |    4.2500 |      4 |     356.48 | normal
    if state.get("in_preview") and "|" in clean:
        parts = [p.strip() for p in clean.split("|")]
        if len(parts) >= 5 and parts[0] and parts[0] != "ETF":
            try:
                symbol = parts[0]
                shares = int(parts[3])
                spent = float(parts[4])
                note = parts[5].strip() if len(parts) > 5 else ""
                price = round(spent / shares, 2) if shares > 0 else 0.0
                events.append({
                    "type": "allocation",
                    "account": acc,
                    "symbol": symbol,
                    "shares": shares,
                    "price": price,
                    "total": spent,
                    "note": note,
                })
            except (ValueError, ZeroDivisionError, IndexError):
                pass
        return events

    # Execution result rows: VUAA  |      4 |      89.45 |     357.80 | Filled
    if state.get("in_exec") and "|" in clean:
        parts = [p.strip() for p in clean.split("|")]
        if len(parts) >= 4 and parts[0] and parts[0] not in ("ETF", "TOTAL"):
            try:
                symbol = parts[0]
                filled = int(float(parts[1]))
                avg_price = float(parts[2])
                total = float(parts[3])
                status = parts[4].strip() if len(parts) > 4 else ""
                events.append({
                    "type": "execution_result",
                    "account": acc,
                    "symbol": symbol,
                    "filled": filled,
                    "avg_price": avg_price,
                    "total": total,
                    "status": status,
                })
            except (ValueError, IndexError):
                pass
        return events

    # Pending top-up status messages
    if "Pending top-up found, but it has expired" in clean:
        events.append({"type": "topup_info", "account": acc, "level": "warning", "message": "Pending top-up expired — running normal allocation"})
        return events

    if re.search(r"Pending top-up found\.", clean):
        events.append({"type": "topup_info", "account": acc, "level": "info", "message": "Pending top-up loaded"})
        return events

    if "Pending top-up is now fully funded" in clean:
        events.append({"type": "topup_info", "account": acc, "level": "success", "message": "Top-up fully funded — order will be placed"})
        return events

    if "Pending top-up is still NOT fully funded" in clean:
        events.append({"type": "topup_info", "account": acc, "level": "warning", "message": "Top-up not yet fully funded"})
        return events

    m = re.match(r"Still missing:\s+(\w+)\s+([\d.]+)", clean)
    if m and acc:
        events.append({"type": "topup_info", "account": acc, "level": "warning", "message": f"Still missing: {m.group(1)} {m.group(2)}"})
        return events

    if "Pending top-up file saved." in clean:
        events.append({"type": "topup_info", "account": acc, "level": "info", "message": "Top-up file saved for next run"})
        return events

    if "Pending top-up file cleared." in clean:
        events.append({"type": "topup_info", "account": acc, "level": "success", "message": "Top-up completed and cleared"})
        return events

    if "Pending top-up file NOT saved because execution was not fully filled" in clean:
        events.append({"type": "topup_info", "account": acc, "level": "warning", "message": "Top-up not saved — order not fully filled"})
        return events

    if "Pending top-up file kept because execution was not fully filled" in clean:
        events.append({"type": "topup_info", "account": acc, "level": "warning", "message": "Top-up file kept — order not fully filled"})
        return events

    # Safety stop
    if re.search(r"[Ss]afety stop", clean):
        events.append({"type": "error", "account": acc, "message": clean})
        return events

    # Approve MFA prompt
    if "Approve the 2FA prompt on your phone" in clean:
        events.append({"type": "mfa_prompt"})
        return events

    return events


# ------------------------------------------------------------
# RUN ENDPOINT (SSE)
# ------------------------------------------------------------

@app.get("/api/run/{mode}")
async def run_bot(mode: str):
    if mode not in ("preview", "execute"):
        raise HTTPException(status_code=400, detail="mode must be 'preview' or 'execute'")

    cmd = [sys.executable, str(BOT_DIR / "main.py")]
    if mode == "execute":
        cmd.append("buy")

    async def stream():
        state = {"account": None, "in_preview": False, "in_exec": False}
        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_event_loop()

        def run_bot_thread():
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    cwd=str(BOT_DIR),
                    bufsize=1,
                    encoding="utf-8",
                    errors="replace",
                )
                for raw_line in proc.stdout:
                    loop.call_soon_threadsafe(queue.put_nowait, ("line", raw_line.rstrip("\n\r")))
                proc.wait()
                loop.call_soon_threadsafe(queue.put_nowait, ("done", proc.returncode))
            except Exception as exc:
                loop.call_soon_threadsafe(queue.put_nowait, ("error", str(exc)))

        thread = threading.Thread(target=run_bot_thread, daemon=True)
        thread.start()

        while True:
            kind, value = await queue.get()
            if kind == "line":
                yield f"data: {json.dumps({'type': 'raw', 'line': value})}\n\n"
                for event in parse_line(value, state):
                    yield f"data: {json.dumps(event)}\n\n"
            elif kind == "done":
                yield f"data: {json.dumps({'type': 'done', 'exit_code': value})}\n\n"
                break
            elif kind == "error":
                yield f"data: {json.dumps({'type': 'raw', 'line': f'Server error: {value}'})}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'exit_code': 1})}\n\n"
                break

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
