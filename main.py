# snappy_safe_all.py
"""
SNAPPY SAFE — All-in-one automation bot
Features:
 - Multi-token (round-robin)
 - /help, /ping, /status
 - /spam (count or 'inf' for infinite)
 - /imagespam (reply photo) (count or 'inf')
 - /dpchange (reply photo) infinite DP/PFP loop
 - /rename, /autorename (infinite if count omitted), /Stoprnm
 - /ultrarnm (fast emoji rename loop)
 - /changepfp_playlist_start /changepfp_playlist_stop
 - /slidespam (safe single-reply mode)
 - /spnc and /all combos
 - /announce (owner), /autoleavegc, /autoleaveallgc
 - /speed per-chat (adaptive autospeed on RetryAfter)
 - Sudo / Owner management
Notes:
 - The bot will adapt delays on RetryAfter/network problems.
 - Running true "infinite" loops is supported, but Telegram may throttle or ban accounts that abuse limits.
"""

import asyncio
import os
import json
import random
import tempfile
import time
from pathlib import Path
from typing import Dict, Set, List, Callable, Any, Coroutine, Optional

from telegram import Update
from telegram.error import RetryAfter, TimedOut, NetworkError
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

# ---------------- CONFIG ----------------
TOKENS = [
    "8366785937:AAGIiR80rjzuSkB7OtNc4ztNsHPg2EPBuaM",
    "8556107583:AAEeLtccZXOVl08vETDj4BLT71nnRGoLGL4",
    "8423318697:AAGxg1WdnOMk9MzZHhJPmwVXq5gXPrZkgRM",
    "8545027440:AAGTOQ3HvLepTsDTTvvl_9N5KtYwS0jwzwM",
    "8135497087:AAFm6hpcDMiYn-Zm-8GFq2rQLSA2X4EOgS8",
    "8460058132:AAGF62ahgM07bib5Kc-pZCOQxkkiRME0EQo",
    "8384337128:AAF20lPFWcTTKtvjV56OMT-8YDigelTEJxE",
    "8372572857:AAFi3gCPNIwJ4iD6QJsnNiJ22AhBg40Q_pQ",
    "8580311855:AAEuC-IGIuD-6UK8OpB7H8ePZ5h1TZVEqTc",
    "8519232314:AAEV4BQ5L2FZRsAaGIZtIW8k75xMygs_5OE",
    "8438070958:AAH9kAHj3kdNRifTLZsCpIClKqAdU2vl-x8",
    "8503929519:AAF_x1rFQZ9MMxYK2Y76dodNBIRDLC2iWf0",
    "8568976147:AAErWHmmRCWZzWJTZ0Ruv1Nw3CKrVT4sacQ",
    "8286703321:AAFDTA2iyHctSsHeSVafypsGywKwjI7x0nU",
]
OWNER_ID =  5915051224  # <-- your Telegram user id
PFP_FOLDER = "pfp"

# Performance & safety tuning
MIN_DELAY = 0.05        # absolute minimum delay (seconds)
AUTO_STEP = 0.5         # add to delay when RetryAfter seen
INITIAL_BACKOFF = 0.5
MAX_BACKOFF = 30.0
MAX_RETRIES = 8

# safety caps for *single-invocation* spam (you can pass 'inf' to run indefinitely)
DEFAULT_SAFE_TEXT_CAP = 500
DEFAULT_SAFE_IMAGE_CAP = 200

SUDO_FILE = "sudo.json"
STATE_FILE = "snappy_all_state.json"

# emoji pool (101-like)
EMOJIS = [
 "🔥","⚡","💥","💀","🕊","💫","🌪","🐉","👑","🌟","💎","🎭","🚀","✨","🔮",
 "🎯","🌀","🐺","🦅","🐍","🎇","🎆","💠","💣","🧨","🎉","🎊","🌈","🌊","🌙",
 "⭐","🌞","🌝","🌛","🌚","☄️","🌋","🏆","🥇","🎖️","🏅","🎗️","🏵️","🌺","🌸",
 "🌼","🌻","🌹","⚓","🛡️","⚔️","🪄","🧿","🪶","🕹️","🎮","🎲","🧩","🎵","🎶",
 "🎼","🎧","🎤","🎷","🎸","🎺","🥁","📯","📀","📣","📯","🛸","🛰️","🏹","🗡️",
 "🛡️","🩸","⚗️","🔭","🔬","💉","🧪","📚","📖","📝","✒️","🖋️","🖊️","✏️","📐",
 "📏","🧭","🔧","⚙️","🔩","🧱","🏗️","🏛️","🧭","🗺️","🧭","🔔","🔕","💡","🔦"
]

