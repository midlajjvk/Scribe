from flask import Flask, render_template, request, redirect, url_for, flash, session
import sqlite3
from datetime import datetime, timedelta, date
import re
from twilio.rest import Client
from apscheduler.schedulers.background import BackgroundScheduler
import pytz  # Added for timezone handling

app = Flask(__name__)
app.secret_key = "your_secret_key"  # Needed for flash messages and sessions

# -----------------------------
# Twilio credentials
# -----------------------------

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")

twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
# -----------------------------
# Timezone
# -----------------------------
IST = pytz.timezone('Asia/Kolkata')

# -----------------------------
# Database initialization
# -----------------------------
def init_db():
    conn = sqlite3.connect('salon.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            phone TEXT NOT NULL,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            UNIQUE(date, time)
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# -----------------------------
# Auto-clear past bookings
# -----------------------------
def delete_past_bookings():
    conn = sqlite3.connect('salon.db')
    cursor = conn.cursor()
    now = datetime.now(IST)
    today_str = now.strftime("%Y-%m-%d")
    current_time_str = now.strftime("%I:%M %p")
    
    # Delete bookings before today
    cursor.execute("DELETE FROM bookings WHERE date < ?", (today_str,))
    
    # Delete bookings for today that are past current time
    cursor.execute("DELETE FROM bookings WHERE date = ? AND time <= ?", (today_str, current_time_str))
    
    conn.commit()
    conn.close()
    print(f"[{datetime.now()}] Cleared past bookings.")

# Start APScheduler
scheduler = BackgroundScheduler()
scheduler.add_job(func=delete_past_bookings, trigger="interval", minutes=1)
scheduler.start()

# -----------------------------
# Admin credentials
# -----------------------------
ADMIN_USERNAME = "itsme"
ADMIN_PASSWORD = "strongpassword"

# -----------------------------
# Helper: Generate 20-minute slots
# -----------------------------
def generate_slots():
    slots = []
    # Morning slots
    morning_start = datetime.strptime("09:00", "%H:%M")
    morning_end = datetime.strptime("12:30", "%H:%M")
    while morning_start <= morning_end:
        slots.append(morning_start.strftime("%I:%M %p"))
        morning_start += timedelta(minutes=20)
    # Afternoon slots
    afternoon_start = datetime.strptime("14:30", "%H:%M")
    afternoon_end = datetime.strptime("22:00", "%H:%M")
    while afternoon_start <= afternoon_end:
        slots.append(afternoon_start.strftime("%I:%M %p"))
        afternoon_start += timedelta(minutes=20)
    return slots

# -----------------------------
# Routes
# -----------------------------
@app.route('/')
def home():
    conn = sqlite3.connect('salon.db')
    cursor = conn.cursor()
    today = datetime.now(IST).date().isoformat()
    cursor.execute("SELECT name, phone, time FROM bookings WHERE date=? ORDER BY time", (today,))
    booked_slots = cursor.fetchall()
    conn.close()
    return render_template('index.html', booked_slots=booked_slots)

@app.route('/book', methods=['GET', 'POST'])
def book():
    conn = sqlite3.connect('salon.db')
    cursor = conn.cursor()
    now = datetime.now(IST)
    today = now.date()
    selected_date = request.form.get('date', today.isoformat())

    # Prevent past dates
    if selected_date < today.isoformat():
        flash("⛔ You cannot book a past date!", "danger")
        selected_date = today.isoformat()

    # Already booked slots for selected_date
    cursor.execute("SELECT time FROM bookings WHERE date=?", (selected_date,))
    booked = {row[0] for row in cursor.fetchall()}

    # Generate slots and mark past times as booked
    all_slots = generate_slots()
    slots = []
    for s in all_slots:
        slot_datetime = datetime.strptime(f"{selected_date} {s}", "%Y-%m-%d %I:%M %p")
        slot_datetime = IST.localize(slot_datetime)
        slots.append({
            "time": s,
            "booked": s in booked or slot_datetime < now
        })

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        phone = request.form.get('phone', '').strip()
        time_selected = request.form.get('time', '').strip()

        # Validations
        if not re.match(r'^[A-Za-z ]+$', name):
            flash("⛔ Enter a valid name using alphabets only!", "danger")
        elif not re.match(r'^\d{10}$', phone):
            flash("⛔ Enter a valid 10-digit mobile number!", "danger")
        elif not time_selected:
            flash("⛔ Please select a slot!", "danger")
        else:
            slot_datetime = datetime.strptime(f"{selected_date} {time_selected}", "%Y-%m-%d %I:%M %p")
            slot_datetime = IST.localize(slot_datetime)

            if time_selected in booked or slot_datetime < now:
                flash("⛔ Slot is already booked or in the past!", "danger")
            else:
                cursor.execute(
                    "INSERT INTO bookings (name, phone, date, time) VALUES (?, ?, ?, ?)",
                    (name, phone, selected_date, time_selected)
                )
                conn.commit()
                conn.close()

                # Optionally send SMS
                # try:
                #     message = twilio_client.messages.create(
                #         body=f"✅ Hi {name}, your booking is confirmed on {selected_date} at {time_selected}. Thank you!",
                #         from_=TWILIO_PHONE_NUMBER,
                #         to=f"+91{phone}"
                #     )
                #     print("SMS sent successfully, SID:", message.sid)
                # except Exception as e:
                #     print("Failed to send SMS:", e)

                return redirect(url_for('success', name=name, time=time_selected, date=selected_date))

    conn.close()
    min_date = today.isoformat()
    return render_template('book.html', slots=slots, min_date=min_date, selected_date=selected_date)

@app.route('/success')
def success():
    name = request.args.get('name')
    time_selected = request.args.get('time')
    selected_date = request.args.get('date')
    return render_template('success.html', name=name, time=time_selected, date=selected_date)

# -----------------------------
# Admin routes
# -----------------------------
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['is_admin'] = True
            return redirect(url_for('admin_bookings'))
        else:
            flash("❌ Invalid username or password!", "danger")
            return redirect(url_for('admin_login'))
    return render_template('admin_login.html')

@app.route('/admin/bookings')
def admin_bookings():
    if not session.get('is_admin'):
        flash("❌ You must log in as admin to view this page!", "danger")
        return redirect(url_for('admin_login'))

    conn = sqlite3.connect('salon.db')
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, phone, date, time FROM bookings ORDER BY date, time")
    bookings = cursor.fetchall()
    conn.close()
    return render_template('admin_bookings.html', bookings=bookings)

@app.route('/admin/delete/<int:id>', methods=['POST'])
def delete_booking(id):
    if not session.get('is_admin'):
        flash("❌ Unauthorized action!", "danger")
        return redirect(url_for('admin_login'))

    conn = sqlite3.connect('salon.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM bookings WHERE id=?", (id,))
    conn.commit()
    conn.close()

    return redirect(url_for('admin_bookings'))

@app.route('/admin/logout')
def admin_logout():
    session.pop('is_admin', None)
    flash("Logged out successfully!", "success")
    return redirect(url_for('home'))

@app.errorhandler(Exception)
def handle_exception(e):
    import traceback
    print("Error occurred:", e)
    traceback.print_exc()
    return render_template('error.html'), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
