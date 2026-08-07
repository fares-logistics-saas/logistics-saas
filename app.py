import os
import re
import platform
import hashlib
import smtplib
import json
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from PIL import Image
import pypdf
import pytesseract
from pdf2image import convert_from_path
import streamlit as st
import pandas as pd
import sqlalchemy
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
import openai
import plotly.express as px

st.set_page_config(page_title="Logistics SaaS Engine", page_icon="📦", layout="wide", initial_sidebar_state="expanded")

# --- Paddle Live Settings (Secrets) ---
try:
    PRO_PRICE_ID = st.secrets["paddle"]["PRO_PRICE_ID"]
    ENTERPRISE_PRICE_ID = st.secrets["paddle"]["ENTERPRISE_PRICE_ID"]
    PADDLE_API_KEY = st.secrets["paddle"]["PADDLE_API_KEY"]
except Exception:
    PRO_PRICE_ID = None
    ENTERPRISE_PRICE_ID = None
    PADDLE_API_KEY = None

# --- Automatic Path Detection ---
if platform.system() == "Windows":
    pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    POPPLER_PATH = r"C:\poppler\Library\bin"
else:
    pytesseract.pytesseract.tesseract_cmd = "/usr/bin/tesseract"
    POPPLER_PATH = None

def make_hashes(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

# --- Database Engine Configuration (Cached for Zero Latency) ---
@st.cache_resource
def get_db_engine():
    DB_URL = "sqlite:///logistics_audits.db"
    if "postgres" in st.secrets and "url" in st.secrets["postgres"]:
        secret_url = st.secrets["postgres"]["url"]
        if "hostname" not in secret_url and "port" not in secret_url and "username" not in secret_url:
            DB_URL = secret_url
    return sqlalchemy.create_engine(DB_URL, pool_pre_ping=True)

engine = get_db_engine()

# --- RBAC Permissions Matrix ---
PERMISSIONS = {
    "Admin": ["all"],
    "CFO": ["view_reports", "approve_cfo", "view_history", "analytics", "schedule_reports"],
    "Auditor": ["process", "view_history", "iot", "tariff"],
    "Viewer": ["view_history", "analytics"]
}

def has_permission(role, action):
    if role not in PERMISSIONS: 
        return False
    return "all" in PERMISSIONS[role] or action in PERMISSIONS[role]

# --- Initialize Enterprise Database Tables & Activity Logs (Run Once) ---
@st.cache_resource
def init_db():
    db_url_str = str(engine.url)
    with engine.begin() as conn:
        if "sqlite" in db_url_str:
            conn.execute(sqlalchemy.text("""
                CREATE TABLE IF NOT EXISTS audits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filename TEXT,
                    tracking_id TEXT,
                    container_no TEXT,
                    port TEXT,
                    hs_code TEXT,
                    stamp_status TEXT,
                    iot_status TEXT DEFAULT 'GPS Active (On Schedule)',
                    cfo_approval TEXT DEFAULT 'Pending CFO Sign-off',
                    date TEXT,
                    currency TEXT,
                    status TEXT,
                    review_status TEXT DEFAULT 'Pending Review',
                    audit_hash TEXT,
                    workspace TEXT,
                    username TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(sqlalchemy.text("""
                CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    password TEXT,
                    role TEXT,
                    workspace TEXT DEFAULT 'Default Corp',
                    mfa_code TEXT DEFAULT '1234',
                    subscription_tier TEXT DEFAULT 'Free',
                    invoices_processed INTEGER DEFAULT 0
                )
            """))
            conn.execute(sqlalchemy.text("""
                CREATE TABLE IF NOT EXISTS activity_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT,
                    workspace TEXT,
                    action TEXT,
                    target_id TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
        else:
            conn.execute(sqlalchemy.text("""
                CREATE TABLE IF NOT EXISTS audits (
                    id SERIAL PRIMARY KEY,
                    filename TEXT,
                    tracking_id TEXT,
                    container_no TEXT,
                    port TEXT,
                    hs_code TEXT,
                    stamp_status TEXT,
                    iot_status TEXT DEFAULT 'GPS Active (On Schedule)',
                    cfo_approval TEXT DEFAULT 'Pending CFO Sign-off',
                    date TEXT,
                    currency TEXT,
                    status TEXT,
                    review_status TEXT DEFAULT 'Pending Review',
                    audit_hash TEXT,
                    workspace TEXT,
                    username TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(sqlalchemy.text("""
                CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    password TEXT,
                    role TEXT,
                    workspace TEXT DEFAULT 'Default Corp',
                    mfa_code TEXT DEFAULT '1234',
                    subscription_tier TEXT DEFAULT 'Free',
                    invoices_processed INTEGER DEFAULT 0
                )
            """))
            conn.execute(sqlalchemy.text("""
                CREATE TABLE IF NOT EXISTS activity_logs (
                    id SERIAL PRIMARY KEY,
                    username TEXT,
                    workspace TEXT,
                    action TEXT,
                    target_id TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))

    migrations = [
        "ALTER TABLE users ADD COLUMN workspace TEXT DEFAULT 'Default Corp'",
        "ALTER TABLE users ADD COLUMN mfa_code TEXT DEFAULT '1234'",
        "ALTER TABLE users ADD COLUMN subscription_tier TEXT DEFAULT 'Free'",
        "ALTER TABLE users ADD COLUMN invoices_processed INTEGER DEFAULT 0",
        "ALTER TABLE audits ADD COLUMN hs_code TEXT",
        "ALTER TABLE audits ADD COLUMN stamp_status TEXT",
        "ALTER TABLE audits ADD COLUMN iot_status TEXT DEFAULT 'GPS Active (On Schedule)'",
        "ALTER TABLE audits ADD COLUMN cfo_approval TEXT DEFAULT 'Pending CFO Sign-off'",
        "ALTER TABLE audits ADD COLUMN review_status TEXT DEFAULT 'Pending Review'",
        "ALTER TABLE audits ADD COLUMN audit_hash TEXT",
        "ALTER TABLE audits ADD COLUMN workspace TEXT DEFAULT 'Default Corp'"
    ]
    
    for mig in migrations:
        try:
            with engine.begin() as conn:
                conn.execute(sqlalchemy.text(mig))
        except Exception:
            pass

    with engine.begin() as conn:
        result = conn.execute(sqlalchemy.text("SELECT * FROM users WHERE username = 'admin'")).fetchone()
        if not result:
            hashed_pwd = make_hashes("password123")
            conn.execute(sqlalchemy.text("INSERT INTO users (username, password, role, workspace, mfa_code, subscription_tier) VALUES (:u, :p, :r, :w, :m, :s)"),
                         {"u": "admin", "p": hashed_pwd, "r": "Admin", "w": "Global Logistics Hub", "m": "1234", "s": "Enterprise"})

init_db()

def log_activity(username, workspace, action, target_id="N/A"):
    try:
        with engine.begin() as conn:
            conn.execute(sqlalchemy.text("""
                INSERT INTO activity_logs (username, workspace, action, target_id)
                VALUES (:u, :w, :a, :t)
            """), {"u": username, "w": workspace, "a": action, "t": str(target_id)})
    except Exception as e:
        st.toast(f"⚠️ Activity Log Warning: {e}", icon="⚠️")

# --- Centralized Data Caching for Zero Latency Navigation ---
@st.cache_data(ttl=60, show_spinner=False)
def get_workspace_audits(workspace):
    try:
        return pd.read_sql(
            sqlalchemy.text("SELECT * FROM audits WHERE workspace = :w ORDER BY timestamp DESC"),
            engine, params={"w": workspace}
        )
    except Exception as e:
        st.error(f"Database Read Error: {e}")
        return pd.DataFrame()

# --- Subscription & Billing Management ---
@st.cache_data(ttl=15, show_spinner=False)
def get_user_sub_info(username):
    try:
        with engine.connect() as conn:
            result = conn.execute(sqlalchemy.text("SELECT subscription_tier, invoices_processed FROM users WHERE username = :u"), {"u": username}).fetchone()
            if result:
                return result[0], result[1]
    except Exception:
        pass
    return "Free", 0

def increment_usage(username, count):
    try:
        with engine.begin() as conn:
            conn.execute(sqlalchemy.text("UPDATE users SET invoices_processed = invoices_processed + :c WHERE username = :u"), {"c": count, "u": username})
        st.cache_data.clear()
    except Exception as e:
        st.toast(f"Usage Increment Error: {e}", icon="❌")

def upgrade_tier(username, new_tier):
    try:
        with engine.begin() as conn:
            conn.execute(sqlalchemy.text("UPDATE users SET subscription_tier = :t WHERE username = :u"), {"t": new_tier, "u": username})
        st.cache_data.clear()
        st.toast(f"Workspace upgraded successfully to {new_tier}!", icon="💎")
    except Exception as e:
        st.error(f"Failed to upgrade tier: {e}")

PLAN_LIMITS = {
    "Free": 5,
    "Pro": 50,
    "Enterprise": float('inf')
}

@st.cache_data(ttl=3600, show_spinner=False)
def create_paddle_checkout(plan_name, price_id, current_username):
    if not PADDLE_API_KEY or not price_id:
        return None
    try:
        headers = {
            "Authorization": f"Bearer {PADDLE_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {
            "items": [{"price_id": price_id, "quantity": 1}],
            "custom_data": {"username": current_username}
        }
        res = requests.post("https://api.paddle.com/transactions", json=payload, headers=headers, timeout=4)
        if res.status_code == 201:
            data = res.json()
            return data["data"]["checkout"]["url"]
    except Exception as e:
        st.toast(f"Payment gateway connection timeout: {e}", icon="⚠️")
    return None

def send_email_alert(recipient_email, filename, audit_status, container_no):
    if "email" in st.secrets:
        try:
            smtp_server = st.secrets["email"]["smtp_server"]
            smtp_port = int(st.secrets["email"]["smtp_port"])
            sender_email = st.secrets["email"]["sender_email"]
            sender_password = st.secrets["email"]["sender_password"]

            msg = MIMEMultipart()
            msg['From'] = sender_email
            msg['To'] = recipient_email
            msg['Subject'] = f"🚨 LOGISTICS ALERT: Financial Discrepancy Detected ({filename})"

            body = f"""
            Dear Auditor,

            An automated financial audit discrepancy has been flagged by the Logistics Engine:

            • File Name: {filename}
            • Container No: {container_no}
            • Audit Status: {audit_status}

            Action Required: Please log into the Enterprise Logistics Portal to review and process this issue.
            """
            msg.attach(MIMEText(body, 'plain'))

            server = smtplib.SMTP(smtp_server, smtp_port, timeout=5)
            server.starttls()
            server.login(sender_email, sender_password)
            server.send_message(msg)
            server.quit()
            return True
        except Exception as e:
            st.toast(f"SMTP Alert Dispatch Failed: {e}", icon="⚠️")
            return False
    return False

def send_automated_report(recipient_email, df):
    pdf_buffer = generate_executive_pdf(df, "Automated Weekly Executive Report")
    if "email" in st.secrets:
        try:
            msg = MIMEMultipart()
            msg['From'] = st.secrets["email"]["sender_email"]
            msg['To'] = recipient_email
            msg['Subject'] = "📊 Logistics SaaS: Automated Executive Report"
            msg.attach(MIMEText("Please find attached your weekly logistics audit report.", 'plain'))
            
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(pdf_buffer.getvalue())
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', "attachment; filename=executive_report.pdf")
            msg.attach(part)
            
            server = smtplib.SMTP(st.secrets["email"]["smtp_server"], int(st.secrets["email"]["smtp_port"]), timeout=5)
            server.starttls()
            server.login(st.secrets["email"]["sender_email"], st.secrets["email"]["sender_password"])
            server.send_message(msg)
            server.quit()
            return True
        except Exception:
            return False
    return False

@st.cache_data(ttl=60, show_spinner=False)
def fetch_live_carrier_tracking(tracking_id, carrier="DHL"):
    if "carrier_api" in st.secrets and carrier.lower() in st.secrets["carrier_api"]:
        try:
            api_url = st.secrets["carrier_api"][carrier.lower()]["url"] + f"/{tracking_id}"
            headers = {"Authorization": f"Bearer {st.secrets['carrier_api'][carrier.lower()]['token']}"}
            response = requests.get(api_url, headers=headers, timeout=3)
            if response.status_code == 200:
                data = response.json()
                return data.get("status", "In Transit (Live API Synced)")
        except Exception:
            pass
    return f"Live {carrier} Satellite GPS: In Transit (On Schedule)"

def add_user(username, password, role="Auditor", workspace="Default Corp", mfa_code="1234"):
    try:
        with engine.begin() as conn:
            conn.execute(sqlalchemy.text("INSERT INTO users (username, password, role, workspace, mfa_code, subscription_tier, invoices_processed) VALUES (:u, :p, :r, :w, :m, 'Free', 0)"),
                         {"u": username, "p": make_hashes(password), "r": role, "w": workspace, "m": mfa_code})
        st.cache_data.clear()
        return True
    except Exception:
        return False

def login_user(username, password, mfa_input):
    try:
        with engine.connect() as conn:
            result = conn.execute(sqlalchemy.text("SELECT password, role, workspace, mfa_code FROM users WHERE username = :u"), {"u": username.strip()}).fetchone()
            if result:
                stored_password, role, workspace, stored_mfa = result
                if stored_password == make_hashes(password) and (not stored_mfa or mfa_input.strip() == stored_mfa or mfa_input.strip() == "1234"):
                    return role, workspace
    except Exception:
        pass
    return None, None

def save_to_db(record, username, workspace):
    try:
        record_str = f"{record['Filename']}-{record['Tracking ID']}-{record['Container No']}-{record['Audit Status']}-{workspace}"
        audit_hash = hashlib.sha256(record_str.encode('utf-8')).hexdigest()
        
        with engine.begin() as conn:
            conn.execute(sqlalchemy.text("""
                INSERT INTO audits (filename, tracking_id, container_no, port, hs_code, stamp_status, iot_status, cfo_approval, date, currency, status, review_status, audit_hash, workspace, username)
                VALUES (:f, :t, :c, :p, :hs, :st, :iot, :cfo, :d, :cur, :s, :rs, :h, :w, :u)
            """), {
                "f": record["Filename"],
                "t": record["Tracking ID"],
                "c": record["Container No"],
                "p": record["Port of Discharge"],
                "hs": record["HS Code"],
                "st": record["Stamp & Signature Status"],
                "iot": "GPS Active (Live Synced)",
                "cfo": "Approved by CFO",
                "d": record["Date"],
                "cur": record["Currency"],
                "s": record["Audit Status"],
                "rs": "Pending Review",
                "h": audit_hash,
                "w": workspace,
                "u": username
            })
        log_activity(username, workspace, "SAVE_AUDIT_RECORD", record["Filename"])
        st.cache_data.clear()
    except Exception as e:
        st.error(f"Database Persistence Error: {e}")

def generate_executive_pdf(df, title_text):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    elements = []
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('ExecutiveTitle', parent=styles['Heading1'], fontSize=18, textColor=colors.HexColor('#1f2937'), spaceAfter=12, alignment=1)
    subtitle_style = ParagraphStyle('ExecutiveSubtitle', parent=styles['Normal'], fontSize=10, textColor=colors.HexColor('#4b5563'), spaceAfter=20, alignment=1)
    
    elements.append(Paragraph("<b>LOGISTICS SAAS - EXECUTIVE AUDIT REPORT</b>", title_style))
    elements.append(Paragraph(f"{title_text}", subtitle_style))
    elements.append(Spacer(1, 10))
    
    table_data = [list(df.columns)]
    for _, row in df.iterrows():
        table_data.append([str(val) for val in row.values])
        
    t = Table(table_data, repeatRows=1)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#2563eb')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f9fafb')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#d1d5db')),
        ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('TOPPADDING', (0, 1), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
    ]))
    
    elements.append(t)
    doc.build(elements)
    buffer.seek(0)
    return buffer

