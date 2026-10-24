#!/usr/bin/env python3
"""
Auto Account Creator Bot
Temp mail (GuerillaMail) -> GitHub -> Render OAuth -> API key -> Telegram
Flask /health keeps Render alive.
Uses SeleniumBase UC Mode for better bot detection bypass.
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

BOT_TOKEN      = os.environ.get("BOT_TOKEN", "")
CHAT_ID        = int(os.environ.get("CHAT_ID", "0"))
PORT           = int(os.environ.get("PORT", "8080"))
CAPTCHA_KEY    = os.environ.get("CAPTCHA_KEY", "")   # 2captcha API key (optional)

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

# ─── keep-alive: ping /health every 10 min so Render doesn't sleep ───────────
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

# ─── Proxy management ─────────────────────────────────────────────────────────
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
    # Test against GitHub specifically
    for p in state["proxy_list"][:100]:
        try:
            r = requests.get(
                "https://github.com",
                proxies={"http": f"http://{p}", "https": f"http://{p}"},
                timeout=8,
                verify=False,
                allow_redirects=True
            )
            if r.status_code in (200, 301, 302):
                return p
        except:
            pass
    return None

# ─── Helpers ──────────────────────────────────────────────────────────────────
def rand_pass():
    return ''.join(random.choices(string.ascii_letters + string.digits, k=12)) + "!9"

def rand_user():
    a = ["dark","swift","ghost","iron","quick","cyber","brave","steel","night","sonic","alpha","delta"]
    n = ["wolf","fox","hawk","viper","blade","byte","ninja","storm","pixel","core","node","grid"]
    return f"{random.choice(a)}{random.choice(n)}{random.randint(1000,9999)}"

def _human_type(sb, selector, text):
    """Type with human-like random delays using SeleniumBase."""
    try:
        sb.click(selector)
    except:
        pass
    for ch in text:
        sb.execute_script(
            f"arguments[0].value += arguments[1]",
            sb.find_element(selector), ch
        )
        time.sleep(random.uniform(0.05, 0.15))
    # Also use native type to ensure JS events fire
    try:
        sb.type(selector, text)
    except:
        pass

# ─── 2captcha solver (optional) ──────────────────────────────────────────────
def _solve_funcaptcha(site_key, page_url):
    """Submit Arkose/FunCaptcha to 2captcha. Returns token or None."""
    if not CAPTCHA_KEY:
        return None
    try:
        r = requests.post(
            "http://2captcha.com/in.php",
            data={
                "key": CAPTCHA_KEY,
                "method": "funcaptcha",
                "publickey": site_key,
                "pageurl": page_url,
                "json": 1,
            },
            timeout=15,
        )
        req_id = r.json().get("request")
        if not req_id:
            return None
        for _ in range(24):   # wait up to 2 min
            time.sleep(5)
            res = requests.get(
                f"http://2captcha.com/res.php?key={CAPTCHA_KEY}&action=get&id={req_id}&json=1",
                timeout=10,
            ).json()
            if res.get("status") == 1:
                return res["request"]
            if res.get("request") == "ERROR_CAPTCHA_UNSOLVABLE":
                return None
    except:
        pass
    return None

# ─── SeleniumBase driver factory ──────────────────────────────────────────────
def _make_sb_driver(proxy=None):
    """
    Returns a SeleniumBase SB context-managed driver in UC mode.
    Caller must use as context manager or call .tearDown() manually.
    """
    from seleniumbase import Driver

    kwargs = {
        "uc": True,
        "headless": False,   # headless detectable — use Xvfb instead
        "no_sandbox": True,
        "disable_gpu": True,
    }
    if proxy:
        kwargs["proxy"] = proxy

    driver = Driver(**kwargs)

    # navigator.webdriver spoofing via CDP
    try:
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
                Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
                window.chrome = {runtime: {}};
                Object.defineProperty(navigator, 'platform', {get: () => 'Win32'});
            """
        })
    except:
        pass

    return driver

