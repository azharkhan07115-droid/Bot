#!/usr/bin/env python3
"""
Auto Account Creator Bot
Temp mail (GuerillaMail) -> GitHub -> Render OAuth -> API key -> Telegram
Flask /health keeps Render alive.
"""

import asyncio
import json
import os
import re
import time
import random
import string
import shutil
import requests
import threading
import urllib3
urllib3.disable_warnings()

from flask import Flask, jsonify
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# ── CONFIG ────────────────────────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID   = int(os.environ.get("CHAT_ID", "0"))
PORT      = int(os.environ.get("PORT", "8080"))

state = {
    "accounts":    [],
    "proxy_list":  [],
    "running":     False,
    "pending_otp": None,
    "mail_obj":    None,
}

# ── FLASK HEALTH ──────────────────────────────────────────────────────
flask_app = Flask(__name__)

@flask_app.route("/health")
def health():
    return jsonify({
        "status":   "ok",
        "accounts": len(state["accounts"]),
        "running":  state["running"],
    })

@flask_app.route("/")
def index():
    return jsonify({"bot": "auto-bot", "status": "running"})

def run_flask():
    flask_app.run(host="0.0.0.0", port=PORT, use_reloader=False)

# ── SAFE TELEGRAM SEND ────────────────────────────────────────────────
async def safe_send(bot, text):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=text)
    except Exception:
        pass

# ── GUERRILLAMAIL TEMP MAIL ───────────────────────────────────────────
class TempMail:
    BASE = "https://api.guerrillamail.com/ajax.php"

    def __init__(self):
        self.sid = None
        self.s   = requests.Session()
        self.s.verify = False
        self.s.headers["User-Agent"] = "Mozilla/5.0"

    def generate(self):
        r   = self.s.get(self.BASE, params={"f": "get_email_address"}, timeout=15)
        d   = r.json()
        self.sid = d["sid_token"]
        return d["email_addr"].replace("\\@", "@")

    def wait_for_otp(self, timeout=180):
        seen = set()
        end  = time.time() + timeout
        while time.time() < end:
            try:
                r = self.s.get(
                    self.BASE,
                    params={"f": "get_email_list", "offset": 0, "sid_token": self.sid},
                    timeout=10
                )
                for msg in r.json().get("list", []):
                    mid = msg.get("mail_id")
                    if mid and mid not in seen:
                        seen.add(mid)
                        full = self.s.get(
                            self.BASE,
                            params={"f": "fetch_email", "email_id": mid, "sid_token": self.sid},
                            timeout=10
                        ).json()
                        body = full.get("mail_body", "") + full.get("mail_text", "")
                        m = re.search(r'\b(\d{6,8})\b', body)
                        if m:
                            return m.group(1)
            except:
                pass
            time.sleep(4)
        return None

# ── PROXY ─────────────────────────────────────────────────────────────
def fetch_proxies():
    urls = [
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
        "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    ]
    proxies = []
    for u in urls:
        try:
            r = requests.get(u, timeout=12, verify=False)
            if r.status_code == 200:
                proxies += [l.strip() for l in r.text.split("\n") if l.strip() and ":" in l]
        except:
            pass
    state["proxy_list"] = list(set(proxies))
    return len(state["proxy_list"])

def get_proxy():
    if not state["proxy_list"]:
        fetch_proxies()
    random.shuffle(state["proxy_list"])
    for p in state["proxy_list"][:50]:
        try:
            r = requests.get(
                "http://httpbin.org/ip",
                proxies={"http": f"http://{p}", "https": f"http://{p}"},
                timeout=6, verify=False
            )
            if r.status_code == 200:
                return p
        except:
            pass
    return None

# ── HELPERS ───────────────────────────────────────────────────────────
def rand_pass():
    return ''.join(random.choices(string.ascii_letters + string.digits, k=12)) + "!9"

def rand_user():
    a = ["dark","swift","ghost","iron","quick","cyber","brave","steel"]
    n = ["wolf","fox","hawk","viper","blade","byte","ninja","storm"]
    return f"{random.choice(a)}{random.choice(n)}{random.randint(100,9999)}"

# ── SELENIUM DRIVER FACTORY ───────────────────────────────────────────
def _make_driver(proxy=None):
    import undetected_chromedriver as uc
    opts = uc.ChromeOptions()
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1280,720")
    opts.add_argument("--single-process")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--disable-software-rasterizer")
    if proxy:
        opts.add_argument(f"--proxy-server=http://{proxy}")

    binary = (
        shutil.which("chromium")
        or shutil.which("chromium-browser")
        or shutil.which("google-chrome")
        or shutil.which("google-chrome-stable")
        or "/usr/bin/chromium"
        or "/usr/bin/chromium-browser"
    )
    if binary:
        opts.binary_location = binary

    return uc.Chrome(options=opts)

def _wait_element(driver, by, selector, timeout=15):
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    return WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((by, selector))
    )