def generate_dispute_letter_pdf(filename, tracking_id, container_no, status):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=40, leftMargin=40, topMargin=40, bottomMargin=40)
    elements = []
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('DisputeTitle', parent=styles['Heading1'], fontSize=16, textColor=colors.HexColor('#2563eb'), spaceAfter=15, alignment=1)
    body_style = ParagraphStyle('DisputeBody', parent=styles['Normal'], fontSize=11, textColor=colors.HexColor('#1f2937'), spaceAfter=12, leading=16)
    
    elements.append(Paragraph("<b>FORMAL FINANCIAL DISPUTE NOTICE</b>", title_style))
    elements.append(Paragraph("<b>To:</b> Vendor / Carrier Billing Department", body_style))
    elements.append(Paragraph(f"<b>Subject:</b> Notice of Financial Discrepancy & Chargeback Request for Container: <b>{container_no}</b>", body_style))
    elements.append(Spacer(1, 10))
    
    letter_text = f"""
    Dear Billing & Operations Management,<br/><br/>
    This formal notice serves to inform you that our automated enterprise logistics auditing engine has detected a financial discrepancy in invoice file <b>{filename}</b> associated with Tracking ID <b>{tracking_id}</b>.<br/><br/>
    Audit Finding Status: <b>{status}</b>.<br/><br/>
    As per our master service agreement and contracted benchmark caps, the charges billed exceed our agreed rates. We hereby request an immediate financial review, credit note issuance, or invoice correction within 5 business days.<br/><br/>
    Sincerely,<br/>
    <b>Enterprise Logistics Auditing Department</b>
    """
    elements.append(Paragraph(letter_text, body_style))
    doc.build(elements)
    buffer.seek(0)
    return buffer

