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
import requests
import threading
import urllib3
urllib3.disable_warnings()

from flask import Flask, jsonify
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

BOT_TOKEN   = os.environ.get("BOT_TOKEN", "")
CHAT_ID     = int(os.environ.get("CHAT_ID", "0"))
PORT        = int(os.environ.get("PORT", "8080"))
CAPTCHA_KEY = os.environ.get("CAPTCHA_KEY", "")

state = {
    "accounts":    [],
    "proxy_list":  [],
    "running":     False,
    "pending_otp": None,
    "mail_obj":    None,
}

flask_app = Flask(__name__)

@flask_app.route("/health")
def health():
    return jsonify({"status": "ok", "accounts": len(state["accounts"]), "running": state["running"]})

@flask_app.route("/")
def index():
    return jsonify({"bot": "auto-bot", "status": "running"})

def run_flask():
    flask_app.run(host="0.0.0.0", port=PORT, use_reloader=False)

def _keepalive():
    while True:
        try:
            requests.get(f"http://localhost:{PORT}/health", timeout=5)
        except:
            pass
        time.sleep(600)

async def safe_send(bot, text):
    try:
        await bot.send_message(chat_id=CHAT_ID, text=text)
    except Exception:
        pass

# ─── Temp Mail ────────────────────────────────────────────────────────────────
class TempMail:
    BASE = "https://api.guerrillamail.com/ajax.php"

    def __init__(self):
        self.sid = None
        self.s   = requests.Session()
        self.s.verify = False
        self.s.headers["User-Agent"] = "Mozilla/5.0"

    def generate(self):
        r = self.s.get(self.BASE, params={"f": "get_email_address"}, timeout=15)
        d = r.json()
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

# ─── Proxies ──────────────────────────────────────────────────────────────────
def fetch_proxies():
    urls = [
        "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
        "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
        "https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt",
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
    for p in state["proxy_list"][:100]:
        try:
            r = requests.get(
                "https://github.com",
                proxies={"http": f"http://{p}", "https": f"http://{p}"},
                timeout=8, verify=False, allow_redirects=True
            )
            if r.status_code in (200, 301, 302):
                return p
        except:
            pass
    return None

def rand_pass():
    return ''.join(random.choices(string.ascii_letters + string.digits, k=12)) + "!9"

def rand_user():
    a = ["dark","swift","ghost","iron","quick","cyber","brave","steel","night","sonic"]
    n = ["wolf","fox","hawk","viper","blade","byte","ninja","storm","pixel","core"]
    return f"{random.choice(a)}{random.choice(n)}{random.randint(1000,9999)}"

# ─── Chrome driver via undetected_chromedriver (correct API) ─────────────────
def _make_driver(proxy=None):
    import undetected_chromedriver as uc
    import subprocess, shutil

    # Chromium binary
    binary = (
        shutil.which("chromium") or
        shutil.which("chromium-browser") or
        "/usr/bin/chromium"
    )
    chromedriver = (
        shutil.which("chromedriver") or
        "/usr/bin/chromedriver"
    )

    # Get chromium version
    version = None
    try:
        out = subprocess.check_output(
            [binary, "--version"], stderr=subprocess.DEVNULL
        ).decode()
        m = re.search(r'(\d+)\.\d+\.\d+', out)
        if m:
            version = int(m.group(1))
    except:
        pass

    opts = uc.ChromeOptions()
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-setuid-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-software-rasterizer")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--single-process")
    opts.add_argument("--disable-extensions")
    opts.add_argument("--lang=en-US")
    opts.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

    if binary and os.path.exists(binary):
        opts.binary_location = binary

    if proxy:
        opts.add_argument(f"--proxy-server=http://{proxy}")

    kwargs = {"options": opts, "use_subprocess": True}
    if chromedriver and os.path.exists(chromedriver):
        kwargs["driver_executable_path"] = chromedriver
    if version:
        kwargs["version_main"] = version

    driver = uc.Chrome(**kwargs)

    # Stealth JS inject
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
        "source": """
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3,4,5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-US','en']});
            window.chrome = {runtime: {}};
            Object.defineProperty(navigator, 'platform', {get: () => 'Win32'});
        """
    })
    return driver

def _wait(driver, by, selector, timeout=20):
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    return WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((by, selector))
    )

def _human_type(el, text):
    el.clear()
    for ch in text:
        el.send_keys(ch)
        time.sleep(random.uniform(0.04, 0.15))