# ---------------- RUNTIME STATE ----------------
apps: List[Application] = []
running_tasks: Dict[str, asyncio.Task] = {}   # key: "<token_idx>:<chat_id>:<action>"
KNOWN_CHATS: Set[int] = set()
delay_settings: Dict[int, float] = {}
SUDO_USERS: Set[int] = set()
pfp_indexes: Dict[int, int] = {}
SLIDE_TARGETS: Set[int] = set()

AUTO_MODE = True

# ---------------- Persistence ----------------
if os.path.exists(SUDO_FILE):
    try:
        with open(SUDO_FILE, "r") as f:
            SUDO_USERS = set(int(x) for x in json.load(f))
    except Exception:
        SUDO_USERS = {OWNER_ID}
else:
    SUDO_USERS = {OWNER_ID}
with open(SUDO_FILE, "w") as f:
    json.dump(list(SUDO_USERS), f)

if os.path.exists(STATE_FILE):
    try:
        with open(STATE_FILE, "r") as f:
            _d = json.load(f)
            KNOWN_CHATS = set(map(int, _d.get("known_chats", [])))
            delay_settings = {int(k): float(v) for k, v in _d.get("delay_settings", {}).items()}
    except Exception:
        KNOWN_CHATS = set()
        delay_settings = {}
else:
    KNOWN_CHATS = set()
    delay_settings = {}

def save_state():
    try:
        with open(STATE_FILE, "w") as f:
            json.dump({
                "known_chats": list(KNOWN_CHATS),
                "delay_settings": {str(k): v for k, v in delay_settings.items()}
            }, f, indent=2)
    except Exception:
        pass

def save_sudo():
    with open(SUDO_FILE, "w") as f:
        json.dump(list(SUDO_USERS), f)

# ---------------- Helpers ----------------
def is_owner(uid: Optional[int]) -> bool:
    return uid == OWNER_ID

def is_sudo(uid: Optional[int]) -> bool:
    return (uid in SUDO_USERS) or is_owner(uid)

def register_chat(update: Update):
    try:
        cid = update.effective_chat.id
        if cid:
            KNOWN_CHATS.add(cid)
            save_state()
    except Exception:
        pass

def get_delay(chat_id: int) -> float:
    return max(MIN_DELAY, float(delay_settings.get(chat_id, MIN_DELAY)))

def key(token_idx: int, chat_id: int, action: str) -> str:
    return f"{token_idx}:{chat_id}:{action}"

async def cancel_task_key(k: str):
    t = running_tasks.get(k)
    if t:
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass
        running_tasks.pop(k, None)

def owner_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id if update.effective_user else None
        if not is_owner(uid):
            if update.message:
                await update.message.reply_text("❌ Owner-only command.")
            return
        return await func(update, context)
    return wrapper