# ── GITHUB ACCOUNT ────────────────────────────────────────────────────
def _github_sync(email, username, password, mail_obj, notify_q):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.common.action_chains import ActionChains

    proxy = get_proxy()
    if proxy:
        notify_q.append(f"Proxy: {proxy}")

    driver = _make_driver(proxy)
    try:
        notify_q.append("GitHub signup open...")
        driver.get("https://github.com/signup")
        time.sleep(2)

        el = _wait_element(driver, By.ID, "email")
        el.clear(); el.send_keys(email); time.sleep(0.5)
        el.send_keys(Keys.RETURN); time.sleep(1)

        el = _wait_element(driver, By.ID, "password")
        el.send_keys(password); time.sleep(0.5)
        el.send_keys(Keys.RETURN); time.sleep(1)

        el = _wait_element(driver, By.ID, "login")
        el.send_keys(username); time.sleep(1)
        el.send_keys(Keys.RETURN); time.sleep(1)

        try:
            for lbl in driver.find_elements(By.TAG_NAME, "label"):
                if lbl.text.strip().lower().startswith("n"):
                    lbl.click(); break
        except:
            pass
        ActionChains(driver).send_keys(Keys.RETURN).perform()
        time.sleep(1)

        notify_q.append("Captcha wait 10s...")
        time.sleep(10)

        try:
            for btn in driver.find_elements(By.TAG_NAME, "button"):
                if "create account" in btn.text.lower():
                    btn.click(); time.sleep(3); break
        except:
            pass

        notify_q.append("OTP wait kar raha hu email mein...")
        otp = mail_obj.wait_for_otp(120)

        if not otp:
            notify_q.append("Auto OTP nahi aaya. /otp CODE bhejo.")
            deadline = time.time() + 200
            while time.time() < deadline:
                time.sleep(5)
                if state["pending_otp"]:
                    otp = state["pending_otp"]
                    state["pending_otp"] = None
                    break

        if otp:
            notify_q.append(f"OTP: {otp}")
            try:
                inp = driver.find_element(
                    By.CSS_SELECTOR,
                    "input[name='otp'], input[autocomplete='one-time-code']"
                )
                inp.clear()
                inp.send_keys(str(otp))
                inp.send_keys(Keys.RETURN)
                time.sleep(3)
            except:
                pass

        final = driver.current_url
        if "github.com" in final and "signup" not in final:
            notify_q.append(f"GitHub account bana: {username}")
            return True
        else:
            notify_q.append(f"GitHub unclear. URL: {final[:80]}")
            return False

    except Exception as e:
        notify_q.append(f"GitHub error: {str(e)[:150]}")
        return False
    finally:
        try: driver.quit()
        except: pass

async def create_github(email, username, password, bot, mail_obj):
    notify_q = []
    loop     = asyncio.get_event_loop()
    future   = loop.run_in_executor(
        None, lambda: _github_sync(email, username, password, mail_obj, notify_q)
    )
    while not future.done():
        await asyncio.sleep(2)
        while notify_q: await safe_send(bot, notify_q.pop(0))
    while notify_q: await safe_send(bot, notify_q.pop(0))
    return future.result()