# ─── GitHub signup ────────────────────────────────────────────────────────────
def _github_sync(email, username, password, mail_obj, notify_q):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys

    proxy = get_proxy()
    notify_q.append(f"Proxy: {proxy}" if proxy else "Direct connect (no proxy)...")

    driver = _make_driver(proxy)
    try:
        notify_q.append("GitHub signup open...")
        driver.get("https://github.com/signup")
        time.sleep(random.uniform(3, 5))

        # ── Email ──
        email_filled = False
        for sel in ["#email", "input[name='user[email]']", "input[type='email']", "input[autocomplete='email']"]:
            try:
                el = driver.find_element(By.CSS_SELECTOR, sel)
                _human_type(el, email)
                el.send_keys(Keys.RETURN)
                email_filled = True
                break
            except:
                continue
        if not email_filled:
            notify_q.append("Email field nahi mila. URL: " + driver.current_url[:80])
            return False
        time.sleep(random.uniform(1.5, 2.5))

        # ── Password ──
        pass_filled = False
        for sel in ["#password", "input[name='user[password]']", "input[type='password']"]:
            try:
                el = driver.find_element(By.CSS_SELECTOR, sel)
                _human_type(el, password)
                el.send_keys(Keys.RETURN)
                pass_filled = True
                break
            except:
                continue
        if not pass_filled:
            notify_q.append("Password field nahi mila.")
            return False
        time.sleep(random.uniform(1.5, 2.5))

        # ── Username ──
        user_filled = False
        for sel in ["#login", "input[name='user[login]']", "input[autocomplete='username']"]:
            try:
                el = driver.find_element(By.CSS_SELECTOR, sel)
                _human_type(el, username)
                el.send_keys(Keys.RETURN)
                user_filled = True
                break
            except:
                continue
        if not user_filled:
            notify_q.append("Username field nahi mila.")
            return False
        time.sleep(random.uniform(1.5, 2.5))

        # ── Email prefs (No) ──
        try:
            for lbl in driver.find_elements(By.TAG_NAME, "label"):
                if lbl.text.strip().lower().startswith("n"):
                    lbl.click()
                    break
        except:
            pass
        time.sleep(0.5)

        # ── Submit ──
        submitted = False
        for txt in ["Continue", "Create account", "Sign up", "Submit"]:
            try:
                btns = driver.find_elements(By.TAG_NAME, "button")
                for btn in btns:
                    if txt.lower() in btn.text.lower():
                        btn.click()
                        submitted = True
                        break
                if submitted:
                    break
            except:
                continue
        time.sleep(random.uniform(2, 4))

        # ── Captcha ──
        notify_q.append("Captcha wait 20s...")
        time.sleep(20)

        # Retry submit post-captcha
        try:
            for btn in driver.find_elements(By.TAG_NAME, "button"):
                if any(x in btn.text.lower() for x in ["create account", "continue", "submit"]):
                    btn.click()
                    time.sleep(3)
                    break
        except:
            pass

        # ── OTP ──
        notify_q.append("OTP wait kar raha hu...")
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
            for sel in [
                "input[name='otp']",
                "input[autocomplete='one-time-code']",
                "input[inputmode='numeric']",
                "input[type='text']",
            ]:
                try:
                    el = driver.find_element(By.CSS_SELECTOR, sel)
                    _human_type(el, str(otp))
                    el.send_keys(Keys.RETURN)
                    time.sleep(3)
                    break
                except:
                    continue

        final = driver.current_url
        notify_q.append(f"Final URL: {final[:100]}")
        if "github.com" in final and "signup" not in final and "verify" not in final:
            notify_q.append(f"GitHub OK: {username}")
            return True
        else:
            notify_q.append("GitHub signup unclear.")
            return False

    except Exception as e:
        notify_q.append(f"GitHub error: {str(e)[:200]}")
        return False
    finally:
        try:
            driver.quit()
        except:
            pass

async def create_github(email, username, password, bot, mail_obj):
    notify_q = []
    loop = asyncio.get_event_loop()
    future = loop.run_in_executor(
        None, lambda: _github_sync(email, username, password, mail_obj, notify_q)
    )
    while not future.done():
        await asyncio.sleep(2)
        while notify_q:
            await safe_send(bot, notify_q.pop(0))
    while notify_q:
        await safe_send(bot, notify_q.pop(0))
    return future.result()

