import os
import json
import asyncio
import sqlite3
import smtplib
import logging
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from threading import Thread
from zoneinfo import ZoneInfo

from flask import Flask, request, jsonify, render_template
from flask_socketio import SocketIO, emit
from flask_cors import CORS
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.date import DateTrigger
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet")

COURT_URL = "https://www.calendis.ro/floresti_cj/parcul-sportiv-floresti/teren-de-paddle-1/s"
TZ = ZoneInfo("Europe/Bucharest")

GMAIL_USER = os.environ.get("GMAIL_USER", "")
GMAIL_PASS = os.environ.get("GMAIL_PASS", "")

scheduler = BackgroundScheduler(timezone="Europe/Bucharest")
scheduler.start()

DB_PATH = "sniper.db"


# ─── DB ──────────────────────────────────────────────────────────────────────

def init_db():
    with sqlite3.connect(DB_PATH) as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                email       TEXT NOT NULL,
                password    TEXT NOT NULL,
                target_date TEXT NOT NULL,
                target_hour TEXT NOT NULL,
                notify_email TEXT NOT NULL,
                status      TEXT NOT NULL DEFAULT 'pending',
                message     TEXT,
                created_at  TEXT NOT NULL
            )
        """)
        con.commit()


def db_insert_booking(email, password, target_date, target_hour, notify_email):
    with sqlite3.connect(DB_PATH) as con:
        cur = con.execute(
            "INSERT INTO bookings (email,password,target_date,target_hour,notify_email,status,created_at) VALUES (?,?,?,?,?,?,?)",
            (email, password, target_date, target_hour, notify_email, "pending", datetime.now(TZ).isoformat()),
        )
        con.commit()
        return cur.lastrowid


def db_update_status(booking_id, status, message=""):
    with sqlite3.connect(DB_PATH) as con:
        con.execute(
            "UPDATE bookings SET status=?, message=? WHERE id=?",
            (status, message, booking_id),
        )
        con.commit()


def db_get_all():
    with sqlite3.connect(DB_PATH) as con:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT id,email,target_date,target_hour,notify_email,status,message,created_at FROM bookings ORDER BY id DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def db_delete_booking(booking_id):
    with sqlite3.connect(DB_PATH) as con:
        con.execute("DELETE FROM bookings WHERE id=?", (booking_id,))
        con.commit()


# ─── EMAIL ───────────────────────────────────────────────────────────────────

def send_email(to_addr, subject, body):
    if not GMAIL_USER or not GMAIL_PASS:
        log.warning("Email credentials not set – skipping notification.")
        return
    try:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = GMAIL_USER
        msg["To"] = to_addr
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as srv:
            srv.login(GMAIL_USER, GMAIL_PASS)
            srv.sendmail(GMAIL_USER, [to_addr], msg.as_string())
        log.info("Email sent to %s", to_addr)
    except Exception as e:
        log.error("Email error: %s", e)


# ─── PLAYWRIGHT HELPERS ──────────────────────────────────────────────────────

async def do_login(page, email, password):
    await page.goto("https://www.calendis.ro/login", timeout=30000)
    try:
        await page.click("#cookie-accept", timeout=5000)
    except Exception:
        pass
    await page.click("#login-btn", timeout=10000)
    await page.fill("#forEmail", email)
    await page.fill("#forPassword", password)
    await page.click("button.connect[type='submit']")
    try:
        await page.wait_for_selector("#forEmail", state="hidden", timeout=10000)
        return True, "Login reușit"
    except Exception:
        return False, "Login eșuat – email/parolă greșite?"


async def check_existing_booking(page):
    """Returns True if account already has a booking this week."""
    try:
        await page.goto("https://www.calendis.ro/contul-meu/rezervarile-mele", timeout=20000)
        content = await page.content()
        now = datetime.now(TZ)
        # check for dates in current week (Mon–Sun)
        week_start = now - timedelta(days=now.weekday())
        for i in range(7):
            day = week_start + timedelta(days=i)
            if day.strftime("%d.%m.%Y") in content or day.strftime("%Y-%m-%d") in content:
                return True
        return False
    except Exception:
        return False


async def navigate_to_date(page, target_date: datetime):
    await page.goto(COURT_URL, timeout=30000)
    await page.wait_for_selector(".horizontal-calendar", timeout=15000)

    target_day_str = str(target_date.day)
    target_month = target_date.month

    for _ in range(8):
        header = await page.inner_text(".calendar-header")
        # header like "Iunie 2026" – check month number by parsing
        months_ro = ["", "Ianuarie", "Februarie", "Martie", "Aprilie", "Mai",
                     "Iunie", "Iulie", "August", "Septembrie", "Octombrie",
                     "Noiembrie", "Decembrie"]
        visible_month = 0
        for idx, name in enumerate(months_ro):
            if name.lower() in header.lower():
                visible_month = idx
                break

        if visible_month == target_month:
            day_elements = await page.query_selector_all(".day-nr")
            for el in day_elements:
                text = (await el.inner_text()).strip()
                if text == target_day_str:
                    await el.click()
                    await page.wait_for_timeout(800)
                    return True
        # navigate to next week
        await page.click(".calendar-arrow.right-arrow")
        await page.wait_for_timeout(500)

    return False


async def find_and_click_slot(page, target_hour: str, dry_run: bool = False):
    """
    Waits for slot with target_hour to appear in DOM, then books it.
    target_hour format: "15:00"
    """
    try:
        await page.wait_for_function(
            f"""() => {{
                const slots = document.querySelectorAll('div.slot-item');
                for (const s of slots) {{
                    if (s.innerText.includes('{target_hour}')) return true;
                }}
                return false;
            }}""",
            timeout=30000,
        )
    except Exception:
        return False, f"Slotul {target_hour} nu a apărut în 30 secunde"

    if dry_run:
        return True, "Dry run – slot găsit dar nu s-a rezervat"

    slots = await page.query_selector_all("div.slot-item")
    clicked = False
    for slot in slots:
        text = await slot.inner_text()
        if target_hour in text:
            await slot.click()
            clicked = True
            break

    if not clicked:
        return False, "Slot găsit în DOM dar click eșuat"

    try:
        await page.wait_for_selector("button:has-text('CONFIRMĂ')", timeout=10000)
        await page.click("button:has-text('CONFIRMĂ')")
        await page.wait_for_selector("button:has-text('FINALIZEAZĂ')", timeout=10000)
        await page.click("button:has-text('FINALIZEAZĂ')")
        return True, f"Rezervare confirmată: {target_hour}"
    except Exception as e:
        return False, f"Eroare la confirmare: {e}"


# ─── SNIPER CORE ─────────────────────────────────────────────────────────────

def run_sniper(booking_id: int):
    """Entry point called by APScheduler (sync wrapper for async sniper)."""
    asyncio.run(_sniper_async(booking_id))


async def _sniper_async(booking_id: int):
    from playwright.async_api import async_playwright

    with sqlite3.connect(DB_PATH) as con:
        con.row_factory = sqlite3.Row
        row = con.execute("SELECT * FROM bookings WHERE id=?", (booking_id,)).fetchone()

    if not row:
        log.error("Booking %d not found", booking_id)
        return

    row = dict(row)
    email = row["email"]
    password = row["password"]
    notify = row["notify_email"]
    target_date = datetime.strptime(row["target_date"], "%Y-%m-%d").replace(tzinfo=TZ)
    target_hour = row["target_hour"]  # "15:00"

    # fire_time = target_date at target_hour – 14 days (slot opens exactly then)
    h, m = map(int, target_hour.split(":"))
    fire_time = target_date.replace(hour=h, minute=m, second=0, microsecond=0) - timedelta(days=14)

    def push(msg, status=None):
        log.info("[%d] %s", booking_id, msg)
        socketio.emit("booking_update", {"id": booking_id, "message": msg, "status": status})

    push("Se conectează la Calendis...", "running")
    db_update_status(booking_id, "running", "Se conectează...")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context()
        page = await context.new_page()

        try:
            ok, msg = await do_login(page, email, password)
            if not ok:
                raise RuntimeError(msg)
            push("Login OK. Verifică rezervări existente...")

            has_booking = await check_existing_booking(page)
            if has_booking:
                raise RuntimeError("Contul are deja o rezervare în săptămâna aceasta")

            push("Navighează la teren și ziua țintă...")
            found = await navigate_to_date(page, target_date)
            if not found:
                raise RuntimeError(f"Nu am găsit ziua {target_date.strftime('%d.%m.%Y')} în calendar")

            push(f"Pagina pregătită. Aștept ora {fire_time.strftime('%H:%M:%S')} exactă...")

            # Busy-wait in 100ms increments until fire_time
            while True:
                now = datetime.now(TZ)
                delta = (fire_time - now).total_seconds()
                if delta <= 0:
                    break
                await asyncio.sleep(min(0.1, delta))

            push(f"Ora exactă! Caut slotul {target_hour}...")

            ok, msg = await find_and_click_slot(page, target_hour, dry_run=False)
            if ok:
                push(f"✅ {msg}", "success")
                db_update_status(booking_id, "success", msg)
                send_email(notify, "✅ Rezervare confirmată – Padel Florești",
                           f"Rezervarea a reușit!\n\nData: {target_date.strftime('%d.%m.%Y')}\nOra: {target_hour}\n\nBucurie la joc! 🎾")
            else:
                raise RuntimeError(msg)

        except Exception as e:
            err = str(e)
            push(f"❌ {err}", "failed")
            db_update_status(booking_id, "failed", err)
            send_email(notify, "❌ Rezervare eșuată – Padel Florești",
                       f"Nu am putut rezerva.\n\nData: {target_date.strftime('%d.%m.%Y')}\nOra: {target_hour}\nMotiv: {err}")
        finally:
            await browser.close()


# ─── FLASK ROUTES ─────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/bookings", methods=["GET"])
def list_bookings():
    return jsonify(db_get_all())


@app.route("/api/bookings/<int:booking_id>", methods=["DELETE"])
def delete_booking(booking_id):
    try:
        scheduler.remove_job(f"sniper_{booking_id}")
    except Exception:
        pass
    db_delete_booking(booking_id)
    return jsonify({"ok": True})


@app.route("/api/verify-login", methods=["POST"])
def verify_login():
    data = request.json or {}
    email = data.get("email", "").strip()
    password = data.get("password", "")
    if not email or not password:
        return jsonify({"ok": False, "message": "Email și parolă obligatorii"}), 400

    def _run():
        return asyncio.run(_verify_login_async(email, password))

    result = {"ok": False, "message": ""}

    async def _verify_login_async(e, p):
        from playwright.async_api import async_playwright
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            page = await browser.new_page()
            try:
                ok, msg = await do_login(page, e, p)
                result["ok"] = ok
                result["message"] = msg
            finally:
                await browser.close()

    asyncio.run(_verify_login_async(email, password))
    return jsonify(result)


@app.route("/api/schedule", methods=["POST"])
def schedule_booking():
    data = request.json or {}
    email = data.get("email", "").strip()
    password = data.get("password", "")
    target_date_str = data.get("target_date", "")  # "2026-06-29"
    target_hour = data.get("target_hour", "")       # "15:00"
    notify_email = data.get("notify_email", email).strip()

    if not all([email, password, target_date_str, target_hour]):
        return jsonify({"ok": False, "message": "Toate câmpurile sunt obligatorii"}), 400

    try:
        target_date = datetime.strptime(target_date_str, "%Y-%m-%d").replace(tzinfo=TZ)
    except ValueError:
        return jsonify({"ok": False, "message": "Format dată invalid (YYYY-MM-DD)"}), 400

    h, m = map(int, target_hour.split(":"))
    fire_time = target_date.replace(hour=h, minute=m, second=0, microsecond=0) - timedelta(days=14)
    job_time = fire_time - timedelta(minutes=2)  # start sniper 2 min early

    now = datetime.now(TZ)
    if job_time < now:
        return jsonify({"ok": False, "message": "Data/ora țintă este în trecut"}), 400

    booking_id = db_insert_booking(email, password, target_date_str, target_hour, notify_email)

    scheduler.add_job(
        run_sniper,
        trigger=DateTrigger(run_date=job_time, timezone=TZ),
        args=[booking_id],
        id=f"sniper_{booking_id}",
        replace_existing=True,
    )

    log.info("Scheduled sniper #%d for %s at %s (job fires at %s)",
             booking_id, target_date_str, target_hour, job_time.isoformat())

    return jsonify({
        "ok": True,
        "booking_id": booking_id,
        "fire_time": job_time.strftime("%d.%m.%Y %H:%M"),
        "message": f"Programat! Botul va porni la {job_time.strftime('%d.%m.%Y %H:%M')}",
    })


# ─── MAIN ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    socketio.run(app, host="0.0.0.0", port=port, debug=False)
