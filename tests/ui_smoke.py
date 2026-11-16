"""Real-browser smoke test of the web app.

    pip install playwright && playwright install chromium
    python tests/ui_smoke.py

It starts its own server (temporary database, free port), drives Chromium through the main user stories and prints one line
per step. Exit code 1 if anything failed or the browser reported a JavaScript error.
"""
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
failed, js_errors = [], []


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def start_server(port, data_dir):
    env = {**os.environ, "PORT": str(port), "WALLET_DATA_DIR": data_dir, "DEMO_MODE": "true", "USE_REDIS": "false", "PASSWORD_ITERATIONS": "1000"}
    proc = subprocess.Popen([sys.executable, "run.py"], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1)
            return proc
        except Exception:
            time.sleep(0.5)
    proc.kill()
    raise SystemExit("server did not start")


def step(name):
    class Ctx:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            if exc:
                failed.append(name)
                print(f"  FAIL {name}\n       {str(exc).splitlines()[0][:220]}")
            else:
                print(f"  ok   {name}")
            return True
    return Ctx()


def keys(page, text):
    for ch in text:
        page.click(f'[data-k="{ch}"]')


def pay_flow(page, base, to, amount, note="", expect_state="ok"):
    page.goto(f"{base}#/pay/{to.replace('@', '%40')}")
    expect(page.locator(".amt-display")).to_be_visible()
    keys(page, amount)
    if note:
        page.fill("#note", note)
    expect(page.locator("#hint")).not_to_have_text("Checking…", timeout=8000)
    page.click("#go")
    expect(page.locator(f".shield[data-state='{expect_state}']")).to_be_visible(timeout=10000)