# ─── Render signup ────────────────────────────────────────────────────────────
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
                gh_btn = el
                break
        if not gh_btn:
            notify_q.append("Render: GitHub button nahi mila.")
            return None
        gh_btn.click()
        time.sleep(3)

        if "github.com" in driver.current_url:
            notify_q.append("GitHub login kar raha hu...")
            try:
                driver.find_element(By.ID, "login_field").send_keys(gh_email)
                driver.find_element(By.ID, "password").send_keys(gh_pass)
                driver.find_element(By.CSS_SELECTOR, "input[type='submit']").click()
                time.sleep(3)
            except Exception as e:
                notify_q.append(f"GitHub login error: {str(e)[:100]}")

        cur = driver.current_url
        if "oauth" in cur or "authorize" in cur:
            try:
                for btn in driver.find_elements(By.TAG_NAME, "button"):
                    if "authorize" in btn.text.lower():
                        btn.click()
                        time.sleep(3)
                        break
                for inp in driver.find_elements(By.CSS_SELECTOR, "input[type='submit']"):
                    if "authorize" in (inp.get_attribute("value") or "").lower():
                        inp.click()
                        time.sleep(3)
                        break
            except:
                pass

        time.sleep(2)
        if "dashboard.render.com" in driver.current_url and "login" not in driver.current_url:
            notify_q.append("Render account bana! API key le raha hu...")
            driver.get("https://dashboard.render.com/account/api-keys")
            time.sleep(2)
            try:
                for btn in driver.find_elements(By.TAG_NAME, "button"):
                    if any(x in btn.text.lower() for x in ["create api key", "new api key", "add api key"]):
                        btn.click()
                        time.sleep(1)
                        break
                inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='text']")
                if inputs:
                    inputs[0].clear()
                    inputs[0].send_keys("bot-key")
                for btn in driver.find_elements(By.TAG_NAME, "button"):
                    if btn.get_attribute("type") == "submit" or "create" in btn.text.lower():
                        btn.click()
                        time.sleep(2)
                        break
                for sel in ["code", "input[readonly]", ".api-key"]:
                    els = driver.find_elements(By.CSS_SELECTOR, sel)
                    if els:
                        k = els[0].text.strip() or els[0].get_attribute("value") or ""
                        if k and len(k) > 10:
                            return k
            except Exception as e:
                notify_q.append(f"API key error: {str(e)[:100]}")

        notify_q.append("Render login fail ya API key nahi mila.")
        return None

    except Exception as e:
        notify_q.append(f"Render error: {str(e)[:150]}")
        return None
    finally:
        try:
            driver.quit()
        except:
            pass

async def create_render(gh_email, gh_pass, bot):
    notify_q = []
    loop = asyncio.get_event_loop()
    future = loop.run_in_executor(
        None, lambda: _render_sync(gh_email, gh_pass, notify_q)
    )
    while not future.done():
        await asyncio.sleep(2)
        while notify_q:
            await safe_send(bot, notify_q.pop(0))
    while notify_q:
        await safe_send(bot, notify_q.pop(0))
    return future.result()

# ─── Full auto ────────────────────────────────────────────────────────────────
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

    await safe_send(bot, f"Email: {email}\nUsername: {username}\nPassword: {password}")
    await safe_send(bot, "--- Step 1: GitHub ---")
    ok = await create_github(email, username, password, bot, mail)
    if not ok:
        await safe_send(bot, "GitHub fail.\nCaptcha ya IP issue.\n/auto se dobara try karo.")
        return

    await asyncio.sleep(5)
    await safe_send(bot, "--- Step 2: Render ---")
    rkey = await create_render(email, password, bot)
    if not rkey:
        await safe_send(bot, f"Render API key nahi mila.\nEmail: {email}\nPass: {password}")
        return

    acc = {
        "num": len(state["accounts"]) + 1,
        "email": email, "username": username,
        "password": password, "render_api_key": rkey,
    }
    state["accounts"].append(acc)
    try:
        with open("accounts.json", "w") as f:
            json.dump(state["accounts"], f, indent=2)
    except:
        pass

    await safe_send(
        bot,
        f"✅ Account #{acc['num']} READY!\n\n"
        f"Email: {email}\nGitHub: {username}\n"
        f"Password: {password}\nRender API Key: {rkey}"
    )

# ─── Telegram handlers ────────────────────────────────────────────────────────
async def cmd_start(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if u.effective_chat.id != CHAT_ID: return
    await u.message.reply_text("Auto Account Bot\n\n/auto\n/otp CODE\n/status\n/proxies")

async def cmd_auto(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if u.effective_chat.id != CHAT_ID: return
    if state["running"]:
        await u.message.reply_text("Pehla chal raha hai..."); return
    state["running"] = True
    await u.message.reply_text("Full auto shuru!")
    bot = ctx.bot
    async def run():
        try: await full_auto(bot)
        finally: state["running"] = False
    asyncio.create_task(run())

async def cmd_otp(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if u.effective_chat.id != CHAT_ID: return
    if not ctx.args:
        await u.message.reply_text("Usage: /otp CODE"); return
    state["pending_otp"] = ctx.args[0]
    await u.message.reply_text(f"OTP set: {ctx.args[0]}")

async def cmd_status(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if u.effective_chat.id != CHAT_ID: return
    if not state["accounts"]:
        try:
            with open("accounts.json") as f: state["accounts"] = json.load(f)
        except: pass
    if not state["accounts"]:
        await u.message.reply_text("Koi account nahi."); return
    msg = f"Total: {len(state['accounts'])}\n\n"
    for a in state["accounts"]:
        msg += f"#{a['num']} {a.get('username','?')}\n  Key: {a.get('render_api_key','?')[:20]}...\n\n"
    await u.message.reply_text(msg)

async def cmd_proxies(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if u.effective_chat.id != CHAT_ID: return
    await u.message.reply_text("Fetch kar raha hu...")
    count = await asyncio.get_event_loop().run_in_executor(None, fetch_proxies)
    await u.message.reply_text(f"{count} proxies ready!")

def main():
    print(f"[*] Flask port {PORT}...")
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=_keepalive, daemon=True).start()
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
