# safety_tracker.py
import os
import logging
from datetime import datetime, timedelta, date
from functools import wraps

from flask import (
    Flask, render_template_string, request, redirect,
    url_for, flash, session
)
from flask_sqlalchemy import SQLAlchemy
from jinja2 import DictLoader
from sqlalchemy import inspect, text  # for simple auto-migrations

# ── App / Config ──────────────────────────────────────────────────────
app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "safety-secret")

# Prefer DATABASE_URL (e.g., Render Postgres). Fall back to local SQLite.
database_url = os.getenv("DATABASE_URL", "sqlite:///safety_v2.db")
# Some providers give postgres://; SQLAlchemy expects postgresql://
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = database_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

NEAR_EXPIRY_DAYS = int(os.getenv("NEAR_EXPIRY_DAYS", 30))
ADMIN_PIN = os.getenv("ADMIN_PIN", "1234")  # change in production

# ── Models ────────────────────────────────────────────────────────────
class Employee(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_code = db.Column(db.String(50), nullable=False, unique=True)
    name = db.Column(db.String(120), nullable=False)

    equipments = db.relationship("Equipment", backref="employee", lazy=True)
    issues = db.relationship("Issue", backref="employee_raiser", lazy=True)

class Equipment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    expiry_date = db.Column(db.Date, nullable=False)
    employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)

    # NEW: retirement state (hide from equipment pages when retired)
    is_retired = db.Column(db.Boolean, default=False, nullable=False)
    retired_on = db.Column(db.DateTime, nullable=True)

    issues = db.relationship("Issue", backref="equipment", lazy=True)