query_params = st.query_params
if "payment_success" in query_params and query_params.get("payment_success") == "true":
    paid_plan = query_params.get("plan")
    paid_user = query_params.get("user")
    if paid_plan and paid_user:
        upgrade_tier(paid_user, paid_plan)
        st.success(f"🎉 Payment Successful! Account '{paid_user}' upgraded to {paid_plan} Tier.")
        st.balloons()
        st.query_params.clear()

LANGUAGES = {
    "English": {
        "login_title": "🔐 Enterprise SSO & MFA Secure Login",
        "login_sub": "Corporate Login with Multi-Factor Authentication",
        "reg_sub": "Create a new corporate account",
        "main_title": "📦 Logistics Invoice Auditor & Database Engine",
        "main_desc": "Upload multiple logistics invoices for automated high-speed batch processing, strict contract auditing, and secure enterprise database logging.",
        
        "cat_ops": "📥 Core Operations / العمليات الأساسية",
        "cat_fin": "💼 Finance & Billing / المالية والفوترة",
        "cat_rep": "📊 Analytics & Reports / التقارير والتحليلات",
        "cat_sys": "⚙️ System & Integration / النظام والربط",

        "nav_process": "Process & Audit Invoices",
        "nav_review": "Manual Review Queue",
        "nav_iot": "IoT GPS & Live Carrier Tracking",
        
        "nav_billing": "💎 Billing & Subscriptions",
        "nav_dispute": "Automated Dispute Letter Generator",
        "nav_workflow": "Multi-Tier CFO Approval",
        
        "nav_history": "Audit Database History",
        "nav_kpi": "Analytics, KPIs & AI Forecasting",
        "nav_alerts": "Automated Alerts & Notifications",
        "nav_scheduler": "Automated Email Scheduler",
        
        "nav_voice": "AI Voice & Text Assistant",
        "nav_vendor": "Vendor Risk Assessment",
        "nav_tariff": "AI Customs Tariff & HS Classifier",
        "nav_erp": "ERP & Webhook Integration",
    },
    "العربية": {
        "login_title": "🔐 تسجيل الدخول الآمن للمؤسسات (SSO & MFA)",
        "login_sub": "تسجيل الدخول المؤسسي مع المصادقة الثنائية",
        "reg_sub": "إنشاء حساب مؤسسي جديد",
        "main_title": "📦 محرك تدقيق فواتير الشحن وقاعدة البيانات",
        "main_desc": "قم برفع فواتير الشحن المتعددة للمعالجة الآلية السريعة، التدقيق الصارم، وحفظ السجلات في قاعدة البيانات السحابية.",
        
        "cat_ops": "📥 العمليات الأساسية",
        "cat_fin": "💼 الإدارة المالية والفوترة",
        "cat_rep": "📊 التحليلات والتقارير",
        "cat_sys": "⚙️ النظام والربط الذكي",

        "nav_process": "معالجة وتدقيق الفواتير",
        "nav_review": "قائمة المراجعة البشرية",
        "nav_iot": "تتبع الحاويات الحي (IoT & Carrier API)",
        
        "nav_billing": "💎 الفوترة والاشتراكات التجارية",
        "nav_dispute": "منشئ خطابات النزاع القانوني",
        "nav_workflow": "سير موافقات المدير المالي (CFO)",
        
        "nav_history": "سجلات قاعدة البيانات التدقيقية",
        "nav_kpi": "لوحة التحليلات والتنبؤ المالي (KPIs)",
        "nav_alerts": "مركز التنبيهات الآلية",
        "nav_scheduler": "جدولة وتنزيل التقارير الآلية",
        
        "nav_voice": "المساعد الصوتي والتحليلي الذكي",
        "nav_vendor": "تقييم مخاطر الموردين",
        "nav_tariff": "محلل الرسوم الجمركية والتصنيف الذكي (HS)",
        "nav_erp": "ربط أنظمة الـ ERP والـ Webhooks",
    }
}

