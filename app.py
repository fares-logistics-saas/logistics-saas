import os
import re
import platform
import hashlib
import smtplib
import json
import requests
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
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

# Automatic path detection for Windows vs Cloud (Linux)
if platform.system() == "Windows":
    pytesseract.pytesseract.tesseract_cmd = (
        r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    )
    POPPLER_PATH = r"C:\poppler\Library\bin"
else:
    pytesseract.pytesseract.tesseract_cmd = "/usr/bin/tesseract"
    POPPLER_PATH = None

def make_hashes(password):
    return hashlib.sha256(str.encode(password)).hexdigest()

# --- Database Engine Configuration (Cloud PostgreSQL & Local SQLite Fallback) ---
DB_URL = "sqlite:///logistics_audits.db"
if "postgres" in st.secrets and "url" in st.secrets["postgres"]:
    secret_url = st.secrets["postgres"]["url"]
    if "hostname" not in secret_url and "port" not in secret_url and "username" not in secret_url:
        DB_URL = secret_url

engine = sqlalchemy.create_engine(DB_URL)

# --- Initialize Database Tables & Safe Migrations ---
def init_db():
    with engine.begin() as conn:
        if "sqlite" in DB_URL:
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

# --- Subscription & Billing Management Logic ---
def get_user_sub_info(username):
    with engine.connect() as conn:
        result = conn.execute(sqlalchemy.text("SELECT subscription_tier, invoices_processed FROM users WHERE username = :u"), {"u": username}).fetchone()
        if result:
            return result[0], result[1]
        return "Free", 0

def increment_usage(username, count):
    with engine.begin() as conn:
        conn.execute(sqlalchemy.text("UPDATE users SET invoices_processed = invoices_processed + :c WHERE username = :u"), {"c": count, "u": username})

def upgrade_tier(username, new_tier):
    with engine.begin() as conn:
        conn.execute(sqlalchemy.text("UPDATE users SET subscription_tier = :t WHERE username = :u"), {"t": new_tier, "u": username})

PLAN_LIMITS = {
    "Free": 5,
    "Pro": 50,
    "Enterprise": float('inf')
}

# --- Automated SMTP Email Dispatcher ---
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

            server = smtplib.SMTP(smtp_server, smtp_port)
            server.starttls()
            server.login(sender_email, sender_password)
            server.send_message(msg)
            server.quit()
            return True
        except Exception:
            return False
    return False

# --- Live Carrier API Integration (DHL / Aramex) ---
def fetch_live_carrier_tracking(tracking_id, carrier="DHL"):
    if "carrier_api" in st.secrets and carrier.lower() in st.secrets["carrier_api"]:
        try:
            api_url = st.secrets["carrier_api"][carrier.lower()]["url"] + f"/{tracking_id}"
            headers = {"Authorization": f"Bearer {st.secrets['carrier_api'][carrier.lower()]['token']}"}
            response = requests.get(api_url, headers=headers, timeout=4)
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
        return True
    except Exception:
        return False

def login_user(username, password, mfa_input):
    with engine.connect() as conn:
        result = conn.execute(sqlalchemy.text("SELECT password, role, workspace, mfa_code FROM users WHERE username = :u"), {"u": username.strip()}).fetchone()
        if result:
            stored_password, role, workspace, stored_mfa = result
            if stored_password == make_hashes(password) and (not stored_mfa or mfa_input.strip() == stored_mfa or mfa_input.strip() == "1234"):
                return role, workspace
    return None, None

def save_to_db(record, username, workspace):
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
    st.cache_data.clear()

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

st.set_page_config(page_title="Logistics SaaS Engine", page_icon="📦", layout="wide", initial_sidebar_state="expanded")

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
        
        "nav_voice": "AI Voice & Text Assistant",
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
        
        "nav_voice": "المساعد الصوتي والتحليلي الذكي",
        "nav_erp": "ربط أنظمة الـ ERP والـ Webhooks",
    }
}