def sudo_only(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id if update.effective_user else None
        if not is_sudo(uid):
            if update.message:
                await update.message.reply_text("❌ Sudo/Owner only.")
            return
        return await func(update, context)
    return wrapper

# ---------------- Multi-token helpers ----------------
def choose_token_index() -> int:
    if not apps:
        return 0
    return random.randrange(len(apps))

async def exec_via_token(token_idx: int, chat_id: int, coro_maker: Callable[[Any], Coroutine[Any, Any, Any]]):
    bot = apps[token_idx].bot
    return await safe_call(lambda: coro_maker(bot), chat_id)

# ---------------- Safe network wrapper ----------------
async def safe_call(coro_factory: Callable[[], Coroutine[Any, Any, Any]], chat_id: int, on_retry_increase_delay: bool = True):
    backoff = INITIAL_BACKOFF
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return await coro_factory()
        except RetryAfter as e:
            wait = getattr(e, "retry_after", None) or backoff
            if AUTO_MODE and on_retry_increase_delay:
                delay_settings[chat_id] = max(get_delay(chat_id), wait + AUTO_STEP)
                save_state()
            await asyncio.sleep(wait)
            backoff = min(backoff * 1.3, MAX_BACKOFF)
            continue
        except (TimedOut, NetworkError, asyncio.TimeoutError):
            jitter = random.random() * 0.5 * backoff
            sleep_for = backoff + jitter
            if AUTO_MODE and on_retry_increase_delay:
                delay_settings[chat_id] = max(get_delay(chat_id), sleep_for)
                save_state()
            await asyncio.sleep(sleep_for)
            backoff = min(backoff * 1.3, MAX_BACKOFF)
            continue
        except Exception:
            raise
    raise TimeoutError("Operation failed after retries")

# ---------------- File helpers ----------------
def write_temp_bytes(b: bytes, suffix: str = ".jpg") -> str:
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tf:
        tf.write(b)
        return tf.name

def list_pfp_files() -> List[str]:
    p = Path(PFP_FOLDER)
    if not p.exists() or not p.is_dir():
        return []
    exts = {".jpg", ".jpeg", ".png", ".webp"}
    return [str(f) for f in sorted(p.iterdir()) if f.suffix.lower() in exts and f.is_file()]

# ---------------- Commands ----------------
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_chat(update)
    await update.message.reply_text(
        "𓆩𓆩⃟⚡𝐍𝐎𝐁𝐈𝐗 ~भगवान हूँ-🔱 ⃟𓆪𓆪\n"
        "━━━━━━━━━━━━━━━━━━\n"
        "✨ 𝐍𝐎𝐁𝐈𝐗 𝐒𝐀𝐅𝐄 — 𝐌𝐞𝐧𝐮 ✨\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "⚡ /spam <count|inf> <text>\n"
        "⚡ /Stopspm\n"
        "📸 /imagespam <count|inf> (reply)\n"
        "📵 /Stopimgspm\n"
        "🌀 /dpchange (reply)\n"
        "🛑 /Stoppfp\n"
        "✏️ /rename <text>\n"
        "♻️ /autorename <sec> <text>\n"
        "🛑 /Stoprnm\n"
        "🚀 /ultrarnm <text>\n"
        "📂 /changepfp_playlist_start <sec>\n"
        "🛑 /changepfp_playlist_stop\n"
        "🎯 /spnc <count|inf> <text>\n"
        "🌪 /all <rename_text> [interval]\n"
        "🎞 /slidespam (reply) <text>\n"
        "🛑 /slidestop\n"
        "📢 /announce <msg>\n"
        "🚪 /autoleavegc\n"
        "💨 /autoleaveallgc\n"
        "⚙️ /speed <sec>\n"
        "🏓 /ping | 📊 /status | 🧾 /help\n"
        "👑 /addsudo | ❌ /delsudo | 📜 /Listsudo | 🫅 /Owner\n"
        "🛑 /stop\n\n"
        "⚙️ *Adaptive Speed*: Auto adjusts delays on RetryAfter\n"
        "📁 PFP Folder → pfp/"
    )

# ping & status & speed
async def ping_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    start = time.time()
    m = await update.message.reply_text("🏓 Pinging...")
    elapsed = int((time.time() - start) * 1000)
    await m.edit_text(f"🏓 Pong: {elapsed} ms")

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_chat(update)
    cid = update.message.chat_id
    tasks = [k for k in running_tasks if f":{cid}:" in k]
    await update.message.reply_text(
        f"📊 STATUS\nChat: {cid}\nActive tasks: {len(tasks)}\nTasks: {tasks}\nKnown chats: {len(KNOWN_CHATS)}\nDelay: {get_delay(cid)}s\nTokens: {len(apps)}"
    )

@sudo_only
async def speed_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.message.chat_id
    if not context.args:
        return await update.message.reply_text(f"Current delay: {get_delay(cid)}s")
    try:
        v = float(context.args[0])
    except:
        return await update.message.reply_text("Enter a numeric value (seconds)")
    if v < MIN_DELAY:
        return await update.message.reply_text(f"Min delay is {MIN_DELAY}s")
    delay_settings[cid] = v
    save_state()
    await update.message.reply_text(f"Delay set to {v}s for this chat")

# ---------------- Text spam (count or infinite) ----------------
@sudo_only
async def spam_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_chat(update)
    if len(context.args) < 1:
        return await update.message.reply_text("Usage: /spam <count|inf> <text>")
    # detect count
    first = context.args[0]
    text = " ".join(context.args[1:]) if len(context.args) > 1 else ""
    infinite = (first.lower() == "inf" or first == "0")
    try:
        count = int(first) if not infinite else None
    except:
        # if count omitted and text provided, treat as infinite with first token part of text
        infinite = True
        text = " ".join(context.args)
        count = None

    if not text.strip():
        return await update.message.reply_text("No text provided to spam.")

    # if not infinite and count huge, cap it (safety)
    if not infinite and count > DEFAULT_SAFE_TEXT_CAP:
        return await update.message.reply_text(f"Count too large. Max per-invocation: {DEFAULT_SAFE_TEXT_CAP}")

    cid = update.message.chat_id
    tok_idx = choose_token_index()
    k = key(tok_idx, cid, "spam")
    await cancel_task_key(k)

    async def worker():
        d = get_delay(cid)
        try:
            if infinite:
                while True:
                    try:
                        await exec_via_token(tok_idx, cid, lambda bot: bot.send_message(cid, text))
                    except Exception:
                        await asyncio.sleep(d)
                    await asyncio.sleep(d)
            else:
                for _ in range(count):
                    try:
                        await exec_via_token(tok_idx, cid, lambda bot: bot.send_message(cid, text))
                    except Exception:
                        await asyncio.sleep(d)
                    await asyncio.sleep(d)
        except asyncio.CancelledError:
            pass
        finally:
            running_tasks.pop(k, None)

    running_tasks[k] = asyncio.create_task(worker())
    await update.message.reply_text(f"✅ Text spam started ({'infinite' if infinite else f'{count} msgs'})")

@sudo_only
async def stop_spam_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.message.chat_id
    keys = [k for k in running_tasks if k.endswith(f":{cid}:spam")]
    for k in keys:
        await cancel_task_key(k)
    await update.message.reply_text("⛔ Text spam stopped")

# ---------------- Image spam (count or infinite) ----------------
@sudo_only
async def imagespam_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_chat(update)
    if not update.message.reply_to_message or not update.message.reply_to_message.photo:
        return await update.message.reply_text("Reply to a photo and use /imagespam <count|inf>")
    if not context.args:
        return await update.message.reply_text("Usage: /imagespam <count|inf>")
    first = context.args[0]
    infinite = (first.lower() == "inf" or first == "0")
    try:
        count = int(first) if not infinite else None
    except:
        infinite = True
        count = None

    if not infinite and count > DEFAULT_SAFE_IMAGE_CAP:
        return await update.message.reply_text(f"Count too large. Max per-invocation: {DEFAULT_SAFE_IMAGE_CAP}")

    cid = update.message.chat_id
    tok_idx = choose_token_index()
    k = key(tok_idx, cid, "imagespam")
    await cancel_task_key(k)

    photo = update.message.reply_to_message.photo[-1]
    f = await photo.get_file()
    img_bytes = await f.download_as_bytearray()

    async def worker():
        d = get_delay(cid)
        try:
            if infinite:
                while True:
                    tmp = write_temp_bytes(img_bytes, ".jpg")
                    try:
                        await exec_via_token(tok_idx, cid, lambda bot: bot.send_photo(cid, open(tmp, "rb")))
                    except Exception:
                        await asyncio.sleep(d)
                    finally:
                        try: os.remove(tmp)
                        except: pass
                    await asyncio.sleep(d)
            else:
                for _ in range(count):
                    tmp = write_temp_bytes(img_bytes, ".jpg")
                    try:
                        await exec_via_token(tok_idx, cid, lambda bot: bot.send_photo(cid, open(tmp, "rb")))
                    except Exception:
                        await asyncio.sleep(d)
                    finally:
                        try: os.remove(tmp)
                        except: pass
                    await asyncio.sleep(d)
        except asyncio.CancelledError:
            pass
        finally:
            running_tasks.pop(k, None)

    running_tasks[k] = asyncio.create_task(worker())
    await update.message.reply_text(f"📸 Image spam started ({'infinite' if infinite else f'{count} imgs'})")

@sudo_only
async def stop_imagespam_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.message.chat_id
    keys = [k for k in running_tasks if k.endswith(f":{cid}:imagespam")]
    for k in keys:
        await cancel_task_key(k)
    await update.message.reply_text("⛔ Image spam stopped")

# ---------------- DP / PFP change (infinite loop) ----------------
@sudo_only
async def dpchange_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_chat(update)
    if not update.message.reply_to_message or not update.message.reply_to_message.photo:
        return await update.message.reply_text("Reply to a photo and use /dpchange")
    cid = update.message.chat_id
    tok_idx = choose_token_index()
    k = key(tok_idx, cid, "dpchange")
    await cancel_task_key(k)

    fobj = await update.message.reply_to_message.photo[-1].get_file()
    img_bytes = await fobj.download_as_bytearray()

    async def worker():
        d = get_delay(cid)
        try:
            while True:
                tmp = write_temp_bytes(img_bytes, ".jpg")
                try:
                    await exec_via_token(tok_idx, cid, lambda bot: bot.set_chat_photo(cid, open(tmp, "rb")))
                except Exception:
                    await asyncio.sleep(d)
                finally:
                    try: os.remove(tmp)
                    except: pass
                await asyncio.sleep(d)
        except asyncio.CancelledError:
            pass
        finally:
            running_tasks.pop(k, None)

    running_tasks[k] = asyncio.create_task(worker())
    await update.message.reply_text("🌀 DP/PFP auto-change started (infinite). Use /Stoppfp to stop.")

@sudo_only
async def changepfp_playlist_stop(cid):
    # cancel any dpchange/playlist task for this chat_id
    keys = []
    for k in running_tasks:
        if f":{cid}:dpchange" in k or f":{cid}:changepfp" in k:
            keys.append(k)

    for k in keys:
        await cancel_task_key(k)

# ---------------- Rename, autorename, ultrarnm ----------------
@sudo_only
async def rename_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Usage: /rename <text>")
    title = " ".join(context.args)
    cid = update.message.chat_id
    tok_idx = choose_token_index()
    try:
        await exec_via_token(tok_idx, cid, lambda bot: bot.set_chat_title(cid, title))
        await update.message.reply_text("✅ Renamed")
    except Exception as e:
        await update.message.reply_text(f"Rename failed: {e}")

@sudo_only
async def autorename_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_chat(update)
    if len(context.args) < 2:
        return await update.message.reply_text("Usage: /autorename <interval_seconds> <text>")
    try:
        interval = float(context.args[0])
    except:
        return await update.message.reply_text("Invalid interval")
    if interval < MIN_DELAY:
        return await update.message.reply_text(f"Interval too low; minimum {MIN_DELAY}s")
    text = " ".join(context.args[1:])
    cid = update.message.chat_id
    tok_idx = choose_token_index()
    k = key(tok_idx, cid, "autorename")
    await cancel_task_key(k)

    async def worker():
        i = 0
        d = interval
        try:
            while True:
                i += 1
                title = f"{text} {i}"
                try:
                    await exec_via_token(tok_idx, cid, lambda bot: bot.set_chat_title(cid, title))
                except Exception:
                    await asyncio.sleep(d)
                await asyncio.sleep(d)
        except asyncio.CancelledError:
            pass
        finally:
            running_tasks.pop(k, None)

    running_tasks[k] = asyncio.create_task(worker())
    await update.message.reply_text(f"🔁 Autorename started every {interval}s (use /Stoprnm to stop)")

@sudo_only
async def stop_rnm_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.message.chat_id
    keys = [k for k in running_tasks if k.endswith(f":{cid}:autorename")]
    for k in keys:
        await cancel_task_key(k)
    await update.message.reply_text("⛔ Autorename stopped")

@sudo_only
async def ultrarnm_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_chat(update)
    if not context.args:
        return await update.message.reply_text("Usage: /ultrarnm <text>")
    base = " ".join(context.args)
    cid = update.message.chat_id
    tok_idx = choose_token_index()
    k = key(tok_idx, cid, "ultrarnm")
    await cancel_task_key(k)

    async def worker():
        try:
            while True:
                picks = random.sample(EMOJIS, min(6, len(EMOJIS)))
                left = " ".join(picks[:3])
                right = " ".join(picks[3:]) if len(picks) > 3 else ""
                title = f"{left} {base} {right}".strip()
                try:
                    await exec_via_token(tok_idx, cid, lambda bot: bot.set_chat_title(cid, title))
                except Exception:
                    await asyncio.sleep(max(get_delay(cid), 0.02))
                await asyncio.sleep(get_delay(cid))
        except asyncio.CancelledError:
            pass
        finally:
            running_tasks.pop(k, None)

    running_tasks[k] = asyncio.create_task(worker())
    await update.message.reply_text("⚡ Ultra rename started (use /stop to stop)")

# ---------------- changepfp playlist ----------------
@sudo_only
async def changepfp_playlist_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_chat(update)
    cid = update.message.chat_id
    files = list_pfp_files()
    if not files:
        return await update.message.reply_text(f"No images found in '{PFP_FOLDER}/'. Add images and retry.")
    interval = get_delay(cid)
    if context.args:
        try:
            interval = float(context.args[0])
        except:
            return await update.message.reply_text("Invalid interval")
    if interval < MIN_DELAY:
        return await update.message.reply_text(f"Interval too low; Minimum {MIN_DELAY}s")
    tok_idx = choose_token_index()
    k = key(tok_idx, cid, "pfp_playlist")
    await cancel_task_key(k)
    pfp_indexes[cid] = pfp_indexes.get(cid, 0)

    async def worker():
        idx = pfp_indexes.get(cid, 0)
        try:
            while True:
                files_now = list_pfp_files()
                if not files_now:
                    await asyncio.sleep(interval)
                    continue
                path = files_now[idx % len(files_now)]
                try:
                    await exec_via_token(tok_idx, cid, lambda bot: bot.set_chat_photo(cid, open(path, "rb")))
                except Exception:
                    await asyncio.sleep(max(interval, 0.2))
                idx += 1
                pfp_indexes[cid] = idx
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass
        finally:
            pfp_indexes.pop(cid, None)
            running_tasks.pop(k, None)

    running_tasks[k] = asyncio.create_task(worker())
    await update.message.reply_text(f"📸 PFP playlist started every {interval}s")

@sudo_only
async def stoppfp_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.message.chat_id

    keys = []
    for k in running_tasks:
        # match both dpchange & playlist tasks for any token
        if f":{cid}:dpchange" in k or f":{cid}:changepfp" in k:
            keys.append(k)

    for k in keys:
        await cancel_task_key(k)

    await update.message.reply_text("⛔ DP/PFP change stopped")

# ---------------- slidespam ----------------
@sudo_only
async def slidespam_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        return await update.message.reply_text("Reply to a message and use /slidespam <text>")
    if not context.args:
        return await update.message.reply_text("Usage: /slidespam <text>")
    uid = update.message.reply_to_message.from_user.id
    SLIDE_TARGETS.add(uid)
    await update.message.reply_text("✅ Slidespam target added (bot replies once when target posts)")

@sudo_only
async def slidestop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        return await update.message.reply_text("Reply to a message and use /slidestop")
    uid = update.message.reply_to_message.from_user.id
    SLIDE_TARGETS.discard(uid)
    await update.message.reply_text("⛔ Slidespam target removed")

async def auto_reply_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_chat(update)
    uid = update.effective_user.id
    if uid in SLIDE_TARGETS:
        try:
            await update.message.reply_text("🔁 Auto-reply (slidespam).")
        except Exception:
            pass

# ---------------- combos: spnc / all ----------------
@sudo_only
async def spnc_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_chat(update)
    if len(context.args) < 1:
        return await update.message.reply_text("Usage: /spnc <count|inf> <text>")
    first = context.args[0]
    infinite = (first.lower() == "inf" or first == "0")
    try:
        count = int(first) if not infinite else None
    except:
        infinite = True
        count = None
    text = " ".join(context.args[1:]) if len(context.args) > 1 else ""
    if not text:
        return await update.message.reply_text("No text provided.")
    cid = update.message.chat_id
    tok_idx = choose_token_index()
    k = key(tok_idx, cid, "spnc")
    await cancel_task_key(k)

    async def worker():
        d = get_delay(cid)
        try:
            if infinite:
                i = 0
                while True:
                    i += 1
                    try:
                        await exec_via_token(tok_idx, cid, lambda bot: bot.send_message(cid, text))
                        await exec_via_token(tok_idx, cid, lambda bot: bot.set_chat_title(cid, f"{text} {i}"))
                    except Exception:
                        await asyncio.sleep(d)
                    await asyncio.sleep(d)
            else:
                for i in range(count):
                    try:
                        await exec_via_token(tok_idx, cid, lambda bot: bot.send_message(cid, text))
                        await exec_via_token(tok_idx, cid, lambda bot: bot.set_chat_title(cid, f"{text} {i+1}"))
                    except Exception:
                        await asyncio.sleep(d)
                    await asyncio.sleep(d)
        except asyncio.CancelledError:
            pass
        finally:
            running_tasks.pop(k, None)

    running_tasks[k] = asyncio.create_task(worker())
    await update.message.reply_text(f"✅ /spnc started ({'inf' if infinite else count})")

@sudo_only
async def stop_spnc_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.message.chat_id
    keys = [k for k in running_tasks if k.endswith(f":{cid}:spnc")]
    for k in keys:
        await cancel_task_key(k)
    await update.message.reply_text("⛔ /spnc stopped")

@sudo_only
async def all_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Usage: /all <rename_text> [pfp_interval]")
    cid = update.message.chat_id
    rename_text = context.args[0]
    pfp_interval = None
    if len(context.args) >= 2:
        try:
            pfp_interval = float(context.args[1])
        except:
            return await update.message.reply_text("Invalid pfp interval")
    # cancel existing
    tok_idx = choose_token_index()
    rk = key(tok_idx, cid, "all_rename")
    pk = key(tok_idx, cid, "all_pfp")
    await cancel_task_key(rk); await cancel_task_key(pk)

    async def rename_worker():
        i = 0
        try:
            while True:
                i += 1
                emo_pair = random.sample(EMOJIS, 2)
                title = f"{emo_pair[0]} {rename_text} {emo_pair[1]} {i}"
                try:
                    await exec_via_token(tok_idx, cid, lambda bot: bot.set_chat_title(cid, title))
                except Exception:
                    await asyncio.sleep(max(get_delay(cid), 0.2))
                await asyncio.sleep(get_delay(cid))
        except asyncio.CancelledError:
            pass

    async def pfp_worker():
        idx = 0
        try:
            while True:
                files = list_pfp_files()
                if not files:
                    await asyncio.sleep(get_delay(cid)); continue
                d = pfp_interval if pfp_interval is not None else get_delay(cid)
                path = files[idx % len(files)]
                try:
                    await exec_via_token(tok_idx, cid, lambda bot: bot.set_chat_photo(cid, open(path, "rb")))
                except Exception:
                    await asyncio.sleep(max(d, 0.2))
                idx += 1
                await asyncio.sleep(d)
        except asyncio.CancelledError:
            pass

    running_tasks[rk] = asyncio.create_task(rename_worker())
    running_tasks[pk] = asyncio.create_task(pfp_worker())
    await update.message.reply_text("✅ /all started — rename + pfp playlist (use /stop)")

# ---------------- announce / autoleave ----------------
@owner_only
async def announce_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        return await update.message.reply_text("Usage: /announce <message>")
    msg = " ".join(context.args)
    targets = list(KNOWN_CHATS)
    if not targets:
        return await update.message.reply_text("No known chats.")
    await update.message.reply_text(f"Sending to {len(targets)} known chats (rate-limited).")
    for cid in targets:
        try:
            await safe_call(lambda: apps[choose_token_index()].bot.send_message(cid, msg), cid)
        except Exception:
            pass
        await asyncio.sleep(get_delay(cid))

@sudo_only
async def autoleavegc_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.message.chat_id
    await update.message.reply_text("👋 Leaving this group...")
    try:
        await context.bot.leave_chat(cid)
        KNOWN_CHATS.discard(cid); save_state()
    except Exception as e:
        await update.message.reply_text(f"Failed to leave: {e}")

@owner_only
async def autoleaveallgc_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keep = update.message.chat_id
    left = 0
    for cid in list(KNOWN_CHATS):
        if cid == keep:
            continue
        try:
            await context.bot.leave_chat(cid)
            KNOWN_CHATS.discard(cid)
            left += 1
        except Exception:
            pass
    save_state()
    await update.message.reply_text(f"Left {left} groups. Stayed here.")

# ---------------- admin / sudo management ----------------
@owner_only
async def addsudo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        return await update.message.reply_text("Reply to a user's message to add sudo.")
    uid = update.message.reply_to_message.from_user.id
    SUDO_USERS.add(uid); save_sudo()
    await update.message.reply_text(f"✅ Added sudo: {uid}")

@owner_only
async def delsudo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        return await update.message.reply_text("Reply to a user's message to remove sudo.")
    uid = update.message.reply_to_message.from_user.id
    SUDO_USERS.discard(uid); save_sudo()
    await update.message.reply_text(f"✅ Removed sudo: {uid}")

async def listsudo_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("SUDO USERS:\n" + "\n".join(map(str, sorted(SUDO_USERS))))

async def owner_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Owner: {OWNER_ID}")

# ---------------- generic stop ----------------
@sudo_only
async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.message.chat_id
    # cancel tasks that reference this chat
    keys = [k for k in list(running_tasks.keys()) if f":{cid}:" in k]
    for k in keys:
        await cancel_task_key(k)
    await update.message.reply_text("⛔ Stopped all loops in this chat")

# ---------------- message handlers ----------------
async def message_register_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register_chat(update)

# ---------------- build app ----------------
def build_app(token: str) -> Application:
    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("ping", ping_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("speed", speed_cmd))
    # spam
    app.add_handler(CommandHandler("spam", spam_cmd))
    app.add_handler(CommandHandler("Stopspm", stop_spam_cmd))
    app.add_handler(CommandHandler("imagespam", imagespam_cmd))
    app.add_handler(CommandHandler("Stopimgspm", stop_imagespam_cmd))
    # dp/pfp
    app.add_handler(CommandHandler("dpchange", dpchange_cmd))
    app.add_handler(CommandHandler("Stoppfp", stoppfp_cmd))
    app.add_handler(CommandHandler("changepfp_playlist_start", changepfp_playlist_start))
    app.add_handler(CommandHandler("changepfp_playlist_stop", changepfp_playlist_stop))
    # rename
    app.add_handler(CommandHandler("rename", rename_cmd))
    app.add_handler(CommandHandler("autorename", autorename_cmd))
    app.add_handler(CommandHandler("Stoprnm", stop_rnm_cmd))
    app.add_handler(CommandHandler("ultrarnm", ultrarnm_cmd))
    # combos
    app.add_handler(CommandHandler("spnc", spnc_cmd))
    app.add_handler(CommandHandler("stopspnc", stop_spnc_cmd))
    app.add_handler(CommandHandler("all", all_cmd))
    # slides
    app.add_handler(CommandHandler("slidespam", slidespam_cmd))
    app.add_handler(CommandHandler("slidestop", slidestop_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, auto_reply_handler))
    # announce / leave / admin
    app.add_handler(CommandHandler("announce", announce_cmd))
    app.add_handler(CommandHandler("autoleavegc", autoleavegc_cmd))
    app.add_handler(CommandHandler("autoleaveallgc", autoleaveallgc_cmd))
    app.add_handler(CommandHandler("addsudo", addsudo_cmd))
    app.add_handler(CommandHandler("delsudo", delsudo_cmd))
    app.add_handler(CommandHandler("Listsudo", listsudo_cmd))
    app.add_handler(CommandHandler("Owner", owner_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))
    # register chats
    app.add_handler(MessageHandler(filters.ALL, message_register_handler))
    return app

# ---------------- runner ----------------
async def run_all():
    Path(PFP_FOLDER).mkdir(parents=True, exist_ok=True)
    for token in TOKENS:
        t = token.strip()
        if not t:
            continue
        app = build_app(t)
        apps.append(app)

    for app in apps:
        try:
            await app.initialize()
            await app.start()
            try:
                await app.updater.start_polling()
            except Exception:
                # some PTB versions differ; ignore
                pass
            print("Started bot token prefix:", (app.bot.token[:8] if app.bot and app.bot.token else "unknown"))
        except Exception as e:
            print("Failed starting a bot:", e)

    print(f"✅ Started {len(apps)} bot(s).")
    try:
        await asyncio.Event().wait()
    finally:
        for app in apps:
            try:
                await app.updater.stop_polling()
            except Exception:
                pass
            try:
                await app.stop()
            except Exception:
                pass
        save_state()
        save_sudo()

if __name__ == "__main__":
    try:
        asyncio.run(run_all())
    except KeyboardInterrupt:
        print("Shutting down...")
        save_state()
        save_sudo()