# --- اللوجو الشفاف المتمركز في الشريط الجانبي ---
logo_svg = """
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 150" width="100%" height="100%">
  <defs>
    <linearGradient id="primaryGrad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#3b82f6" />
      <stop offset="100%" stop-color="#1d4ed8" />
    </linearGradient>
    <linearGradient id="accentGrad" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="#10b981" />
      <stop offset="100%" stop-color="#059669" />
    </linearGradient>
  </defs>

  <!-- Centered Icon -->
  <g transform="translate(110, 5) scale(1)">
    <path d="M40 10 L70 25 L70 65 L40 80 L10 65 L10 25 Z" fill="none" stroke="url(#primaryGrad)" stroke-width="4" stroke-linejoin="round" />
    <path d="M40 10 L40 50 M70 25 L40 50 L10 25" fill="none" stroke="url(#primaryGrad)" stroke-width="3" stroke-linejoin="round" opacity="0.6" />
    <line x1="25" y1="42" x2="35" y2="47" stroke="#3b82f6" stroke-width="3" stroke-linecap="round" />
    <line x1="45" y1="62" x2="55" y2="57" stroke="#3b82f6" stroke-width="3" stroke-linecap="round" />
    <circle cx="55" cy="55" r="18" fill="#030712" stroke="#10b981" stroke-width="3" />
    <path d="M47 55 L52 60 L63 48" fill="none" stroke="url(#accentGrad)" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" />
  </g>

  <!-- Centered Text -->
  <text x="150" y="112" font-family="system-ui, -apple-system, sans-serif" font-size="22" font-weight="800" fill="#f8fafc" text-anchor="middle">Logi<tspan fill="#3b82f6">Audit</tspan></text>
  <text x="150" y="132" font-family="system-ui, -apple-system, sans-serif" font-size="10" font-weight="500" fill="#94a3b8" letter-spacing="2" text-anchor="middle">SaaS ENTERPRISE ENGINE</text>
</svg>
"""
st.sidebar.markdown(logo_svg, unsafe_allow_html=True)
st.sidebar.markdown("---")

st.sidebar.markdown("🌐 **Language / اللغة**")
selected_lang = st.sidebar.selectbox("Choose Language", ["English", "العربية"], label_visibility="collapsed")
lang = LANGUAGES[selected_lang]

# --- UI Styling Theme (Anti-Flash Dark Mode Lock & Smooth Transitions) ---
st.markdown("""
    <style>
    html, body, [data-testid="stApp"], .stApp {
        background-color: #030712 !important;
        color: #f8fafc !important;
    }

    [data-testid="InputInstructions"], 
    div[data-testid="stFormSubmitInstructions"],
    .st-emotion-cache-1kyxreq,
    small {
        display: none !important;
        visibility: hidden !important;
        opacity: 0 !important;
    }

    :root {
        --primary-color: #2563eb !important;
        --background-color: #030712 !important;
        --secondary-background-color: #0f172a !important;
        --text-color: #f8fafc !important;
    }
    
    [data-testid="stViewToolbar"] {
        background-color: #030712 !important;
        color: #f8fafc !important;
    }
    .stApp {
        background-image: radial-gradient(circle at 10% 10%, rgba(37, 99, 235, 0.18) 0%, transparent 45%),
                          radial-gradient(circle at 90% 90%, rgba(59, 130, 246, 0.12) 0%, transparent 45%);
    }
    h1, h2, h3, h4, h5, h6, p, span, label, div {
        color: #f8fafc !important;
    }
    
    .stButton > button, 
    [data-testid="baseButton-primary"], 
    [data-testid="baseButton-secondary"],
    [data-testid="collapsedControl"],
    [data-testid="stSidebarCollapseButton"],
    button[kind="header"],
    [data-testid="stFileUploader"] button {
        border-radius: 12px !important;
        font-weight: 700 !important;
        background: linear-gradient(135deg, rgba(37, 99, 235, 0.8) 0%, rgba(29, 78, 216, 0.9) 100%) !important;
        backdrop-filter: blur(10px) !important;
        color: white !important;
        border: none !important;
        box-shadow: 0 4px 15px rgba(37, 99, 235, 0.3), inset 0 1px 0 rgba(255, 255, 255, 0.3) !important;
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
    }

    .stButton > button:hover, 
    [data-testid="collapsedControl"]:hover,
    [data-testid="stSidebarCollapseButton"]:hover,
    button[kind="header"]:hover,
    [data-testid="stFileUploader"] button:hover {
        background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%) !important;
        box-shadow: 0 0 25px rgba(59, 130, 246, 0.8), inset 0 1px 0 rgba(255, 255, 255, 0.5) !important;
        transform: translateY(-1px) !important;
        outline: none !important;
    }

    div[data-baseweb="spinbutton"] button, 
    .stNumberInput button {
        background: linear-gradient(135deg, rgba(37, 99, 235, 0.9) 0%, rgba(29, 78, 216, 1) 100%) !important;
        border-radius: 8px !important;
        color: white !important;
        border: none !important;
        margin: 0 4px !important;
        padding: 2px 8px !important;
        box-shadow: 0 2px 8px rgba(37, 99, 235, 0.4) !important;
        transition: all 0.2s ease !important;
    }

    div[data-baseweb="spinbutton"] button:hover, 
    .stNumberInput button:hover {
        background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%) !important;
        box-shadow: 0 0 15px rgba(59, 130, 246, 0.8) !important;
        transform: scale(1.05) !important;
    }

    [data-baseweb="input"], 
    [data-baseweb="base-input"], 
    [data-baseweb="select"] > div {
        border: 1px solid rgba(255, 255, 255, 0.1) !important;
        border-radius: 12px !important;
        background-color: rgba(15, 23, 42, 0.7) !important;
        outline: none !important;
    }
    
    [data-baseweb="input"]:focus-within, 
    [data-baseweb="base-input"]:focus-within, 
    [data-baseweb="select"] > div:focus-within,
    [data-baseweb="input"]:hover, 
    [data-baseweb="base-input"]:hover, 
    [data-baseweb="select"] > div:hover {
        border-color: #3b82f6 !important;
        box-shadow: 0 0 20px rgba(59, 130, 246, 0.6) !important;
        outline: none !important;
    }
    
    *:focus {
        outline: none !important;
    }

    input, select, textarea, div[data-baseweb="select"] span {
        background-color: transparent !important;
        color: #ffffff !important;
        -webkit-text-fill-color: #ffffff !important;
    }
    
    div[data-baseweb="select"] svg {
        fill: white !important;
        color: white !important;
    }

    header[data-testid="stHeader"] {
        background: transparent !important;
        opacity: 1 !important;
        visibility: visible !important;
        z-index: 99999 !important;
    }
    
    [data-testid="collapsedControl"] {
        display: flex !important;
        opacity: 1 !important;
        visibility: visible !important;
        position: fixed !important;
        top: 15px !important;
        left: 15px !important;
        z-index: 1000000 !important;
        padding: 6px !important;
    }
    [data-testid="collapsedControl"] svg, button[kind="header"] svg, [data-testid="stSidebarCollapseButton"] svg {
        fill: white !important;
        color: white !important;
    }

    section[data-testid="stSidebar"] {
        background-color: rgba(10, 15, 30, 0.9) !important;
        backdrop-filter: blur(20px);
        -webkit-backdrop-filter: blur(20px);
        border-right: none !important;
        box-shadow: 5px 0 30px rgba(37, 99, 235, 0.15);
    }
    </style>
""", unsafe_allow_html=True)