def run(base):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.on("pageerror", lambda e: js_errors.append(str(e)))
        page.on("console", lambda m: js_errors.append(m.text) if m.type == "error" and "Failed to load resource" not in m.text else None)

        with step("sign-in screen, demo login, wallet card"):
            page.goto(base)
            expect(page.locator(".auth-frame")).to_be_visible()
            page.click("[data-demo^='aarav']")
            expect(page.locator(".wcard")).to_be_visible(timeout=15000)
            expect(page.locator(".tabbar .tab")).to_have_count(5)
            expect(page.locator("#bal")).to_contain_text("₹")

        with step("hide balance + dark theme from Profile"):
            page.goto(base + "#/profile")
            page.click("#hide")
            page.click("[data-pref=dark]")
            assert page.evaluate("document.documentElement.dataset.theme") == "dark"
            page.click("[data-pref=light]")
            page.goto(base + "#/home")
            expect(page.locator("#bal")).to_contain_text("••••")
            page.click("#eye")
            expect(page.locator("#bal")).not_to_contain_text("••••")

        with step("add money with the keypad (₹20,000)"):
            page.goto(base + "#/add")
            keys(page, "20000")
            page.click("#go")
            expect(page.locator(".shield, .sheet h2")).to_be_visible()
            page.click("#rv-pay")
            expect(page.locator(".done h1")).to_contain_text("₹20,000.00", timeout=10000)

        with step("AI shield holds a risky payment to a brand-new account, admin approves it"):
            page.evaluate("""async () => { await fetch('/api/auth/register', {method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({full_name: 'Zara Test', email: 'zara@t.test', password: 'Passw0rd1'})}); }""")
            pay_flow(page, base, "zara@swallet", "13000", "urgent", expect_state="bad")
            expect(page.locator("#rv-pay")).to_have_text("Send for review")
            page.click("#rv-pay")
            expect(page.locator(".done h1")).to_have_text("Held for review", timeout=10000)

        with step("instant payment: shield cleared, success, live trace in the side panel"):
            pay_flow(page, base, "rohan@swallet", "250", "dinner split")
            expect(page.locator("#rv-checks li[data-s='ok']")).to_have_count(6, timeout=8000)
            page.click("#rv-pay")
            expect(page.locator(".done h1")).to_have_text("₹250.00", timeout=10000)
            expect(page.locator(".hood-steps li").first).to_be_visible()
            expect(page.locator(".hood-steps .lay-OS").first).to_be_visible()
            expect(page.locator(".hood-steps .lay-DBMS").first).to_be_visible()

        with step("receipt: timeline, AI card, category change teaches the AI"):
            page.click("#done-rcpt")
            expect(page.locator(".hero-txn")).to_be_visible()
            expect(page.locator(".vt li")).to_have_count(3)
            page.click("#cat")
            page.click("[data-cat='Friends & Family']")
            expect(page.locator("#toasts")).to_contain_text("remember")

        with step("OTP payment: wrong code shakes, right code pays"):
            pay_flow(page, base, "priya@swallet", "6000", "hostel fees", expect_state="warn")
            page.click("#rv-pay")
            expect(page.locator(".otp-boxes")).to_be_visible()
            otp = page.locator(".demo-note b").inner_text().strip()
            wrong = "000000" if otp != "000000" else "111111"
            for i, ch in enumerate(wrong):
                page.locator(".otp-boxes input").nth(i).fill(ch)
            expect(page.locator("#otp-err")).to_contain_text("Wrong OTP", timeout=8000)
            for i, ch in enumerate(otp):
                page.locator(".otp-boxes input").nth(i).fill(ch)
            expect(page.locator(".done h1")).to_have_text("₹6,000.00", timeout=10000)

        with step("activity: grouped list, filter chips, search"):
            page.goto(base + "#/activity")
            expect(page.locator(".day").first).to_be_visible()
            page.click("[data-f=held]")
            expect(page.locator(".list .row")).to_have_count(1)
            page.click("[data-f=all]")
            page.fill("#q", "swiggy")
            expect(page.locator(".list .row").first).to_contain_text("Swiggy")

        with step("insights: stories, category bars, chart"):
            page.goto(base + "#/insights")
            expect(page.locator(".story").first).to_be_visible()
            assert page.locator(".story").count() >= 4
            expect(page.locator(".cat-row").first).to_be_visible()
            expect(page.locator("svg.chart")).to_be_visible()

        with step("Ask AI in Hinglish, then 'Review this payment' opens a pre-filled Pay screen"):
            page.goto(base + "#/ask")
            page.fill("#msg", "mera balance kitna hai")
            page.press("#msg", "Enter")
            expect(page.locator(".msg.ai").nth(1)).to_contain_text("₹", timeout=8000)
            page.fill("#msg", "Rohan ko 500 bhejo")
            page.press("#msg", "Enter")
            page.click("[data-prefill]")
            expect(page.locator(".amt-display")).to_contain_text("500", timeout=8000)

        with step("Receive sheet shows a QR code"):
            page.goto(base + "#/home")
            page.click("[data-act=receive]")
            expect(page.locator(".qr-box svg")).to_be_visible()
            page.keyboard.press("Escape")

        with step("scheduled payment can be created"):
            page.goto(base + "#/scheduled")
            page.click("#new")
            page.fill("#s-to", "neha@swallet")
            page.fill("#s-amt", "120")
            page.fill("#s-note", "mess fees")
            page.click("#sf button[type=submit]")
            expect(page.locator("#list")).to_contain_text("Neha", timeout=8000)

        with step("lab console: deadlock demo and CPU scheduling"):
            page.goto(base + "#/lab/deadlock")
            page.click("[data-mode=naive]")
            expect(page.locator("#dl")).to_contain_text("Deadlock detected", timeout=20000)
            page.goto(base + "#/lab/cpu")
            page.click("#run")
            expect(page.locator("svg.gantt")).to_be_visible()

        with step("admin approves the held payment"):
            page.goto(base + "#/profile")
            page.click("#signout")
            expect(page.locator(".auth-frame")).to_be_visible()
            page.click("[data-demo^='admin']")
            expect(page.locator(".wcard")).to_be_visible(timeout=15000)
            page.goto(base + "#/admin")
            expect(page.locator("[data-act=approve]")).to_have_count(1, timeout=10000)
            page.once("dialog", lambda d: d.accept())
            page.click("[data-act=approve]")
            expect(page.locator("#adm")).to_contain_text("approved", timeout=10000)
            page.click("#recon")
            expect(page.locator("#adm-out")).to_contain_text("Books balance", timeout=10000)
        ctx.close()

        mobile = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
        m = mobile.new_page()
        m.on("pageerror", lambda e: js_errors.append(str(e)))
        with step("phone layout: full-screen app, no horizontal scroll, Under the hood opens as a sheet"):
            m.goto(base)
            m.click("[data-demo^='aarav']")
            expect(m.locator(".wcard")).to_be_visible(timeout=15000)
            assert m.evaluate("document.documentElement.scrollWidth") <= 391
            m.click("[data-act=hood]")
            expect(m.locator(".sheet .hood")).to_be_visible()
        browser.close()


if __name__ == "__main__":
    tmp = tempfile.mkdtemp()
    port = free_port()
    server = start_server(port, tmp)
    try:
        run(f"http://127.0.0.1:{port}/")
    finally:
        server.kill()
    if js_errors:
        print("\nbrowser JavaScript errors:\n - " + "\n - ".join(sorted(set(js_errors))))
    print(f"\n{len(failed)} step(s) failed" if failed else "\nall UI steps passed")
    sys.exit(1 if failed or js_errors else 0)