class Issue(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    equipment_id = db.Column(db.Integer, db.ForeignKey("equipment.id"), nullable=False)
    description = db.Column(db.String(300), nullable=False)
    raised_on = db.Column(db.DateTime, default=datetime.utcnow)
    raised_by_employee_id = db.Column(db.Integer, db.ForeignKey("employee.id"), nullable=True)

    # resolution state
    is_resolved = db.Column(db.Boolean, default=False, nullable=False)
    resolved_on = db.Column(db.DateTime, nullable=True)

# ── Templating / CSS ─────────────────────────────────────────────────
BASE_HTML = """
<!doctype html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="utf-8">
  <title>Safety Equipment Tracker</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <link rel="icon" href="{{ url_for('static', filename='iocl.png') }}" />
  <meta name="color-scheme" content="dark light" />

  <style>
    :root {
      --radius: 14px; --shadow-1: 0 10px 30px rgba(0, 0, 0, 0.35); --shadow-2: 0 18px 60px rgba(20, 33, 61, 0.45);
      --focus: 0 0 0 3px rgba(91,140,255,0.35);
      --trans-fast: .12s ease; --trans-med: .18s ease;
    }
    /* Dark theme (default) */
    [data-theme="dark"] {
      --bg: #0b1220; --panel: #121a33; --text: #e8ecf3; --muted: #9aa8bf; --border: #223056;
      --primary: #5b8cff; --primary-2: #7aa5ff; --green: #3ddc97; --green-2: #2cc386; --red: #ff6b6b; --amber: #ffc857;
      --chip-bg: rgba(255,255,255,0.06); --chip-border: rgba(255,255,255,0.12);
      --grad-1: radial-gradient(1200px 600px at 20% -10%, rgba(91,140,255,0.25), transparent 60%),
                 radial-gradient(1000px 500px at 110% -20%, rgba(61,220,151,0.18), transparent 55%),
                 linear-gradient(180deg, #0a1120 0%, #0b1220 100%);
      --table-stripe: rgba(255,255,255,0.025);
      --surface-raise: 0 10px 40px rgba(14,21,43,0.6);
      --link: #a8c1ff;
    }
    /* Light theme */
    [data-theme="light"] {
      --bg: #f6f8fb; --panel: #ffffff; --text: #0f172a; --muted: #5b6577; --border: #e5e9f2;
      --primary: #315efb; --primary-2: #466dff; --green: #0bb07b; --green-2: #069a6b; --red: #e11d48; --amber: #f59e0b;
      --chip-bg: rgba(0,0,0,0.04); --chip-border: rgba(0,0,0,0.08);
      --grad-1: linear-gradient(180deg, #f1f5ff 0%, #f6f8fb 100%);
      --table-stripe: rgba(0,0,0,0.02);
      --surface-raise: 0 10px 40px rgba(2,6,23,0.06);
      --link: #2748ff;
    }

    * { box-sizing: border-box; }
    html, body { height: 100%; }
    body {
      margin: 0; font-family: 'Inter', system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
      color: var(--text); background: var(--grad-1); background-attachment: fixed; line-height: 1.55;
    }

    a { color: var(--link); text-decoration: none; }
    a:hover { text-decoration: underline; }

    header {
      position: sticky; top: 0; z-index: 50; backdrop-filter: saturate(140%) blur(10px);
      background: linear-gradient(180deg, rgba(15,22,44,0.85), rgba(15,22,44,0.55)); border-bottom: 1px solid var(--border);
    }
    .container { max-width: 1180px; margin: 0 auto; padding: 16px 20px; }

    .topbar { display:flex; align-items:center; gap:16px; }
    .logo-img { height: 42px; width: 42px; border-radius: 9px; background:#fff; padding: 3px; box-shadow: 0 6px 18px rgba(0,0,0,0.25); }
    .brand { display:flex; flex-direction:column; }
    .brand-title { margin:0; font-weight:800; letter-spacing:0.2px; font-size:19px; }
    .brand-sub { margin:0; color: var(--muted); font-size:12px; }

    nav { margin-left:auto; display:flex; gap:10px; flex-wrap:wrap; align-items:center; }
    .nav-link, .nav-badge { text-decoration:none; color: var(--text); font-weight:600; padding:9px 12px; border-radius: 12px; border:1px solid transparent; transition: all var(--trans-med); }
    .nav-link:hover { background: var(--chip-bg); border-color: var(--chip-border); transform: translateY(-1px); }
    .nav-badge { background: var(--chip-bg); border-color: var(--chip-border); font-weight:700; letter-spacing:.2px; }

    .theme-toggle { border:1px solid var(--chip-border); background: var(--chip-bg); padding:8px 12px; border-radius: 12px; cursor:pointer; font-weight:700; transition: all var(--trans-fast); }
    .theme-toggle:hover { transform: translateY(-1px); }

    main { padding: 26px 20px 40px; }
    .panel { background: linear-gradient(180deg, color-mix(in oklab, var(--panel) 94%, transparent), color-mix(in oklab, var(--panel) 88%, transparent)); border: 1px solid var(--border); border-radius: var(--radius); box-shadow: var(--surface-raise); padding: 18px; }

    h2 { margin: 0 0 12px; font-weight:800; letter-spacing: .2px; }
    h2 .hint { font-size: 13px; font-weight:600; color: var(--muted); margin-left:8px; }
    .subtle { color: var(--muted); margin-top: 6px; }

    .row { display:grid; grid-template-columns: repeat(4, minmax(230px, 1fr)); gap:14px; }
    @media (max-width: 1080px) { .row { grid-template-columns: repeat(2, minmax(230px, 1fr)); } }
    @media (max-width: 560px) { .row { grid-template-columns: 1fr; } }

    .card { background: linear-gradient(180deg, color-mix(in oklab, var(--panel) 70%, transparent), color-mix(in oklab, var(--panel) 40%, transparent)); border: 1px solid var(--border); border-radius: var(--radius); padding: 16px 16px 14px; box-shadow: var(--shadow-1); min-width: 200px; position: relative; overflow: hidden; isolation:isolate; }
    .card::after { content:""; position:absolute; inset:-1px; background: radial-gradient(250px 80px at 0 -20%, color-mix(in srgb, var(--primary) 35%, transparent), transparent 70%); pointer-events:none; opacity:.7; }
    .card h3 { margin:0 0 10px; font-size:12px; color: var(--muted); font-weight:800; text-transform: uppercase; letter-spacing:.8px; }
    .card .big { font-size:34px; font-weight:800; }
    .card .accent { color: var(--primary-2); }

    .btn { padding:10px 12px; border-radius: 12px; border:1px solid transparent; cursor:pointer; font-weight:700; text-decoration:none; display:inline-flex; align-items:center; gap:8px; transition: transform var(--trans-fast), filter var(--trans-fast), box-shadow var(--trans-fast); }
    .btn:focus { outline: none; box-shadow: var(--focus); }
    .btn-primary { background: linear-gradient(180deg, var(--primary), color-mix(in srgb, var(--primary) 85%, #2248ff)); color:#fff; }
    .btn-primary:hover { transform: translateY(-1px); filter: brightness(1.05); }
    .btn-green { background: linear-gradient(180deg, var(--green), var(--green-2)); color:#0a1220; }
    .btn-green:hover { transform: translateY(-1px); }
    .btn-danger { background: linear-gradient(180deg, var(--red), color-mix(in srgb, var(--red) 88%, #ff2b2b)); color:#fff; }
    .btn-danger:hover { transform: translateY(-1px); }
    .btn-link { color: var(--primary-2); background: transparent; border: none; padding:0; cursor:pointer; }
    .actions { white-space:nowrap; display:flex; gap:8px; }

    form input[type=text], form input[type=date], form select, form input[type=password] {
      padding:12px 12px; margin:6px 0 10px; border:1px solid var(--border); border-radius: 12px; width:360px; max-width:100%; background: color-mix(in oklab, var(--panel) 30%, transparent); color: var(--text); outline:none; transition: box-shadow var(--trans-med), border-color var(--trans-med), background var(--trans-med);
    }
    form input[type=text]:focus, form input[type=date]:focus, form select:focus, form input[type=password]:focus { border-color: var(--primary-2); box-shadow: var(--focus); background: color-mix(in oklab, var(--panel) 45%, transparent); }
    form input[type=submit] { margin-top:6px; }

    .toolbar { display:flex; gap:8px; align-items:center; margin: 4px 0 10px; }
    .toolbar .search { flex:1; }
    .toolbar input[type=search] { width:100%; padding:10px 12px; border:1px solid var(--border); border-radius:12px; background: color-mix(in oklab, var(--panel) 30%, transparent); color: var(--text); }

    .table-wrap { overflow-x:auto; border-radius: var(--radius); border:1px solid var(--border); }
    table { width:100%; border-collapse: separate; border-spacing: 0; background: color-mix(in oklab, var(--panel) 20%, transparent); }
    thead th { position:sticky; top:0; z-index:1; background: linear-gradient(180deg, color-mix(in oklab, var(--primary) 12%, transparent), color-mix(in oklab, var(--primary) 6%, transparent)); color: var(--text); text-align:left; padding:12px; font-size:13px; letter-spacing:.3px; border-bottom:1px solid var(--border); }
    tbody td { padding:12px; border-bottom:1px solid var(--border); }
    tbody tr:nth-child(odd) td { background: var(--table-stripe); }
    tbody tr:hover td { background: color-mix(in oklab, var(--primary) 6%, transparent); }

    .chip { display:inline-flex; align-items:center; gap:6px; padding:6px 10px; border-radius: 999px; background: var(--chip-bg); border:1px solid var(--chip-border); font-weight:700; font-size:12px; }
    .chip.ok { color:#a7f3d0; border-color: rgba(61,220,151,0.35); }
    .chip.warn { color:#ffe6b0; border-color: rgba(255,200,87,0.35); }

    .flash { background: color-mix(in oklab, var(--amber) 12%, transparent); border:1px solid color-mix(in oklab, var(--amber) 35%, transparent); color: #ffe6b0; padding: 10px 12px; border-radius: 12px; margin: 12px 0; }

    .muted { color: var(--muted); font-size: 0.95em; }
    .spacer { height: 6px; }

    footer { color: var(--muted); font-size: 12px; text-align:center; padding: 24px 0 36px; }

    /* Print-friendly */
    @media print {
      header, nav, .flash, .btn, .actions, .theme-toggle, .toolbar { display:none !important; }
      body { background: #fff; color: #111827; }
      .panel { box-shadow:none; border-color:#ddd; }
    }
  </style>
</head>
<body>
  <header>
    <div class="container topbar">
      <img src="{{ url_for('static', filename='iocl.png') }}" alt="Logo" class="logo-img">
      <div class="brand">
        <h1 class="brand-title">Safety Equipment Tracker</h1>
        <p class="brand-sub">Track PPE expiry, assignments & issues with ease</p>
      </div>
      <nav>
        {% if session.get('is_admin') %}
          <a class="nav-link" href="{{ url_for('admin_dashboard') }}">Dashboard</a>
          <a class="nav-link" href="{{ url_for('list_employees') }}">Employees</a>
          <a class="nav-link" href="{{ url_for('list_equipment') }}">Equipment</a>
          <a class="nav-link" href="{{ url_for('list_issues') }}">Issues</a>
          <span class="nav-badge">👑 Admin</span>
          <a class="nav-link" href="{{ url_for('logout') }}">Logout</a>
        {% elif session.get('employee_id') %}
          <a class="nav-link" href="{{ url_for('my_dashboard') }}">My Dashboard</a>
          <span class="nav-badge">🧑 {{ session.get('employee_name') }}</span>
          <a class="nav-link" href="{{ url_for('logout') }}">Logout</a>
        {% else %}
          <a class="nav-link" href="{{ url_for('login') }}">Employee Login</a>
          <a class="nav-link" href="{{ url_for('admin_login') }}">Admin Login</a>
        {% endif %}
        <button class="theme-toggle" id="themeBtn" title="Toggle theme">🌓 Theme</button>
      </nav>
    </div>
  </header>

  <main class="container">
    {% with messages = get_flashed_messages() %}
      {% if messages %}
        {% for msg in messages %}
          <div class="flash" role="status">{{ msg }}</div>
        {% endfor %}
      {% endif %}
    {% endwith %}

    <div class="panel" role="region" aria-label="Main content">
      {% block content %}{% endblock %}
      <div class="spacer"></div>
      <p class="muted">⚠️ Items are flagged if expiry is within {{ near_days }} days.</p>
    </div>
  </main>

  <footer>
    <div class="container">© {{ date.today().year }} · Made by <strong>Chinmoy & Harsh</strong></div>
  </footer>

  <script>
    // Theme persistence + search filter for tables
    (function(){
      const root = document.documentElement;
      const btn = document.getElementById('themeBtn');
      const stored = localStorage.getItem('theme') || 'dark';
      root.setAttribute('data-theme', stored);
      btn && btn.addEventListener('click', function(){
        const current = root.getAttribute('data-theme');
        const next = current === 'dark' ? 'light' : 'dark';
        root.setAttribute('data-theme', next);
        localStorage.setItem('theme', next);
      });
      // Auto-hide flash messages
      setTimeout(() => {
        document.querySelectorAll('.flash').forEach(el => el.style.display = 'none');
      }, 3000);

      // Client-side filter for any table with data-filter="true"
      document.querySelectorAll('[data-filter="true"]').forEach(wrapper => {
        const input = wrapper.querySelector('input[type="search"]');
        const rows = wrapper.querySelectorAll('tbody tr');
        if (!input) return;
        input.addEventListener('input', () => {
          const q = input.value.toLowerCase();
          rows.forEach(r => {
            const text = r.innerText.toLowerCase();
            r.style.display = text.includes(q) ? '' : 'none';
          });
        });
      });
    })();
  </script>
</body>
</html>
"""
app.jinja_loader = DictLoader({"base.html": BASE_HTML})

# ── Helpers / Decorators ─────────────────────────────────────────────
@app.context_processor
def inject_globals():
    # expose date to templates and keep existing globals
    return {"near_days": NEAR_EXPIRY_DAYS, "session": session, "date": date}

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("employee_id"):
            flash("Please log in with your Employee ID.")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper

def admin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("is_admin"):
            flash("Admin access required.")
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return wrapper

def days_to(date_obj: date) -> int:
    return (date_obj - date.today()).days

# ── Auth (Employee) ──────────────────────────────────────────────────
@app.route("/")
def root():
    if session.get("is_admin"):
        return redirect(url_for("admin_dashboard"))
    if session.get("employee_id"):
        return redirect(url_for("my_dashboard"))
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        code = (request.form.get("employee_code") or "").strip()
        emp = Employee.query.filter_by(employee_code=code).first()
        if emp:
            session.clear()
            session["employee_id"] = emp.id
            session["employee_name"] = emp.name
            flash(f"Welcome, {emp.name}!")
            return redirect(url_for("my_dashboard"))
        flash("Invalid Employee ID.")
    return render_template_string(
        """{% extends "base.html" %}{% block content %}
        <h2>Employee Login <span class=hint>Use your employee code</span></h2>
        <form method="post" aria-label="Employee Login Form">
          <div><input type="text" name="employee_code" placeholder="Employee ID (e.g., E1001)" required></div>
          <input class="btn btn-green" type="submit" value="Log In">
        </form>
        <p class="subtle">Tip: Ask Safety Admin for your Employee ID.</p>
        {% endblock %}"""
    )

@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out.")
    return redirect(url_for("login"))

# ── Auth (Admin) ─────────────────────────────────────────────────────
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        pin = (request.form.get("pin") or "").strip()
        if pin == ADMIN_PIN:
            session.clear()
            session["is_admin"] = True
            flash("Admin login successful.")
            return redirect(url_for("admin_dashboard"))
        flash("Invalid PIN.")
    return render_template_string(
        """{% extends "base.html" %}{% block content %}
        <h2>Admin Login</h2>
        <form method="post" aria-label="Admin Login Form">
          <div><input type="password" name="pin" placeholder="Enter admin PIN" required></div>
          <input class="btn btn-green" type="submit" value="Log In">
        </form>
        {% endblock %}"""
    )

# ── Employee Views ───────────────────────────────────────────────────
@app.route("/me")
@login_required
def my_dashboard():
    emp = Employee.query.get_or_404(session["employee_id"])
    mine = Equipment.query.filter_by(employee_id=emp.id, is_retired=False).order_by(Equipment.expiry_date.asc()).all()
    near_cutoff = date.today() + timedelta(days=NEAR_EXPIRY_DAYS)
    near = [e for e in mine if e.expiry_date <= near_cutoff]
    return render_template_string(
        """{% extends "base.html" %}{% block content %}
        <h2>My Dashboard</h2>
        <div class="row" role="list">
          <div class="card" role="listitem"><h3>My Equipment</h3><div class="big accent">{{ mine|length }}</div></div>
          <div class="card" role="listitem"><h3>Near Expiry (≤ {{ near_days }}d)</h3><div class="big">{{ near|length }}</div></div>
        </div>
        <h2 style="margin-top:18px;">Assigned to Me</h2>
        <div class="table-wrap">
          <table aria-label="My Equipment Table">
            <thead>
              <tr><th>Name</th><th>Expiry</th><th>Status</th><th>Action</th></tr>
            </thead>
            <tbody>
            {% for eq in mine %}
              {% set status = "ok" %}
              {% if eq.expiry_date <= near_cutoff %}{% set status = "near" %}{% endif %}
              <tr>
                <td>{{ eq.name }}</td>
                <td>{{ eq.expiry_date }}</td>
                <td>
                  {% if status == "near" %}
                    <span class="chip warn">⚠️ Near Expiry</span>
                  {% else %}
                    <span class="chip ok">✅ OK</span>
                  {% endif %}
                </td>
                <td class="actions">
                  <a class="btn btn-primary" href="{{ url_for('raise_issue', eq_id=eq.id) }}">Raise Issue</a>
                </td>
              </tr>
            {% else %}
              <tr><td colspan="4" class="muted">No equipment assigned.</td></tr>
            {% endfor %}
            </tbody>
          </table>
        </div>
        {% endblock %}""",
        mine=mine, near=near, near_cutoff=near_cutoff
    )

@app.route("/me/equipment")
@login_required
def my_equipment():
    # Kept for backward compatibility; redirect to dashboard
    return redirect(url_for("my_dashboard"))

# ── Admin Views / CRUD ───────────────────────────────────────────────
@app.route("/admin")
@admin_required
def admin_dashboard():
    equipment = Equipment.query.filter_by(is_retired=False).order_by(Equipment.expiry_date.asc()).all()
    today = date.today()
    near_cutoff = today + timedelta(days=NEAR_EXPIRY_DAYS)
    total_emp = Employee.query.count()
    total_eq = len(equipment)  # active only
    open_issues = Issue.query.filter_by(is_resolved=False).count()
    near = [e for e in equipment if e.expiry_date <= near_cutoff]
    return render_template_string(
        """{% extends "base.html" %}{% block content %}
        <h2>Admin Dashboard</h2>
        <div class="row" role="list">
          <div class="card" role="listitem"><h3>Employees</h3><div class="big accent">{{ total_emp }}</div></div>
          <div class="card" role="listitem"><h3>Equipment</h3><div class="big">{{ total_eq }}</div></div>
          <div class="card" role="listitem"><h3>Issues (Open)</h3><div class="big">{{ open_issues }}</div></div>
          <div class="card" role="listitem"><h3>Near Expiry (≤ {{ near_days }}d)</h3><div class="big">{{ near|length }}</div></div>
        </div>

        <h2 style="margin-top:18px;">All Equipment</h2>
        <div class="toolbar" data-filter="true">
          <div class="search"><input type="search" placeholder="Filter by name, assignee, status…" aria-label="Filter equipment"></div>
          <a class="btn btn-primary" href="{{ url_for('add_equipment') }}">+ Add Equipment</a>
        </div>
        <div class="table-wrap">
          <table aria-label="All Equipment Table">
            <thead>
              <tr><th>Name</th><th>Expiry</th><th>Assigned To</th><th>Status</th><th>Actions</th></tr>
            </thead>
            <tbody>
            {% for eq in equipment %}
              {% set status = "ok" %}
              {% if eq.expiry_date <= near_cutoff %}{% set status = "near" %}{% endif %}
              <tr>
                <td>{{ eq.name }}</td>
                <td>{{ eq.expiry_date }}</td>
                <td>{{ eq.employee.name if eq.employee else "Unassigned" }}</td>
                <td>
                  {% if status == "near" %}
                    <span class="chip warn">⚠️ Near Expiry</span>
                  {% else %}
                    <span class="chip ok">✅ OK</span>
                  {% endif %}
                </td>
                <td class="actions">
                  <a class="btn btn-primary" href="{{ url_for('assign_equipment', eq_id=eq.id) }}">Assign</a>
                  <a class="btn btn-primary" href="{{ url_for('raise_issue', eq_id=eq.id) }}">Raise Issue</a>
                </td>
              </tr>
            {% else %}
              <tr><td colspan="5" class="muted">No equipment yet.</td></tr>
            {% endfor %}
            </tbody>
          </table>
        </div>
        {% endblock %}""",
        equipment=equipment, total_emp=total_emp, total_eq=total_eq,
        open_issues=open_issues, near=near, near_cutoff=near_cutoff
    )

# Employees (Admin)
@app.route("/employees")
@admin_required
def list_employees():
    employees = Employee.query.order_by(Employee.name.asc()).all()
    return render_template_string(
        """{% extends "base.html" %}{% block content %}
        <h2>Employees</h2>
        <div class="toolbar" data-filter="true">
          <div class="search"><input type="search" placeholder="Filter by name or ID…" aria-label="Filter employees"></div>
          <a class="btn btn-primary" href="{{ url_for('add_employee') }}">+ Add Employee</a>
        </div>
        <div class="table-wrap">
          <table aria-label="Employees Table">
            <thead>
              <tr><th>Employee ID</th><th>Name</th><th>Holding</th><th>Actions</th></tr>
            </thead>
            <tbody>
            {% for emp in employees %}
              <tr>
                <td><code>{{ emp.employee_code }}</code></td>
                <td>{{ emp.name }}</td>
                <td>
                  {% set active = emp.equipments|selectattr('is_retired', 'equalto', False)|list %}
                  {% if active %}
                    {{ active|map(attribute='name')|join(', ') }}
                  {% else %}
                    <span class="muted">None</span>
                  {% endif %}
                </td>
                <td class="actions">
                  <a class="btn btn-danger" href="{{ url_for('remove_employee', emp_id=emp.id) }}"
                     onclick="return confirm('Remove {{ emp.name }}? Any assigned equipment will be unassigned.')">
                     Remove
                  </a>
                </td>
              </tr>
            {% else %}
              <tr><td colspan="4" class="muted">No employees yet.</td></tr>
            {% endfor %}
            </tbody>
          </table>
        </div>
        {% endblock %}""",
        employees=employees,
    )

@app.route("/employees/add", methods=["GET", "POST"])
@admin_required
def add_employee():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        code = (request.form.get("employee_code") or "").strip()
        if not name or not code:
            flash("Name and Employee ID are required.")
            return redirect(url_for("add_employee"))
        if Employee.query.filter_by(employee_code=code).first():
            flash("Employee ID already exists. Choose another.")
            return redirect(url_for("add_employee"))
        db.session.add(Employee(name=name, employee_code=code))
        db.session.commit()
        flash("Employee added.")
        return redirect(url_for("list_employees"))
    return render_template_string(
        """{% extends "base.html" %}{% block content %}
        <h2>Add Employee</h2>
        <form method="post" aria-label="Add Employee Form">
          <div><input type="text" name="employee_code" placeholder="Employee ID (e.g., E1001)" required></div>
          <div><input type="text" name="name" placeholder="Employee name" required></div>
          <input class="btn btn-green" type="submit" value="Add">
        </form>
        {% endblock %}"""
    )

@app.route("/employees/remove/<int:emp_id>")
@admin_required
def remove_employee(emp_id):
    emp = Employee.query.get_or_404(emp_id)
    # Unassign equipment (don't retire here; just unassign)
    for eq in emp.equipments:
        eq.employee_id = None
    db.session.delete(emp)
    db.session.commit()
    flash("Employee removed. Any assigned equipment was unassigned.")
    return redirect(url_for("list_employees"))

# Equipment (Admin)
@app.route("/equipment")
@admin_required
def list_equipment():
    equipment = Equipment.query.filter_by(is_retired=False).order_by(Equipment.expiry_date.asc()).all()
    return render_template_string(
        """{% extends "base.html" %}{% block content %}
        <h2>Equipment</h2>
        <div class="toolbar" data-filter="true">
          <div class="search"><input type="search" placeholder="Filter by name or assignee…" aria-label="Filter equipment list"></div>
          <a class="btn btn-primary" href="{{ url_for('add_equipment') }}">+ Add Equipment</a>
        </div>
        <div class="table-wrap">
          <table aria-label="Equipment Table">
            <thead>
              <tr><th>Name</th><th>Expiry</th><th>Assigned To</th><th>Actions</th></tr>
            </thead>
            <tbody>
            {% for eq in equipment %}
              <tr>
                <td>{{ eq.name }}</td>
                <td>{{ eq.expiry_date }}</td>
                <td>{{ eq.employee.name if eq.employee else "Unassigned" }}</td>
                <td class="actions">
                  <a class="btn btn-primary" href="{{ url_for('assign_equipment', eq_id=eq.id) }}">Assign</a>
                  <a class="btn btn-primary" href="{{ url_for('raise_issue', eq_id=eq.id) }}">Raise Issue</a>
                </td>
              </tr>
            {% else %}
              <tr><td colspan="4" class="muted">No equipment yet.</td></tr>
            {% endfor %}
            </tbody>
          </table>
        </div>
        {% endblock %}""",
        equipment=equipment,
    )

@app.route("/equipment/add", methods=["GET", "POST"])
@admin_required
def add_equipment():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        expiry_raw = request.form.get("expiry_date")
        if not name or not expiry_raw:
            flash("All fields are required.")
            return redirect(url_for("add_equipment"))
        expiry_date = datetime.strptime(expiry_raw, "%Y-%m-%d").date()
        db.session.add(Equipment(name=name, expiry_date=expiry_date))
        db.session.commit()
        flash("Equipment added.")
        return redirect(url_for("list_equipment"))
    return render_template_string(
        """{% extends "base.html" %}{% block content %}
        <h2>Add Equipment</h2>
        <form method="post" aria-label="Add Equipment Form">
          <div><input type="text" name="name" placeholder="Equipment name" required></div>
          <div><input type="date" name="expiry_date" required></div>
          <input class="btn btn-green" type="submit" value="Add">
        </form>
        {% endblock %}"""
    )

@app.route("/equipment/assign/<int:eq_id>", methods=["GET", "POST"])
@admin_required
def assign_equipment(eq_id):
    eq = Equipment.query.get_or_404(eq_id)
    if eq.is_retired:
        flash("This equipment is retired and cannot be assigned.")
        return redirect(url_for("list_equipment"))
    employees = Employee.query.order_by(Employee.name.asc()).all()
    if request.method == "POST":
        emp_id = int(request.form["employee_id"])
        eq.employee_id = emp_id
        db.session.commit()
        flash("Assigned equipment.")
        return redirect(url_for("list_equipment"))
    return render_template_string(
        """{% extends "base.html" %}{% block content %}
        <h2>Assign Equipment: {{ eq.name }}</h2>
        <form method="post" aria-label="Assign Equipment Form">
          <div>
            <select name="employee_id" required>
              <option value="">— Select employee —</option>
              {% for emp in employees %}
                <option value="{{ emp.id }}">{{ emp.name }} ({{ emp.employee_code }})</option>
              {% endfor %}
            </select>
          </div>
          <input class="btn btn-green" type="submit" value="Assign">
        </form>
        {% endblock %}""",
        eq=eq,
        employees=employees,
    )

# Issues (Admin + Employee raise)
@app.route("/issues")
@admin_required
def list_issues():
    issues = Issue.query.order_by(Issue.raised_on.desc()).all()
    return render_template_string(
        """{% extends "base.html" %}{% block content %}
        <h2>Issues</h2>
        <div class="table-wrap">
          <table aria-label="Issues Table">
            <thead>
              <tr>
                <th>ID</th><th>Equipment</th><th>Description</th>
                <th>Raised By</th><th>Raised On</th><th>Status</th><th>Actions</th>
              </tr>
            </thead>
            <tbody>
            {% for issue in issues %}
              <tr>
                <td>#{{ issue.id }}</td>
                <td>{{ issue.equipment_id }} — {{ issue.equipment.name if issue.equipment_id and issue.equipment else "N/A" }}</td>
                <td>{{ issue.description }}</td>
                <td>
                  {% if issue.raised_by_employee_id and issue.employee_raiser %}
                    {{ issue.employee_raiser.name }} ({{ issue.employee_raiser.employee_code }})
                  {% else %}
                    <span class="muted">Admin</span>
                  {% endif %}
                </td>
                <td>{{ issue.raised_on.strftime('%d-%b-%Y %H:%M') }}</td>
                <td>
                  {% if issue.is_resolved %}
                    <span class="chip ok">✅ Solved{% if issue.resolved_on %} ({{ issue.resolved_on.strftime('%d-%b-%Y %H:%M') }}){% endif %}</span>
                  {% else %}
                    <span class="chip warn">⚠️ Open</span>
                  {% endif %}
                </td>
                <td class="actions">
                  {% if issue.is_resolved %}
                    <a class="btn btn-primary" href="{{ url_for('resolve_issue', issue_id=issue.id) }}">Reopen</a>
                  {% else %}
                    <a class="btn btn-green" href="{{ url_for('resolve_issue', issue_id=issue.id) }}">Mark Solved</a>
                  {% endif %}
                  <a class="btn btn-danger" href="{{ url_for('delete_issue', issue_id=issue.id) }}"
                     onclick="return confirm('Delete issue #{{ issue.id }} permanently?')">Delete</a>
                </td>
              </tr>
            {% else %}
              <tr><td colspan="7" class="muted">No issues yet.</td></tr>
            {% endfor %}
            </tbody>
          </table>
        </div>
        {% endblock %}""",
        issues=issues,
    )

@app.route("/issues/raise/<int:eq_id>", methods=["GET", "POST"])
def raise_issue(eq_id):
    eq = Equipment.query.get_or_404(eq_id)
    if eq.is_retired:
        flash("This equipment is retired. You cannot raise a new issue.")
        return redirect(url_for("root"))
    if request.method == "POST":
        desc = (request.form.get("description") or "").strip()
        if not desc:
            flash("Description is required.")
            return redirect(url_for("raise_issue", eq_id=eq.id))
        issue = Issue(equipment_id=eq.id, description=desc)
        if session.get("employee_id"):
            issue.raised_by_employee_id = session["employee_id"]
        db.session.add(issue)
        db.session.commit()
        flash("Issue raised.")
        # Redirect smartly
        if session.get("is_admin"):
            return redirect(url_for("admin_dashboard"))
        elif session.get("employee_id"):
            return redirect(url_for("my_dashboard"))
        else:
            return redirect(url_for("root"))
    return render_template_string(
        """{% extends "base.html" %}{% block content %}
        <h2>Raise Issue: {{ eq.name }}</h2>
        <form method="post" aria-label="Raise Issue Form">
          <div><input type="text" name="description" placeholder="Describe the issue…" required></div>
          <input class="btn btn-green" type="submit" value="Raise">
        </form>
        {% endblock %}""",
        eq=eq,
    )

# Toggle resolve / reopen
@app.route("/issues/resolve/<int:issue_id>")
@admin_required
def resolve_issue(issue_id):
    issue = Issue.query.get_or_404(issue_id)
    eq = issue.equipment

    # Toggle state
    issue.is_resolved = not issue.is_resolved
    issue.resolved_on = datetime.utcnow() if issue.is_resolved else None

    # If solved, unassign and retire equipment so it vanishes from dashboards
    if issue.is_resolved and eq:
        eq.employee_id = None
        eq.is_retired = True
        eq.retired_on = datetime.utcnow()

    # If reopened, allow equipment to come back (optional behavior).
    # Comment these 3 lines if you never want a reopened issue to reactivate the equipment.
    if not issue.is_resolved and eq:
        eq.is_retired = False
        eq.retired_on = None

    db.session.commit()
    flash(
        "Issue marked as resolved. Equipment unassigned and retired."
        if issue.is_resolved else
        "Issue re-opened. Equipment reactivated."
    )
    return redirect(url_for("list_issues"))

# Delete issue
@app.route("/issues/delete/<int:issue_id>")
@admin_required
def delete_issue(issue_id):
    issue = Issue.query.get_or_404(issue_id)
    db.session.delete(issue)
    db.session.commit()
    flash("Issue deleted.")
    return redirect(url_for("list_issues"))

# ── Init / Seed (optional for first run) ─────────────────────────────
def seed_if_empty():
    if Employee.query.count() == 0:
        demo = [
            Employee(name="Chinmoy Das", employee_code="E1001"),
            Employee(name="Harsha Das", employee_code="E1002"),
            Employee(name="Koustav Patowary", employee_code="E1003"),
        ]
        db.session.add_all(demo)
    if Equipment.query.count() == 0:
        today = date.today()
        demo_eq = [
            Equipment(name="Safety Helmet", expiry_date=today + timedelta(days=10)),
            Equipment(name="Fire Extinguisher CO₂", expiry_date=today + timedelta(days=3)),
            Equipment(name="Safety Harness", expiry_date=today + timedelta(days=90)),
        ]
        db.session.add_all(demo_eq)
    db.session.commit()

# ── Simple Auto-migrations ───────────────────────────────────────────
def ensure_issue_status_columns():
    """Add is_resolved / resolved_on if DB was created before this change."""
    insp = inspect(db.engine)
    try:
        cols = {c["name"] for c in insp.get_columns("issue")}
    except Exception:
        cols = set()
    with db.engine.begin() as conn:
        if "is_resolved" not in cols:
            conn.execute(text('ALTER TABLE "issue" ADD COLUMN is_resolved BOOLEAN DEFAULT 0'))
        if "resolved_on" not in cols:
            conn.execute(text('ALTER TABLE "issue" ADD COLUMN resolved_on TIMESTAMP NULL'))

def ensure_equipment_retire_columns():
    """Add is_retired / retired_on on equipment if missing."""
    insp = inspect(db.engine)
    try:
        cols = {c["name"] for c in insp.get_columns("equipment")}
    except Exception:
        cols = set()
    with db.engine.begin() as conn:
        if "is_retired" not in cols:
            conn.execute(text('ALTER TABLE "equipment" ADD COLUMN is_retired BOOLEAN DEFAULT 0'))
        if "retired_on" not in cols:
            conn.execute(text('ALTER TABLE "equipment" ADD COLUMN retired_on TIMESTAMP NULL'))

# ── Main ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        ensure_issue_status_columns()     # ensure new Issue columns exist
        ensure_equipment_retire_columns() # ensure new Equipment columns exist
        seed_if_empty()
    # Optional: list routes to confirm what's available
    print("\nRegistered routes:")
    for r in app.url_map.iter_rules():
        print(f"  {r.rule:30s} -> {','.join(sorted(r.methods))}  (endpoint: {r.endpoint})")
    print("\nSafety Equipment Tracker running at http://127.0.0.1:5000")
    print("Employee portal: /login (use E1001/E1002/E1003 from seed)")
    print(f"Admin portal: /admin/login (PIN={ADMIN_PIN})\n")
    app.run(host="0.0.0.0", port=5000, debug=True)