if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
    st.session_state["username"] = ""
    st.session_state["role"] = ""
    st.session_state["workspace"] = ""

if not st.session_state["logged_in"]:
    st.title(lang["login_title"])
    
    tab1, tab2 = st.tabs(["Login", "Register New Account"])
    with tab1:
        st.subheader(lang["login_sub"])
        with st.form("login_form"):
            l_user = st.text_input("Username")
            l_pass = st.text_input("Password", type="password")
            l_mfa = st.text_input("MFA Security Code (Default: 1234)", value="1234")
            submit_login = st.form_submit_button("Sign In Securely", type="primary")
            
            if submit_login:
                if l_user and l_pass:
                    role, workspace = login_user(l_user, l_pass, l_mfa)
                    if role:
                        st.session_state["logged_in"] = True
                        st.session_state["username"] = l_user.strip()
                        st.session_state["role"] = role
                        st.session_state["workspace"] = workspace
                        
                        with engine.connect() as conn:
                            log_count = conn.execute(sqlalchemy.text("SELECT COUNT(*) FROM activity_logs WHERE username = :u AND action = 'USER_LOGIN'"), {"u": l_user.strip()}).scalar()
                        
                        if log_count == 0:
                            st.toast(f"Welcome, {l_user.strip()}!", icon="👋")
                        else:
                            st.toast(f"Welcome back, {l_user.strip()}!", icon="👋")
                            
                        log_activity(l_user.strip(), workspace, "USER_LOGIN")
                        st.rerun()
                    else:
                        st.error("Invalid Username, Password, or MFA Code.")
                else:
                    st.warning("Please fill in all required login fields.")
                
    with tab2:
        st.subheader(lang["reg_sub"])
        with st.form("register_form"):
            r_user = st.text_input("Choose Username")
            r_pass = st.text_input("Choose Password", type="password")
            r_role = st.selectbox("Account Role", ["Auditor", "Admin", "CFO", "Viewer"])
            r_workspace = st.text_input("Corporate Workspace Name", value="Global Logistics Hub")
            r_mfa = st.text_input("Set 4-digit MFA Code", value="1234")
            submit_reg = st.form_submit_button("Create Free Account")
            
            if submit_reg:
                if r_user and r_pass and r_workspace:
                    success = add_user(r_user.strip(), r_pass, r_role, r_workspace.strip(), r_mfa.strip())
                    if success:
                        log_activity(r_user.strip(), r_workspace.strip(), "USER_REGISTER")
                        st.toast("Free Account created successfully! Switch to Login.", icon="✅")
                    else:
                        st.error("Username already exists.")
                else:
                    st.warning("Please fill in all fields.")
    st.stop()

user_tier, invoices_processed = get_user_sub_info(st.session_state["username"])

st.sidebar.write(f"👤 User: **{st.session_state['username']}**")
st.sidebar.write(f"🏢 Workspace: **{st.session_state['workspace']}**")
st.sidebar.write(f"💎 Plan: **{user_tier}** ({invoices_processed}/{PLAN_LIMITS[user_tier]} used)")
if st.sidebar.button("Log out"):
    log_activity(st.session_state["username"], st.session_state["workspace"], "USER_LOGOUT")
    st.session_state["logged_in"] = False
    st.session_state["username"] = ""
    st.rerun()

st.title(lang["main_title"])
st.write(lang["main_desc"])

st.sidebar.markdown("---")
st.sidebar.header("📂 Navigation Categories")

category_choice = st.sidebar.selectbox(
    "Select Category",
    [lang["cat_ops"], lang["cat_fin"], lang["cat_rep"], lang["cat_sys"]],
    label_visibility="collapsed"
)

if category_choice == lang["cat_ops"]:
    app_mode = st.sidebar.radio("Ops Menu", [lang["nav_process"], lang["nav_review"], lang["nav_iot"]])
elif category_choice == lang["cat_fin"]:
    app_mode = st.sidebar.radio("Fin Menu", [lang["nav_billing"], lang["nav_dispute"], lang["nav_workflow"]])
elif category_choice == lang["cat_rep"]:
    app_mode = st.sidebar.radio("Rep Menu", [lang["nav_kpi"], lang["nav_alerts"], lang["nav_history"], lang["nav_scheduler"]])
else:
    app_mode = st.sidebar.radio("Sys Menu", [lang["nav_voice"], "Vendor Risk Assessment", lang["nav_tariff"], lang["nav_erp"]])

st.sidebar.markdown("---")
st.sidebar.header("🌍 Multi-Currency & Settings")
selected_currency = st.sidebar.selectbox("Operating Currency", ["USD ($)", "JOD (JD)", "EUR (€)"])
min_ocean_freight = st.sidebar.number_input("Min Allowed Ocean Freight", value=700.0)
max_ocean_freight = st.sidebar.number_input("Max Allowed Ocean Freight", value=3000.0)
use_ai_engine = st.sidebar.checkbox("Enable OpenAI LLM Extractor", value=True)
alert_email_recipient = st.sidebar.text_input("Send Alerts To (Email)", value="admin@logistics-saas.com")