# ── RENDER VIA GITHUB OAUTH ───────────────────────────────────────────
def _render_sync(gh_email, gh_pass, notify_q):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys

    proxy  = get_proxy()
    driver = _make_driver(proxy)
    try:
        notify_q.append("Render register open...")
        driver.get("https://dashboard.render.com/register")
        time.sleep(3)

        gh_btn = None
        for el in driver.find_elements(By.TAG_NAME, "a") + driver.find_elements(By.TAG_NAME, "button"):
            if "github" in el.text.lower():
                gh_btn = el; break
        if not gh_btn:
            notify_q.append("Render: GitHub button nahi mila.")
            return None
        gh_btn.click()
        time.sleep(3)

        if "github.com" in driver.current_url:
            notify_q.append("GitHub login kar raha hu...")
            try:
                _wait_element(driver, By.ID, "login").send_keys(gh_email)
                driver.find_element(By.ID, "password").send_keys(gh_pass)
                driver.find_element(By.CSS_SELECTOR, "input[type='submit']").click()
                time.sleep(3)
            except Exception as e:
                notify_q.append(f"GitHub login error: {str(e)[:100]}")

        if "oauth" in driver.current_url or "authorize" in driver.current_url:
            try:
                for btn in driver.find_elements(By.TAG_NAME, "button"):
                    if "authorize" in btn.text.lower():
                        btn.click(); time.sleep(3); break
                for inp in driver.find_elements(By.CSS_SELECTOR, "input[type='submit']"):
                    if "authorize" in (inp.get_attribute("value") or "").lower():
                        inp.click(); time.sleep(3); break
            except:
                pass

        time.sleep(2)
        if "dashboard.render.com" in driver.current_url and "login" not in driver.current_url:
            notify_q.append("Render account bana! API key le raha hu...")
            driver.get("https://dashboard.render.com/account/api-keys")
            time.sleep(2)

            try:
                for btn in driver.find_elements(By.TAG_NAME, "button"):
                    if "create api key" in btn.text.lower() or "new api key" in btn.text.lower():
                        btn.click(); time.sleep(1); break
                inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='text']")
                if inputs:
                    inputs[0].clear()
                    inputs[0].send_keys("bot-key")
                for btn in driver.find_elements(By.TAG_NAME, "button"):
                    if btn.get_attribute("type") == "submit" or "create" in btn.text.lower():
                        btn.click(); time.sleep(2); break
                for sel in ["code", "input[readonly]"]:
                    els = driver.find_elements(By.CSS_SELECTOR, sel)
                    if els:
                        k = els[0].text.strip() or els[0].get_attribute("value") or ""
                        if k and len(k) > 10:
                            return k
            except Exception as e:
                notify_q.append(f"API key extract error: {str(e)[:100]}")

        notify_q.append("Render login fail ya API key nahi mila.")
        return None

    except Exception as e:
        notify_q.append(f"Render error: {str(e)[:150]}")
        return None
    finally:
        try: driver.quit()
        except: pass

async def create_render(gh_email, gh_pass, bot):
    notify_q = []
    loop     = asyncio.get_event_loop()
    future   = loop.run_in_executor(
        None, lambda: _render_sync(gh_email, gh_pass, notify_q)
    )
    while not future.done():
        await asyncio.sleep(2)
        while notify_q: await safe_send(bot, notify_q.pop(0))
    while notify_q: await safe_send(bot, notify_q.pop(0))
    return future.result()