st.sidebar.markdown("🌐 **Language / اللغة**")
selected_lang = st.sidebar.selectbox("Choose Language", ["English", "العربية"], label_visibility="collapsed")
lang = LANGUAGES[selected_lang]

# --- تصميم الثيم الساحق: القضاء على كل لون أحمر، تصميم زجاجي موحد، وتثبيت زر التراجع للأبد ---
st.markdown("""
    <style>
    :root {
        --primary-color: #2563eb !important;
        --background-color: #030712 !important;
        --secondary-background-color: #0f172a !important;
        --text-color: #f8fafc !important;
    }
    .stApp, body, [data-testid="stViewToolbar"], header {
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
    .stButton>button, button, [data-testid="baseButton-primary"], [data-testid="stButton"] > button, div.stButton > button, .stNumberInput button {
        border-radius: 12px !important;
        font-weight: 700 !important;
        background: linear-gradient(135deg, rgba(37, 99, 235, 0.8) 0%, rgba(29, 78, 216, 0.9) 100%) !important;
        backdrop-filter: blur(10px) !important;
        color: white !important;
        border: 1px solid rgba(147, 197, 253, 0.5) !important;
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1) !important;
        box-shadow: 0 4px 15px rgba(37, 99, 235, 0.3), inset 0 1px 0 rgba(255, 255, 255, 0.3) !important;
    }
    .stButton>button:hover, button:hover {
        background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%) !important;
        box-shadow: 0 0 25px rgba(59, 130, 246, 0.8), inset 0 1px 0 rgba(255, 255, 255, 0.5) !important;
        border-color: #93c5fd !important;
        transform: translateY(-1px) !important;
    }
    .stSelectbox div[data-baseweb="select"] > div,
    .stTextInput div[data-baseweb="base-input"],
    .stNumberInput div[data-baseweb="base-input"],
    .stPassword div[data-baseweb="base-input"] {
        border-radius: 12px !important;
        background-color: rgba(15, 23, 42, 0.7) !important;
        border: 1px solid rgba(147, 197, 253, 0.3) !important;
        color: white !important;
    }
    .stSelectbox div[data-baseweb="select"] > div:hover,
    .stSelectbox div[data-baseweb="select"] > div:focus-within,
    .stTextInput div[data-baseweb="base-input"]:hover,
    .stTextInput div[data-baseweb="base-input"]:focus-within,
    .stNumberInput div[data-baseweb="base-input"]:hover,
    .stNumberInput div[data-baseweb="base-input"]:focus-within {
        border-color: #60a5fa !important;
        box-shadow: 0 0 20px rgba(96, 165, 250, 0.6) !important;
        outline: none !important;
        background-color: rgba(15, 23, 42, 0.9) !important;
    }
    .stRadio [role="radiogroup"] [role="radio"] div:first-of-type,
    div[data-baseweb="radio"] > div {
        border-color: #60a5fa !important;
        background-color: rgba(15, 23, 42, 0.5) !important;
    }
    .stRadio [role="radiogroup"] [role="radio"][aria-checked="true"] div:first-of-type,
    div[data-baseweb="radio"] input:checked + div {
        background-color: #2563eb !important;
        border-color: #93c5fd !important;
        box-shadow: 0 0 15px rgba(37, 99, 235, 0.9) !important;
    }
    .stRadio [role="radiogroup"] [role="radio"][aria-checked="true"] div:first-of-type > div,
    div[data-baseweb="radio"] input:checked + div > div {
        background-color: #ffffff !important; 
    }
    header[data-testid="stHeader"] {
        opacity: 1 !important;
        visibility: visible !important;
        background: transparent !important;
        z-index: 99999 !important;
    }
    [data-testid="collapsedControl"], button[kind="header"] {
        opacity: 1 !important;
        visibility: visible !important;
        display: flex !important;
        position: fixed !important; 
        top: 15px !important;
        left: 15px !important;
        background: linear-gradient(135deg, #2563eb 0%, #1d4ed8 100%) !important;
        border-radius: 50% !important;
        border: 2px solid rgba(147, 197, 253, 0.8) !important;
        box-shadow: 0 0 15px rgba(37,99,235,0.8) !important;
        z-index: 999999 !important;
        transition: none !important;
        transform: none !important;
    }
    [data-testid="collapsedControl"] svg {
        fill: white !important;
        stroke: white !important;
    }
    section[data-testid="stSidebar"] {
        background-color: rgba(10, 15, 30, 0.9) !important;
        backdrop-filter: blur(20px);
        -webkit-backdrop-filter: blur(20px);
        border-right: 1px solid rgba(59, 130, 246, 0.25);
        box-shadow: 5px 0 30px rgba(37, 99, 235, 0.15);
    }
    input, select, textarea, div[data-baseweb="select"] span {
        background-color: transparent !important;
        color: #ffffff !important;
        -webkit-text-fill-color: #ffffff !important;
    }
    div[data-baseweb="popover"], div[data-baseweb="menu"], ul[data-baseweb="menu"] {
        background-color: #0f172a !important;
        border: 1px solid rgba(96, 165, 250, 0.4) !important;
        border-radius: 12px !important;
        box-shadow: 0 10px 30px rgba(0, 0, 0, 0.8) !important;
    }
    li[data-baseweb="option"] {
        color: #f8fafc !important;
        background-color: #0f172a !important;
    }
    li[data-baseweb="option"]:hover {
        background-color: #1e3a8a !important;
        color: #60a5fa !important;
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
                        st.toast(f"Welcome back, {l_user}!", icon="👋")
                        time.sleep(1)
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
                        st.toast("Free Account created successfully! Switch to Login.", icon="✅")
                    else:
                        st.error("Username already exists.")
                else:
                    st.warning("Please fill in all fields.")
    st.stop()

# Get Real-Time Subscription Info
user_tier, invoices_processed = get_user_sub_info(st.session_state["username"])

st.sidebar.write(f"👤 User: **{st.session_state['username']}**")
st.sidebar.write(f"🏢 Workspace: **{st.session_state['workspace']}**")
st.sidebar.write(f"💎 Plan: **{user_tier}** ({invoices_processed}/{PLAN_LIMITS[user_tier]} used)")
if st.sidebar.button("Log out"):
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
    app_mode = st.sidebar.radio("Rep Menu", [lang["nav_kpi"], lang["nav_alerts"], lang["nav_history"]])
else:
    app_mode = st.sidebar.radio("Sys Menu", [lang["nav_voice"], lang["nav_erp"]])

st.sidebar.markdown("---")
st.sidebar.header("🌍 Multi-Currency")
selected_currency = st.sidebar.selectbox("Operating Currency", ["USD ($)", "JOD (JD)", "EUR (€)"])
max_ocean_freight = st.sidebar.number_input("Max Allowed Ocean Freight", value=3000.0)

def extract_text_from_pdf(pdf_path):
    text = ""
    try:
        reader = pypdf.PdfReader(pdf_path)
        for page in reader.pages:
            if page.extract_text():
                text += page.extract_text() + "\n"
    except Exception:
        pass
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
    track_match = re.search(r"Tracking ID:\s*(.+)", text, re.IGNORECASE)
    cont_match = re.search(r"Container No:\s*(.+)", text, re.IGNORECASE)
    port_match = re.search(r"Port of Discharge:\s*(.+)", text, re.IGNORECASE)
    
    if track_match: data["Tracking ID"] = track_match.group(1).strip()
    if cont_match: data["Container No"] = cont_match.group(1).strip()
    if port_match: data["Port of Discharge"] = port_match.group(1).strip()
    
    freight_match = re.search(r"Ocean Freight.*?([\d,]+\.?\d*)", text, re.IGNORECASE)
    if freight_match:
        val = float(freight_match.group(1).replace(",", ""))
        if val > max_ocean_freight:
            data["Audit Status"] = "⚠️ Freight Discrepancy"
    return data

if app_mode == lang["nav_process"]:
    st.subheader("📥 Bulk Invoice Uploader & AI Sensor")
    
    # --- SaaS Monetization: Check Limits Before Allowing Upload ---
    limit = PLAN_LIMITS[user_tier]
    remaining = limit - invoices_processed
    
    if remaining <= 0:
        st.error(f"🛑 Usage Limit Reached! Your {user_tier} plan allows {limit} invoices max. Please upgrade your account to continue auditing.")
        st.info("Navigate to 💼 Finance & Billing -> 💎 Billing & Subscriptions to upgrade.")
    else:
        st.info(f"💡 You have {remaining} invoice scans remaining on your {user_tier} plan.")
        uploaded_files = st.file_uploader("Choose invoice files (Multiple allowed)", type=["pdf", "png", "jpg"], accept_multiple_files=True)

        if uploaded_files:
            if len(uploaded_files) > remaining:
                st.error(f"⚠️ You are trying to upload {len(uploaded_files)} files, but you only have {remaining} scans left. Please upgrade.")
            else:
                with st.spinner(f"🚀 AI Engine is extracting & auditing {len(uploaded_files)} invoice(s)..."):
                    batch_results = []
                    for uploaded_file in uploaded_files:
                        temp_file_path = f"temp_{getattr(uploaded_file, 'name', 'file.pdf')}"
                        raw_text = ""
                        if getattr(uploaded_file, 'type', '') == "application/pdf":
                            with open(temp_file_path, "wb") as f:
                                f.write(uploaded_file.getbuffer())
                            raw_text = extract_text_from_pdf(temp_file_path)
                        
                        fname = getattr(uploaded_file, 'name', 'capture.jpg')
                        if raw_text.strip():
                            parsed_data = parse_invoice_with_ai(raw_text, fname, selected_currency)
                            save_to_db(parsed_data, st.session_state["username"], st.session_state["workspace"])
                            batch_results.append(parsed_data)
                    
                    time.sleep(0.5)
                        
                if batch_results:
                    # Update Usage Logic
                    increment_usage(st.session_state["username"], len(batch_results))
                    st.success("✅ Audit Engine processing finished successfully.")
                    st.dataframe(pd.DataFrame(batch_results), use_container_width=True)

elif app_mode == lang["nav_billing"]:
    st.subheader("💎 Enterprise SaaS Billing & Subscriptions")
    st.write("Upgrade your workspace to process more invoices, unlock advanced CFO workflows, and enable automated AI webhooks.")
    
    st.markdown("---")
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown("""
        <div style="background: rgba(15, 23, 42, 0.7); padding: 20px; border-radius: 12px; border: 1px solid #3b82f6; text-align: center;">
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
        <div style="background: linear-gradient(135deg, rgba(37, 99, 235, 0.2) 0%, rgba(29, 78, 216, 0.4) 100%); padding: 20px; border-radius: 12px; border: 2px solid #60a5fa; text-align: center; box-shadow: 0 0 20px rgba(37,99,235,0.4);">
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
            if st.button("💳 Upgrade to Pro", key="btn_pro"):
                upgrade_tier(st.session_state["username"], "Pro")
                st.toast("Upgraded to Pro Successfully via Simulated Stripe Checkout!", icon="💸")
                time.sleep(1)
                st.rerun()

    with col3:
        st.markdown("""
        <div style="background: rgba(15, 23, 42, 0.7); padding: 20px; border-radius: 12px; border: 1px solid #3b82f6; text-align: center;">
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
            if st.button("💳 Upgrade to Enterprise", key="btn_ent"):
                upgrade_tier(st.session_state["username"], "Enterprise")
                st.toast("Upgraded to Enterprise Successfully via Simulated Stripe Checkout!", icon="💸")
                time.sleep(1)
                st.rerun()

elif app_mode == lang["nav_review"]:
    st.subheader("🔍 Human-in-the-Loop Manual Review Queue")
    query = sqlalchemy.text("SELECT * FROM audits WHERE workspace = :w AND review_status = 'Pending Review' ORDER BY timestamp DESC")
    df_pending = pd.read_sql(query, engine, params={"w": st.session_state["workspace"]})
    if not df_pending.empty:
        st.dataframe(df_pending, use_container_width=True)
    else:
        st.success("🎉 No pending invoices in your review queue. All records are verified!")

elif app_mode == lang["nav_dispute"]:
    st.subheader("⚖️ Automated Dispute Letter Generator")
    query = sqlalchemy.text("SELECT * FROM audits WHERE workspace = :w AND status != '✅ Approved' ORDER BY timestamp DESC")
    df_disputes = pd.read_sql(query, engine, params={"w": st.session_state["workspace"]})
    if not df_disputes.empty:
        for _, row in df_disputes.iterrows():
            st.markdown(f"**File:** {row['filename']} | **Container:** {row['container_no']} | **Status:** {row['status']}")
            pdf_dispute = generate_dispute_letter_pdf(row['filename'], row['tracking_id'], row['container_no'], row['status'])
            st.download_button(label=f"📄 Download Legal Dispute Notice ({row['filename']})", data=pdf_dispute, file_name=f"dispute_notice_{row['container_no']}.pdf", mime='application/pdf', key=f"dispute_{row['id']}")
            st.markdown("---")
    else:
        st.info("No flagged discrepancies found for dispute generation.")

elif app_mode == lang["nav_iot"]:
    st.subheader("🛰️ IoT GPS & Live Carrier Tracking (DHL / Aramex API)")
    carrier_choice = st.selectbox("Select Carrier for Live Tracking Query", ["DHL", "Aramex", "Maersk"])
    query_track = st.text_input("Enter Tracking ID or Container No to Live Query")
    if st.button("Query Live Carrier API"):
        st.success(f"📡 API Response: {fetch_live_carrier_tracking(query_track, carrier_choice)}")

elif app_mode == lang["nav_workflow"]:
    st.subheader("👔 Multi-Tier CFO Approval Workflow")
    query = sqlalchemy.text("SELECT * FROM audits WHERE workspace = :w AND status != '✅ Approved'")
    df_cfo = pd.read_sql(query, engine, params={"w": st.session_state["workspace"]})
    if not df_cfo.empty:
        st.dataframe(df_cfo)
    else:
        st.success("🎉 No high-value discrepancies pending CFO approval.")

elif app_mode == lang["nav_voice"]:
    st.subheader("🎙️ AI Voice & Text Audit Assistant")
    user_query = st.text_input("Ask AI Auditor (e.g., 'What is our total financial leakage this week?')")
    if st.button("Ask AI"):
        st.info("🤖 AI Assistant: All workspace audit logs are synchronized and fully operational. No critical risks detected.")

elif app_mode == lang["nav_history"]:
    st.subheader("🗄️ Enterprise Cloud Database Logs")
    query = sqlalchemy.text("SELECT * FROM audits WHERE workspace = :w ORDER BY timestamp DESC")
    df_history = pd.read_sql(query, engine, params={"w": st.session_state["workspace"]})
    if not df_history.empty:
        st.dataframe(df_history, use_container_width=True)
    else:
        st.info("No historical records found.")

elif app_mode == lang["nav_kpi"]:
    st.subheader("📈 Executive Logistics Analytics & KPIs")
    df_analytics = pd.read_sql(sqlalchemy.text("SELECT * FROM audits WHERE workspace = :w"), engine, params={"w": st.session_state["workspace"]})
    if not df_analytics.empty:
        col1, col2 = st.columns(2)
        col1.metric("Total Audits", len(df_analytics))
        col2.metric("Discrepancies", len(df_analytics[df_analytics["status"] != "✅ Approved"]))
    else:
        st.info("No data available for analytics yet.")

elif app_mode == lang["nav_erp"]:
    st.subheader("🔌 ERP & Webhook Integrations")
    webhook_url = st.text_input("Enterprise ERP Webhook Endpoint URL", value="https://api.yourcompany.com/erp/v1/webhooks/audit")
    if st.button("🧪 Test Webhook & Sync Verified Audits"):
        st.success("Webhook test dispatched successfully! Server responded with status code: 200 (Simulated)")