# ─── GitHub signup ────────────────────────────────────────────────────────────
def _github_sync(email, username, password, mail_obj, notify_q):
    proxy = get_proxy()
    if proxy:
        notify_q.append(f"Proxy: {proxy}")
    else:
        notify_q.append("Proxy nahi mila, direct try kar raha hu...")

    driver = _make_sb_driver(proxy)
    try:
        notify_q.append("GitHub signup open...")

        # UC Mode reconnect — avoids initial detection window
        driver.uc_open_with_reconnect("https://github.com/signup", 4)
        time.sleep(random.uniform(2, 3))

        # ── Email ──
        try:
            for sel in ["#email", "input[name='user[email]']", "input[type='email']"]:
                try:
                    driver.type(sel, email)
                    break
                except:
                    continue
            time.sleep(random.uniform(0.5, 1.2))
            driver.send_keys("input:focus", "\n")
            time.sleep(random.uniform(1.5, 2.5))
        except Exception as e:
            notify_q.append(f"Email field error: {str(e)[:80]}")
            return False

        # ── Password ──
        try:
            for sel in ["#password", "input[name='user[password]']", "input[type='password']"]:
                try:
                    driver.type(sel, password)
                    break
                except:
                    continue
            time.sleep(random.uniform(0.5, 1.2))
            driver.send_keys("input:focus", "\n")
            time.sleep(random.uniform(1.5, 2.5))
        except Exception as e:
            notify_q.append(f"Password field error: {str(e)[:80]}")
            return False

        # ── Username ──
        try:
            for sel in ["#login", "input[name='user[login]']", "input[autocomplete='username']"]:
                try:
                    driver.type(sel, username)
                    break
                except:
                    continue
            time.sleep(random.uniform(1.0, 2.0))
            driver.send_keys("input:focus", "\n")
            time.sleep(random.uniform(1.5, 2.5))
        except Exception as e:
            notify_q.append(f"Username field error: {str(e)[:80]}")
            return False

        # ── Email preferences (No) ──
        try:
            driver.find_element("label", by="tag").click()
        except:
            pass
        time.sleep(random.uniform(0.5, 1.0))

        # ── Continue/Submit ──
        try:
            for txt in ["Continue", "Create account", "Sign up"]:
                try:
                    driver.click(f"button:contains('{txt}')")
                    break
                except:
                    continue
        except:
            pass
        time.sleep(random.uniform(2, 3))

        # ── Captcha handling ──
        notify_q.append("Captcha check kar raha hu...")

        # Try 2captcha if key available
        captcha_solved = False
        if CAPTCHA_KEY:
            try:
                # Find Arkose iframe sitekey
                src = driver.get_page_source()
                m = re.search(r'data-pkey="([^"]+)"', src)
                if not m:
                    m = re.search(r'"sitekey"\s*:\s*"([^"]+)"', src)
                if m:
                    site_key = m.group(1)
                    notify_q.append("Captcha solve kar raha hu (2captcha)...")
                    token = _solve_funcaptcha(site_key, "https://github.com/signup")
                    if token:
                        driver.execute_script(
                            f"document.querySelector('input[name=\"fc-token\"]') && "
                            f"(document.querySelector('input[name=\"fc-token\"]').value = '{token}');"
                        )
                        captcha_solved = True
                        notify_q.append("Captcha token inject kiya.")
            except:
                pass

        if not captcha_solved:
            notify_q.append("Manual captcha solve hoga ya skip... 20s wait")
            time.sleep(20)

        # Try final submit again
        try:
            for txt in ["Create account", "Continue", "Submit"]:
                try:
                    driver.click(f"button:contains('{txt}')")
                    time.sleep(2)
                    break
                except:
                    continue
        except:
            pass

        # ── OTP ──
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
                for sel in [
                    "input[name='otp']",
                    "input[autocomplete='one-time-code']",
                    "input[inputmode='numeric']",
                    "input[type='text']",
                ]:
                    try:
                        driver.type(sel, str(otp))
                        driver.send_keys(sel, "\n")
                        break
                    except:
                        continue
                time.sleep(3)
            except:
                pass

        final = driver.get_current_url()
        notify_q.append(f"Final URL: {final[:100]}")

        if "github.com" in final and "signup" not in final and "verify" not in final:
            notify_q.append(f"GitHub account bana: {username}")
            return True
        else:
            notify_q.append("GitHub signup unclear. URL check karo.")
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
    loop     = asyncio.get_event_loop()
    future   = loop.run_in_executor(
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
    proxy  = get_proxy()
    driver = _make_sb_driver(proxy)
    try:
        notify_q.append("Render register open...")
        driver.uc_open_with_reconnect("https://dashboard.render.com/register", 4)
        time.sleep(3)

        # Click GitHub OAuth button
        try:
            for txt in ["GitHub", "Continue with GitHub", "Sign in with GitHub"]:
                try:
                    driver.click(f"a:contains('{txt}')")
                    time.sleep(3)
                    break
                except:
                    try:
                        driver.click(f"button:contains('{txt}')")
                        time.sleep(3)
                        break
                    except:
                        continue
        except:
            notify_q.append("Render: GitHub button nahi mila.")
            return None

        # GitHub OAuth login
        if "github.com" in driver.get_current_url():
            notify_q.append("GitHub login kar raha hu...")
            try:
                driver.type("#login_field", gh_email)
                driver.type("#password", gh_pass)
                driver.click("input[type='submit']")
                time.sleep(3)
            except Exception as e:
                notify_q.append(f"GitHub login error: {str(e)[:100]}")

        # Authorize Render
        cur = driver.get_current_url()
        if "oauth" in cur or "authorize" in cur:
            try:
                driver.click("button:contains('Authorize')")
                time.sleep(3)
            except:
                try:
                    driver.click("input[value*='Authorize']")
                    time.sleep(3)
                except:
                    pass

        time.sleep(2)
        cur = driver.get_current_url()
        if "dashboard.render.com" in cur and "login" not in cur:
            notify_q.append("Render account bana! API key le raha hu...")
            driver.open("https://dashboard.render.com/account/api-keys")
            time.sleep(2)
            try:
                for txt in ["Create API Key", "New API Key", "Add API Key"]:
                    try:
                        driver.click(f"button:contains('{txt}')")
                        time.sleep(1)
                        break
                    except:
                        continue
                try:
                    driver.type("input[type='text']", "bot-key")
                except:
                    pass
                try:
                    driver.click("button[type='submit']")
                    time.sleep(2)
                except:
                    pass
                for sel in ["code", "input[readonly]", ".api-key"]:
                    try:
                        k = driver.get_text(sel).strip()
                        if k and len(k) > 10:
                            return k
                    except:
                        pass
                # Fallback: get_attribute value
                for sel in ["input[readonly]"]:
                    try:
                        el = driver.find_element(sel)
                        k = el.get_attribute("value") or ""
                        if k and len(k) > 10:
                            return k
                    except:
                        pass
            except Exception as e:
                notify_q.append(f"API key extract error: {str(e)[:100]}")

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
    loop     = asyncio.get_event_loop()
    future   = loop.run_in_executor(
        None, lambda: _render_sync(gh_email, gh_pass, notify_q)
    )
    while not future.done():
        await asyncio.sleep(2)
        while notify_q:
            await safe_send(bot, notify_q.pop(0))
    while notify_q:
        await safe_send(bot, notify_q.pop(0))
    return future.result()

# ─── Full auto flow ───────────────────────────────────────────────────────────
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
        "email": email,
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

    await safe_send(
        bot,
        f"✅ Account #{acc['num']} READY!\n\n"
        f"Email: {email}\nGitHub: {username}\nPassword: {password}\n"
        f"Render API Key: {rkey}"
    )

# ─── Telegram commands ────────────────────────────────────────────────────────
async def cmd_start(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if u.effective_chat.id != CHAT_ID:
        return
    await u.message.reply_text(
        "Auto Account Bot\n\n"
        "/auto    - full auto\n"
        "/otp CODE - manual OTP\n"
        "/status  - accounts\n"
        "/proxies - load proxies"
    )

async def cmd_auto(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if u.effective_chat.id != CHAT_ID:
        return
    if state["running"]:
        await u.message.reply_text("Pehla chal raha hai...")
        return
    state["running"] = True
    await u.message.reply_text("Full auto shuru!")
    bot = ctx.bot
    async def run():
        try:
            await full_auto(bot)
        finally:
            state["running"] = False
    asyncio.create_task(run())

async def cmd_otp(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if u.effective_chat.id != CHAT_ID:
        return
    if not ctx.args:
        await u.message.reply_text("Usage: /otp CODE")
        return
    state["pending_otp"] = ctx.args[0]
    await u.message.reply_text(f"OTP set: {ctx.args[0]}")

async def cmd_status(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if u.effective_chat.id != CHAT_ID:
        return
    if not state["accounts"]:
        try:
            with open("accounts.json") as f:
                state["accounts"] = json.load(f)
        except:
            pass
    if not state["accounts"]:
        await u.message.reply_text("Koi account nahi. /auto se banao.")
        return
    msg = f"Total: {len(state['accounts'])}\n\n"
    for a in state["accounts"]:
        msg += f"#{a['num']} {a.get('username','?')}\n  Key: {a.get('render_api_key','?')[:20]}...\n\n"
    await u.message.reply_text(msg)

async def cmd_proxies(u: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if u.effective_chat.id != CHAT_ID:
        return
    await u.message.reply_text("Fetch kar raha hu...")
    count = await asyncio.get_event_loop().run_in_executor(None, fetch_proxies)
    await u.message.reply_text(f"{count} proxies ready!")

# ─── Main ─────────────────────────────────────────────────────────────────────
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