# ── FULL AUTO ─────────────────────────────────────────────────────────
async def full_auto(bot):
    mail     = TempMail()
    username = rand_user()
    password = rand_pass()

    await safe_send(bot, "Temp email bana raha hu...")
    try:
        email = mail.generate()
        state["mail_obj"] = mail
    except Exception as e:
        await safe_send(bot, f"Temp mail fail: {str(e)[:200]}")
        return

    await safe_send(bot,
        f"Email: {email}\nUsername: {username}\nPassword: {password}"
    )

    await safe_send(bot, "--- Step 1: GitHub ---")
    ok = await create_github(email, username, password, bot, mail)
    if not ok:
        await safe_send(bot,
            "GitHub fail.\nCaptcha ya IP issue.\n/auto se dobara try karo."
        )
        return

    await asyncio.sleep(5)

    await safe_send(bot, "--- Step 2: Render ---")
    rkey = await create_render(email, password, bot)
    if not rkey:
        await safe_send(bot,
            f"Render API key nahi mila.\n"
            f"GitHub bana:\nEmail: {email}\nPass: {password}\n"
            f"Manually render.com pe GitHub se signup karo."
        )
        return

    acc = {
        "num":      len(state["accounts"]) + 1,
        "email":    email,
        "username": username,
        "password": password,
        "render_api_key": rkey,
    }
    state["accounts"].append(acc)
    try:
        with open("accounts.json", "w") as f:
            json.dump(state["accounts"], f, indent=2)
    except:
        pass

    await safe_send(bot,
        f"✅ Account #{acc['num']} READY!\n\n"
        f"Email: {email}\n"
        f"GitHub: {username}\n"
        f"Password: {password}\n"
        f"Render API Key: {rkey}"
    )

# ── COMMANDS ──────────────────────────────────────────────────────────
async def cmd_start(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if u.effective_chat.id != CHAT_ID: return
    await u.message.reply_text(
        "Auto Account Bot\n\n"
        "/auto   - full auto (mail→github→render→key)\n"
        "/otp CODE - manual OTP\n"
        "/status - accounts list\n"
        "/proxies - fresh proxies load"
    )

async def cmd_auto(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if u.effective_chat.id != CHAT_ID: return
    if state["running"]:
        await u.message.reply_text("Pehla chal raha hai...")
        return
    state["running"] = True
    await u.message.reply_text("Full auto shuru!")
    bot = ctx.bot
    async def run():
        try:    await full_auto(bot)
        finally: state["running"] = False
    asyncio.create_task(run())

async def cmd_otp(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if u.effective_chat.id != CHAT_ID: return
    if not ctx.args:
        await u.message.reply_text("Usage: /otp CODE")
        return
    state["pending_otp"] = ctx.args[0]
    await u.message.reply_text(f"OTP set: {ctx.args[0]}")

async def cmd_status(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if u.effective_chat.id != CHAT_ID: return
    if not state["accounts"]:
        try:
            with open("accounts.json") as f: state["accounts"] = json.load(f)
        except: pass
    if not state["accounts"]:
        await u.message.reply_text("Koi account nahi. /auto se banao.")
        return
    msg = f"Total accounts: {len(state['accounts'])}\n\n"
    for a in state["accounts"]:
        msg += (
            f"#{a['num']} {a.get('username','?')}\n"
            f"  Email: {a.get('email','?')}\n"
            f"  Key: {a.get('render_api_key','?')[:20]}...\n\n"
        )
    await u.message.reply_text(msg)

async def cmd_proxies(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if u.effective_chat.id != CHAT_ID: return
    await u.message.reply_text("Fetch kar raha hu...")
    count = await asyncio.get_event_loop().run_in_executor(None, fetch_proxies)
    await u.message.reply_text(f"{count} proxies ready!")

# ── MAIN ──────────────────────────────────────────────────────────────
def main():
    print(f"[*] Flask port {PORT}...")
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=fetch_proxies, daemon=True).start()

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("auto",    cmd_auto))
    app.add_handler(CommandHandler("otp",     cmd_otp))
    app.add_handler(CommandHandler("status",  cmd_status))
    app.add_handler(CommandHandler("proxies", cmd_proxies))
    print("[*] Ready!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