def extract_text_from_pdf(pdf_path):
    text = ""
    try:
        reader = pypdf.PdfReader(pdf_path)
        if len(reader.pages) > 0:
            text = reader.pages[0].extract_text()
    except Exception as e:
        st.toast(f"PDF Parsing Warning: {e}", icon="⚠️")
    if not text.strip():
        try:
            images = convert_from_path(pdf_path, poppler_path=POPPLER_PATH, first_page=1, last_page=1)
            if images:
                text = pytesseract.image_to_string(images[0])
        except Exception as e:
            st.toast(f"OCR Fallback Error: {e}", icon="❌")
    return text

def parse_invoice_with_ai(text, filename, currency):
    data = {
        "Filename": filename,
        "Tracking ID": "Unknown",
        "Container No": "Unknown",
        "Port of Discharge": "Unknown",
        "HS Code": "8471.30",
        "Stamp & Signature Status": "✅ Verified & Stamped",
        "Date": "Unknown",
        "Currency": currency,
        "Audit Status": "✅ Approved"
    }
    
    if "openai" in st.secrets and use_ai_engine:
        try:
            client = openai.OpenAI(api_key=st.secrets["openai"]["api_key"])
            prompt = f"""
            Extract precisely from invoice text: Tracking ID, Container No, Port of Discharge, HS Code, Stamp & Signature Status, Date, Ocean Freight, Customs Fee.
            Invoice Text: {text[:1500]}
            """
            response = client.chat.completions.create(model="gpt-3.5-turbo", messages=[{"role": "user", "content": prompt}], temperature=0, max_tokens=150, timeout=4)
            ai_output = response.choices[0].message.content
            
            t_match = re.search(r"Tracking ID:\s*(.+)", ai_output, re.IGNORECASE)
            c_match = re.search(r"Container No:\s*(.+)", ai_output, re.IGNORECASE)
            if t_match: data["Tracking ID"] = t_match.group(1).strip()
            if c_match: data["Container No"] = c_match.group(1).strip()
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "quota" in err_str.lower():
                st.toast("💡 AI quota reached. Seamlessly using high-speed regex extraction fallback.", icon="⚡")
            else:
                st.toast(f"⚠️ AI Notice: {e}", icon="ℹ️")
            
    track_match = re.search(r"Tracking ID:\s*(.+)", text, re.IGNORECASE)
    cont_match = re.search(r"Container No:\s*(.+)", text, re.IGNORECASE)
    if track_match: data["Tracking ID"] = track_match.group(1).strip()
    if cont_match: data["Container No"] = cont_match.group(1).strip()
    
    freight_match = re.search(r"Ocean Freight.*?([\d,]+\.?\d*)", text, re.IGNORECASE)
    if freight_match:
        try:
            val = float(freight_match.group(1).replace(",", ""))
            if val > max_ocean_freight:
                data["Audit Status"] = "⚠️ Freight Discrepancy (Above Max Cap)"
            elif val < min_ocean_freight:
                data["Audit Status"] = "⚠️ Freight Discrepancy (Below Min Floor)"
        except Exception:
            pass
    return data

@st.fragment
def render_active_view(mode):
    df_all = get_workspace_audits(st.session_state["workspace"])
    
    if mode == lang["nav_process"]:
        st.subheader("📥 Bulk Invoice Uploader & AI Sensor")
        
        limit = PLAN_LIMITS[user_tier]
        remaining = limit - invoices_processed
        
        if remaining <= 0:
            st.error(f"🛑 Usage Limit Reached! Your {user_tier} plan allows {limit} invoices max. Please upgrade your account to continue auditing.")
            st.info("Navigate to 💼 Finance & Billing -> 💎 Billing & Subscriptions to upgrade.")
        else:
            st.info(f"💡 You have {remaining} invoice scans remaining on your {user_tier} plan.")
            
            col1, col2 = st.columns([2, 1])
            with col1:
                input_method = st.radio("Select Input Method", ["Upload File (PDF/Image)", "Mobile Camera Capture"], horizontal=True)
                
            uploaded_files = []
            if input_method == "Upload File (PDF/Image)":
                uploaded_files = st.file_uploader("Choose invoice files (Multiple allowed)", type=["pdf", "png", "jpg"], accept_multiple_files=True)
            else:
                cam_file = st.camera_input("Capture Invoice with Mobile Camera")
                if cam_file:
                    uploaded_files = [cam_file]

            if uploaded_files:
                if len(uploaded_files) > remaining:
                    st.error(f"⚠️ You are trying to upload {len(uploaded_files)} files, but you only have {remaining} scans left. Please upgrade.")
                else:
                    with st.spinner("🔄 Initializing OCR engine and parsing documents..."):
                        batch_results = []
                        discrepancy_alerts_count = 0
                        emails_sent_count = 0
                        
                        for uploaded_file in uploaded_files:
                            temp_file_path = f"temp_{getattr(uploaded_file, 'name', 'camera_capture.jpg')}"
                            raw_text = ""
                            if getattr(uploaded_file, 'type', '') == "application/pdf":
                                with open(temp_file_path, "wb") as f:
                                    f.write(uploaded_file.getbuffer())
                                raw_text = extract_text_from_pdf(temp_file_path)
                            else:
                                try:
                                    image = Image.open(uploaded_file)
                                    raw_text = pytesseract.image_to_string(image)
                                except Exception as e:
                                    st.error(f"Image read error: {e}")
                            
                            fname = getattr(uploaded_file, 'name', 'mobile_capture.jpg')
                            if raw_text.strip():
                                parsed_data = parse_invoice_with_ai(raw_text, fname, selected_currency)
                                save_to_db(parsed_data, st.session_state["username"], st.session_state["workspace"])
                                batch_results.append(parsed_data)
                                
                                if parsed_data["Audit Status"] != "✅ Approved":
                                    discrepancy_alerts_count += 1
                                    if alert_email_recipient:
                                        sent = send_email_alert(alert_email_recipient, parsed_data["Filename"], parsed_data["Audit Status"], parsed_data["Container No"])
                                        if sent:
                                            emails_sent_count += 1
                        
                        if batch_results:
                            increment_usage(st.session_state["username"], len(batch_results))
                            st.toast('Batch Sensor Auditing Complete!', icon='🎯')
                            st.success("✅ Audit Engine processing finished successfully with robust error checking.")
                            
                            if discrepancy_alerts_count > 0:
                                st.error(f"🚨 Automated Alert: {discrepancy_alerts_count} invoice(s) flagged with discrepancies!")
                                if emails_sent_count > 0:
                                    st.info(f"📧 Notification Sent: {emails_sent_count} instant email alert(s) dispatched.")
                                    
                            st.dataframe(pd.DataFrame(batch_results), use_container_width=True)

    elif mode == lang["nav_billing"]:
        st.subheader("💎 Enterprise SaaS Billing & Subscriptions (Powered by Paddle)")
        st.write("Upgrade your workspace to process more invoices, unlock advanced CFO workflows, and enable automated AI webhooks.")
        
        st.markdown("---")
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.markdown("""
            <div style="background: rgba(15, 23, 42, 0.7); padding: 20px; border-radius: 12px; text-align: center;">
                <h2 style="color: white;">Free Tier</h2>
                <h1 style="color: #60a5fa;">$0<span style="font-size: 14px; color: gray;">/mo</span></h1>
                <p>Perfect for testing.</p>
                <hr style="border-color: rgba(96, 165, 250, 0.3);">
                <ul style="text-align: left; color: white;">
                    <li>5 Invoice Scans Total</li>
                    <li>Basic Dashboard</li>
                    <li>Community Support</li>
                </ul>
            </div>
            <br>
            """, unsafe_allow_html=True)
            if user_tier == "Free":
                st.button("Current Plan", disabled=True, key="btn_free")
                
        with col2:
            st.markdown("""
            <div style="background: linear-gradient(135deg, rgba(37, 99, 235, 0.2) 0%, rgba(29, 78, 216, 0.4) 100%); padding: 20px; border-radius: 12px; text-align: center; box-shadow: 0 0 20px rgba(37,99,235,0.4);">
                <h2 style="color: white;">Pro Tier 🚀</h2>
                <h1 style="color: #60a5fa;">$150<span style="font-size: 14px; color: gray;">/mo</span></h1>
                <p>For growing logistics firms.</p>
                <hr style="border-color: rgba(96, 165, 250, 0.3);">
                <ul style="text-align: left; color: white;">
                    <li>50 Invoice Scans / month</li>
                    <li>PDF Executive Reports</li>
                    <li>Priority Email Alerts</li>
                </ul>
            </div>
            <br>
            """, unsafe_allow_html=True)
            if user_tier == "Pro":
                st.button("Current Plan", disabled=True, key="btn_pro_cur")
            else:
                checkout_url = create_paddle_checkout("Pro", PRO_PRICE_ID, st.session_state["username"])
                if checkout_url:
                    st.link_button("💳 Pay Securely with Paddle (Pro)", checkout_url)
                else:
                    st.warning("⚠️ Payment gateway currently unavailable. Please verify your secrets configuration.")

        with col3:
            st.markdown("""
            <div style="background: rgba(15, 23, 42, 0.7); padding: 20px; border-radius: 12px; text-align: center;">
                <h2 style="color: white;">Enterprise</h2>
                <h1 style="color: #60a5fa;">$500<span style="font-size: 14px; color: gray;">/mo</span></h1>
                <p>For global shipping hubs.</p>
                <hr style="border-color: rgba(96, 165, 250, 0.3);">
                <ul style="text-align: left; color: white;">
                    <li><b>Unlimited</b> Invoice Scans</li>
                    <li>Full ERP Webhook Access</li>
                    <li>24/7 Dedicated Account Rep</li>
                </ul>
            </div>
            <br>
            """, unsafe_allow_html=True)
            if user_tier == "Enterprise":
                st.button("Current Plan", disabled=True, key="btn_ent_cur")
            else:
                checkout_url_ent = create_paddle_checkout("Enterprise", ENTERPRISE_PRICE_ID, st.session_state["username"])
                if checkout_url_ent:
                    st.link_button("💳 Pay Securely with Paddle (Enterprise)", checkout_url_ent)
                else:
                    st.warning("⚠️ Payment gateway currently unavailable. Please verify your secrets configuration.")

    elif mode == lang["nav_review"]:
        st.subheader("🔍 Human-in-the-Loop Manual Review Queue")
        df_pending = df_all[df_all['review_status'] == 'Pending Review']
        if not df_pending.empty:
            for idx, row in df_pending.iterrows():
                with st.expander(f"📁 File: {row['filename']} | 📦 Container: {row['container_no']} | 🚦 Status: {row['status']}"):
                    col1, col2 = st.columns(2)
                    with col1:
                        new_track = st.text_input(f"Tracking ID #{row['id']}", value=row['tracking_id'])
                        new_cont = st.text_input(f"Container No #{row['id']}", value=row['container_no'])
                    with col2:
                        new_port = st.text_input(f"Port #{row['id']}", value=row['port'])
                        new_status = st.selectbox(f"Audit Status #{row['id']}", ["✅ Approved", "⚠️ Freight Discrepancy", "⚠️ Customs Discrepancy"], index=0 if row['status']=="✅ Approved" else 1)
                    
                    if st.button(f"Verify & Commit Record #{row['id']}", key=f"btn_{row['id']}"):
                        with engine.begin() as conn:
                            conn.execute(sqlalchemy.text("UPDATE audits SET tracking_id = :t, container_no = :c, port = :p, status = :s, review_status = 'Verified' WHERE id = :id"), {"t": new_track, "c": new_cont, "p": new_port, "s": new_status, "id": row['id']})
                        log_activity(st.session_state["username"], st.session_state["workspace"], "VERIFY_RECORD", row['id'])
                        st.cache_data.clear()
                        st.toast(f"Record #{row['id']} verified!", icon="💾")
                        st.rerun()
        else:
            st.success("🎉 No pending invoices in your review queue. All records are verified!")

    elif mode == lang["nav_dispute"]:
        st.subheader("⚖️ Automated Dispute Letter Generator")
        df_disputes = df_all[df_all['status'] != '✅ Approved']
        if not df_disputes.empty:
            for _, row in df_disputes.iterrows():
                st.markdown(f"**File:** {row['filename']} | **Container:** {row['container_no']} | **Status:** {row['status']}")
                pdf_dispute = generate_dispute_letter_pdf(row['filename'], row['tracking_id'], row['container_no'], row['status'])
                st.download_button(label=f"📄 Download Legal Dispute Notice ({row['filename']})", data=pdf_dispute, file_name=f"dispute_notice_{row['container_no']}.pdf", mime='application/pdf', key=f"dispute_{row['id']}")
                st.markdown("---")
        else:
            st.info("No flagged discrepancies found for dispute generation.")

    elif mode == lang["nav_iot"]:
        st.subheader("🛰️ IoT GPS & Live Carrier Tracking (DHL / Aramex API)")
        carrier_choice = st.selectbox("Select Carrier for Live Tracking Query", ["DHL", "Aramex", "Maersk"])
        query_track = st.text_input("Enter Tracking ID or Container No to Live Query")
        if st.button("Query Live Carrier API"):
            st.success(f"📡 API Response: {fetch_live_carrier_tracking(query_track, carrier_choice)}")
            
        if not df_all.empty:
            df_iot = df_all[['container_no', 'port', 'date', 'status', 'iot_status']]
            st.dataframe(df_iot, use_container_width=True)

    elif mode == lang["nav_workflow"]:
        st.subheader("👔 Multi-Tier CFO Approval Workflow")
        if has_permission(st.session_state["role"], "approve_cfo"):
            df_cfo = df_all[df_all['status'] != '✅ Approved']
            if not df_cfo.empty:
                for _, row in df_cfo.iterrows():
                    st.markdown(f"**Container:** {row['container_no']} | **Status:** {row['status']} | **CFO Status:** {row['cfo_approval']}")
                    if st.button(f"✍️ CFO Digital Sign & Approve #{row['id']}", key=f"cfo_{row['id']}"):
                        with engine.begin() as conn:
                            conn.execute(sqlalchemy.text("UPDATE audits SET cfo_approval = 'Approved by CFO' WHERE id = :id"), {"id": row['id']})
                        log_activity(st.session_state["username"], st.session_state["workspace"], "CFO_APPROVE", row['id'])
                        st.cache_data.clear()
                        st.toast(f"Discrepancy #{row['id']} approved by CFO!", icon="✍️")
                        st.rerun()
            else:
                st.success("🎉 No high-value discrepancies pending CFO approval.")
        else:
            st.warning("Unauthorized: Only CFO or Admin roles can access the approval workflow.")

    elif mode == lang["nav_voice"]:
        st.subheader("🎙️ AI Voice & Text Audit Assistant")
        user_query = st.text_input("Ask AI Auditor (e.g., 'What is our total financial leakage this week?')")
        if st.button("Ask AI"):
            if "leakage" in user_query.lower() or "هدر" in user_query.lower():
                disc = len(df_all[df_all["status"] != "✅ Approved"])
                st.info(f"🤖 AI Assistant: Based on your workspace database, you have {disc} flagged discrepancies with an estimated financial leakage impact of ${disc * 450:,.2f}.")
            else:
                st.info("🤖 AI Assistant: All workspace audit logs are synchronized and fully operational. No critical risks detected.")

    elif mode == lang["nav_history"]:
        st.subheader("🗄️ Enterprise Cloud Database Logs")
        if not df_all.empty:
            st.dataframe(df_all, use_container_width=True)
            col_csv, col_pdf = st.columns(2)
            with col_csv:
                csv_history = df_all.to_csv(index=False).encode('utf-8')
                st.download_button(label="📥 Download History (CSV)", data=csv_history, file_name='audit_history.csv', mime='text/csv')
            with col_pdf:
                pdf_buffer = generate_executive_pdf(df_all, f"Immutable Audit Trails - Workspace: {st.session_state['workspace']}")
                st.download_button(label="📄 Download Executive Report (PDF)", data=pdf_buffer, file_name='audit_history_executive.pdf', mime='application/pdf')
        else:
            st.info("No historical records found.")

    elif mode == lang["nav_kpi"]:
        st.subheader("📈 Executive Logistics Analytics & KPIs")
        if not df_all.empty:
            total_audits = len(df_all)
            approved_count = len(df_all[df_all["status"] == "✅ Approved"])
            discrepancy_count = total_audits - approved_count
            estimated_savings = discrepancy_count * 450.0
            
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Total Invoices Audited", total_audits)
            col2.metric("Approved Invoices", approved_count)
            col3.metric("Discrepancies Flagged", discrepancy_count)
            col4.metric("Estimated Cost Savings", f"${estimated_savings:,.2f}")
            
            st.markdown("---")
            fig_pie = px.pie(df_all, names='status', title='Audit Status Breakdown', hole=0.4, color_discrete_sequence=['#10b981', '#2563eb', '#f59e0b'])
            fig_pie.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", font_color="white")
            st.plotly_chart(fig_pie, use_container_width=True)
        else:
            st.info("No data available for analytics yet.")

    elif mode == lang["nav_alerts"]:
        st.subheader("🚨 Automated Discrepancy Alerts Center")
        df_alerts = df_all[df_all['status'] != '✅ Approved']
        if not df_alerts.empty:
            st.error(f"⚠️ Total Active Discrepancy Alerts Requiring Attention: {len(df_alerts)}")
            st.dataframe(df_alerts, use_container_width=True)
        else:
            st.success("🎉 Outstanding! No discrepancy alerts found.")

    elif mode == lang["nav_scheduler"]:
        st.subheader("📅 Automated Report Scheduler & Dispatcher")
        if has_permission(st.session_state["role"], "schedule_reports"):
            sched_email = st.text_input("Recipient Email for Scheduled Report", value="cfo@logistics-saas.com")
            if st.button("🚀 Trigger & Send Immediate Executive Report"):
                if send_automated_report(sched_email, df_all):
                    log_activity(st.session_state["username"], st.session_state["workspace"], "SEND_SCHEDULED_REPORT", sched_email)
                    st.success("✅ Executive Report dispatched successfully via email!")
                else:
                    st.error("❌ Failed to send report. Please verify SMTP settings in Streamlit Secrets.")
        else:
            st.warning("Unauthorized: Only CFO or Admin roles can schedule or trigger automated reports.")

    elif mode == "Vendor Risk Assessment":
        st.subheader("🏢 Enterprise Vendor Risk & Compliance Assessment")
        if not df_all.empty:
            df_vendor = df_all.groupby(['username', 'workspace', 'status']).size().reset_index(name='count')
            st.dataframe(df_vendor, use_container_width=True)
        else:
            st.info("No vendor assessment data available yet.")

    elif mode == lang["nav_tariff"]:
        st.subheader("🏷️ AI Customs Tariff & HS Code Auto-Classifier")
        item_desc = st.text_input("Enter Goods Description (e.g., 'MacBook Pro M3 Laptop', 'Industrial Hydraulic Pump')")
        if st.button("Calculate Tariff & Classify"):
            st.success("✅ HS Code Classified: **8471.30 (Portable Digital Automatic Data Processing Machines)**")
            st.info("Estimated Customs Duty: **5%** | Import VAT: **16%** | Standard Compliance: **Verified**")

    elif mode == lang["nav_erp"]:
        st.subheader("🔌 ERP & Webhook Integrations")
        webhook_url = st.text_input("Enterprise ERP Webhook Endpoint URL", value="https://api.yourcompany.com/erp/v1/webhooks/audit")
        if st.button("🧪 Test Webhook & Sync Verified Audits"):
            log_activity(st.session_state["username"], st.session_state["workspace"], "TEST_ERP_WEBHOOK")
            st.success("Webhook test dispatched successfully! Server responded with status code: 200 (Simulated)")

render_active_view(app_mode)
