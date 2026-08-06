import os
import re
import platform
import hashlib
import smtplib
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

# --- Database Engine Configuration ---
if "postgres" in st.secrets and "url" in st.secrets["postgres"]:
    DB_URL = st.secrets["postgres"]["url"]
else:
    DB_URL = "sqlite:///logistics_audits.db"

engine = sqlalchemy.create_engine(DB_URL)

# --- Initialize Database Tables Permanently ---
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
                    date TEXT,
                    status TEXT,
                    username TEXT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(sqlalchemy.text("""
                CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    password TEXT,
                    role TEXT
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
                    date TEXT,
                    status TEXT,
                    username TEXT,
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
            conn.execute(sqlalchemy.text("""
                CREATE TABLE IF NOT EXISTS users (
                    username TEXT PRIMARY KEY,
                    password TEXT,
                    role TEXT
                )
            """))
        
        result = conn.execute(sqlalchemy.text("SELECT * FROM users WHERE username = 'admin'")).fetchone()
        if not result:
            hashed_pwd = make_hashes("password123")
            conn.execute(sqlalchemy.text("INSERT INTO users (username, password, role) VALUES (:u, :p, :r)"),
                         {"u": "admin", "p": hashed_pwd, "r": "Admin"})

init_db()

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

            Best regards,
            Logistics SaaS Automated Audit Engine
            """
            msg.attach(MIMEText(body, 'plain'))

            server = smtplib.SMTP(smtp_server, smtp_port)
            server.starttls()
            server.login(sender_email, sender_password)
            server.send_message(msg)
            server.quit()
            return True
        except Exception as e:
            print(f"Email Dispatch Failed: {e}")
            return False
    return False

def add_user(username, password, role="User"):
    try:
        with engine.begin() as conn:
            conn.execute(sqlalchemy.text("INSERT INTO users (username, password, role) VALUES (:u, :p, :r)"),
                         {"u": username, "p": make_hashes(password), "r": role})
        return True
    except Exception:
        return False

def login_user(username, password):
    with engine.connect() as conn:
        result = conn.execute(sqlalchemy.text("SELECT password, role FROM users WHERE username = :u"), {"u": username.strip()}).fetchone()
        if result:
            stored_password, role = result
            if stored_password == make_hashes(password):
                return role
    return None

def save_to_db(record, username):
    with engine.begin() as conn:
        conn.execute(sqlalchemy.text("""
            INSERT INTO audits (filename, tracking_id, container_no, port, date, status, username)
            VALUES (:f, :t, :c, :p, :d, :s, :u)
        """), {
            "f": record["Filename"],
            "t": record["Tracking ID"],
            "c": record["Container No"],
            "p": record["Port of Discharge"],
            "d": record["Date"],
            "s": record["Audit Status"],
            "u": username
        })

def generate_executive_pdf(df, title_text):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    elements = []
    
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'ExecutiveTitle',
        parent=styles['Heading1'],
        fontSize=18,
        textColor=colors.HexColor('#1f2937'),
        spaceAfter=12,
        alignment=1
    )
    
    subtitle_style = ParagraphStyle(
        'ExecutiveSubtitle',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor('#4b5563'),
        spaceAfter=20,
        alignment=1
    )
    
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

st.set_page_config(
    page_title="Logistics Invoice Auditor", page_icon="📦", layout="wide"
)

# --- Authentication State Management ---
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
    st.session_state["username"] = ""
    st.session_state["role"] = ""

if not st.session_state["logged_in"]:
    st.title("🔐 Logistics SaaS - Secure Enterprise Login")
    tab1, tab2 = st.tabs(["Login", "Register New Account"])
    
    with tab1:
        st.subheader("Login to your account")
        l_user = st.text_input("Username", key="login_user")
        l_pass = st.text_input("Password", type="password", key="login_pass")
        if st.button("Login", type="primary"):
            if l_user and l_pass:
                role = login_user(l_user, l_pass)
                if role:
                    st.session_state["logged_in"] = True
                    st.session_state["username"] = l_user.strip()
                    st.session_state["role"] = role
                    st.success(f"Welcome back, {l_user}!")
                    st.rerun()
                else:
                    st.error("Invalid Username or Password. Please check your credentials.")
            else:
                st.warning("Please enter both username and password.")
                
    with tab2:
        st.subheader("Create a new corporate account")
        r_user = st.text_input("Choose Username", key="reg_user")
        r_pass = st.text_input("Choose Password", type="password", key="reg_pass")
        r_role = st.selectbox("Account Role", ["User", "Admin"])
        if st.button("Register"):
            if r_user and r_pass:
                success = add_user(r_user.strip(), r_pass, r_role)
                if success:
                    st.success("Account created successfully! Please switch to the Login tab.")
                else:
                    st.error("Username already exists. Please choose another.")
            else:
                st.warning("Please fill in all fields.")
    st.stop()

# --- Main App Sidebar Configuration ---
st.sidebar.write(f"👤 Logged in as: **{st.session_state['username']}** ({st.session_state['role']})")
if st.sidebar.button("Log out"):
    st.session_state["logged_in"] = False
    st.session_state["username"] = ""
    st.session_state["role"] = ""
    st.rerun()

st.title("📦 Logistics Invoice Auditor & Database Engine")
st.write(
    "Upload multiple logistics invoices for automated batch processing, contract auditing, and secure enterprise database logging."
)

st.sidebar.header("📋 Contract Benchmark Rules")
max_ocean_freight = st.sidebar.number_input("Max Allowed Ocean Freight ($)", value=3000.0)
max_customs_fee = st.sidebar.number_input("Max Allowed Customs Fee (JOD)", value=700.0)

st.sidebar.markdown("---")
st.sidebar.header("🤖 AI Extraction Mode")
use_ai_engine = st.sidebar.checkbox("Enable OpenAI LLM Extractor", value=True)

st.sidebar.markdown("---")
st.sidebar.header("📧 Email Notifications")
alert_email_recipient = st.sidebar.text_input("Send Alerts To (Email)", value="admin@logistics-saas.com")

st.sidebar.markdown("---")
app_mode = st.sidebar.radio(
    "Navigation", 
    [
        "Process & Audit Invoices", 
        "View Audit Database History", 
        "Analytics & KPI Dashboard", 
        "🚨 Automated Alerts & Notifications",
        "🏢 Vendor Risk Assessment"
    ]
)

def extract_text_from_pdf(pdf_path):
    text = ""
    try:
        reader = pypdf.PdfReader(pdf_path)
        for page in reader.pages:
            extracted = page.extract_text()
            if extracted:
                text += extracted + "\n"
    except Exception:
        pass

    if not text.strip():
        try:
            images = convert_from_path(pdf_path, poppler_path=POPPLER_PATH)
            for image in images:
                text += pytesseract.image_to_string(image) + "\n"
        except Exception:
            pass
    return text

def parse_invoice_with_ai(text, filename):
    data = {
        "Filename": filename,
        "Tracking ID": "Not Found",
        "Container No": "Not Found",
        "Port of Discharge": "Not Found",
        "Date": "Not Found",
        "Audit Status": "✅ Approved"
    }
    
    if "openai" in st.secrets and use_ai_engine:
        try:
            client = openai.OpenAI(api_key=st.secrets["openai"]["api_key"])
            prompt = f"""
            You are an expert logistics auditor. Extract the following fields from the invoice text below:
            - Tracking ID
            - Container No
            - Port of Discharge
            - Date
            - Ocean Freight numeric value (if any)
            - Port Handling/Customs numeric value in JD/JOD (if any)

            Invoice Text:
            {text[:3000]}

            Return ONLY a valid string format like:
            Tracking ID: [value]
            Container No: [value]
            Port of Discharge: [value]
            Date: [value]
            Ocean Freight: [value]
            Customs Fee: [value]
            """
            response = client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[{"role": "user", "content": prompt}],
                temperature=0
            )
            ai_output = response.choices[0].message.content
            
            t_match = re.search(r"Tracking ID:\s*(.+)", ai_output, re.IGNORECASE)
            c_match = re.search(r"Container No:\s*(.+)", ai_output, re.IGNORECASE)
            p_match = re.search(r"Port of Discharge:\s*(.+)", ai_output, re.IGNORECASE)
            d_match = re.search(r"Date:\s*(.+)", ai_output, re.IGNORECASE)
            f_match = re.search(r"Ocean Freight:\s*\$?([\d,]+\.?\d*)", ai_output, re.IGNORECASE)
            cf_match = re.search(r"Customs Fee:\s*(?:JD)?\s*([\d,]+\.?\d*)", ai_output, re.IGNORECASE)
            
            if t_match: data["Tracking ID"] = t_match.group(1).strip()
            if c_match: data["Container No"] = c_match.group(1).strip()
            if p_match: data["Port of Discharge"] = p_match.group(1).strip()
            if d_match: data["Date"] = d_match.group(1).strip()
            
            if f_match:
                val = float(f_match.group(1).replace(",", ""))
                if val > max_ocean_freight:
                    data["Audit Status"] = "⚠️ Freight Discrepancy"
            if cf_match:
                val = float(cf_match.group(1).replace(",", ""))
                if val > max_customs_fee:
                    data["Audit Status"] = "⚠️ Customs Discrepancy"
            return data
        except Exception:
            pass
            
    track_match = re.search(r"Tracking ID:\s*(.+)", text, re.IGNORECASE)
    cont_match = re.search(r"Container No:\s*(.+)", text, re.IGNORECASE)
    port_match = re.search(r"Port of Discharge:\s*(.+)", text, re.IGNORECASE)
    date_match = re.search(r"Date:\s*(.+)", text, re.IGNORECASE)
    
    if track_match: data["Tracking ID"] = track_match.group(1).strip()
    if cont_match: data["Container No"] = cont_match.group(1).strip()
    if port_match: data["Port of Discharge"] = port_match.group(1).strip()
    if date_match: data["Date"] = date_match.group(1).strip()
    
    freight_match = re.search(r"Ocean Freight Charges.*?\$([\d,]+\.?\d*)", text, re.IGNORECASE)
    if freight_match:
        val = float(freight_match.group(1).replace(",", ""))
        if val > max_ocean_freight:
            data["Audit Status"] = "⚠️ Freight Discrepancy"
            
    customs_match = re.search(r"Port Handling.*?JD\s*([\d,]+\.?\d*)", text, re.IGNORECASE)
    if customs_match:
        val = float(customs_match.group(1).replace(",", ""))
        if val > max_customs_fee:
            data["Audit Status"] = "⚠️ Customs Discrepancy"
            
    return data

if app_mode == "Process & Audit Invoices":
    uploaded_files = st.file_uploader(
        "Choose invoice files (Multiple allowed)", type=["pdf", "png", "jpg", "jpeg"], accept_multiple_files=True
    )

    if uploaded_files:
        st.info(f"Processing {len(uploaded_files)} invoice(s) for user '{st.session_state['username']}'...")
        batch_results = []
        discrepancy_alerts_count = 0
        emails_sent_count = 0
        
        for uploaded_file in uploaded_files:
            temp_file_path = f"temp_{uploaded_file.name}"
            raw_text = ""
            
            if uploaded_file.type == "application/pdf":
                with open(temp_file_path, "wb") as f:
                    f.write(uploaded_file.getbuffer())
                raw_text = extract_text_from_pdf(temp_file_path)
            else:
                try:
                    image = Image.open(uploaded_file)
                    raw_text = pytesseract.image_to_string(image)
                except Exception:
                    pass
            
            if raw_text.strip():
                parsed_data = parse_invoice_with_ai(raw_text, uploaded_file.name)
                save_to_db(parsed_data, st.session_state["username"])
                batch_results.append(parsed_data)
                
                if parsed_data["Audit Status"] != "✅ Approved":
                    discrepancy_alerts_count += 1
                    if alert_email_recipient:
                        sent = send_email_alert(
                            recipient_email=alert_email_recipient,
                            filename=parsed_data["Filename"],
                            audit_status=parsed_data["Audit Status"],
                            container_no=parsed_data["Container No"]
                        )
                        if sent:
                            emails_sent_count += 1
                
        if batch_results:
            st.success("Batch Processing, Auditing & Cloud Database Logging Complete!")
            if discrepancy_alerts_count > 0:
                st.warning(f"🚨 Automated Alert: {discrepancy_alerts_count} invoice(s) flagged with discrepancies requiring financial review!")
                if emails_sent_count > 0:
                    st.info(f"📧 Notification Sent: {emails_sent_count} instant email alert(s) dispatched to '{alert_email_recipient}'.")
            else:
                st.info("✨ All processed invoices passed benchmark rules successfully.")
                
            st.subheader("📊 Consolidated Batch Audit Report")
            df_batch = pd.DataFrame(batch_results)
            st.dataframe(df_batch, use_container_width=True)
            
            col_csv, col_pdf = st.columns(2)
            with col_csv:
                csv_data = df_batch.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="📥 Download Batch Report (CSV)",
                    data=csv_data,
                    file_name='batch_audit_report.csv',
                    mime='text/csv',
                )
            with col_pdf:
                pdf_buffer = generate_executive_pdf(df_batch, f"Batch Processing Report for User: {st.session_state['username']}")
                st.download_button(
                    label="📄 Download Executive Report (PDF)",
                    data=pdf_buffer,
                    file_name='executive_audit_report.pdf',
                    mime='application/pdf',
                )

elif app_mode == "View Audit Database History":
    st.subheader("🗄️ Enterprise Cloud Database Logs")
    
    if st.session_state["role"] == "Admin":
        df_history = pd.read_sql("SELECT * FROM audits ORDER BY timestamp DESC", engine)
        st.info("Showing all system audits (Admin Enterprise View)")
    else:
        query = sqlalchemy.text("SELECT * FROM audits WHERE username = :u ORDER BY timestamp DESC")
        df_history = pd.read_sql(query, engine, params={"u": st.session_state["username"]})
        st.info(f"Showing audits for user: {st.session_state['username']}")
    
    if not df_history.empty:
        st.dataframe(df_history, use_container_width=True)
        col_csv, col_pdf = st.columns(2)
        with col_csv:
            csv_history = df_history.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Download History (CSV)",
                data=csv_history,
                file_name='audit_history.csv',
                mime='text/csv',
            )
        with col_pdf:
            pdf_buffer = generate_executive_pdf(df_history, "Full Audit Database History Report")
            st.download_button(
                label="📄 Download Executive Report (PDF)",
                data=pdf_buffer,
                file_name='audit_history_executive.pdf',
                mime='application/pdf',
            )
    else:
        st.info("No historical records found.")

elif app_mode == "Analytics & KPI Dashboard":
    st.subheader("📈 Executive Logistics Analytics & KPIs")
    
    if st.session_state["role"] == "Admin":
        df_analytics = pd.read_sql("SELECT * FROM audits", engine)
    else:
        query = sqlalchemy.text("SELECT * FROM audits WHERE username = :u")
        df_analytics = pd.read_sql(query, engine, params={"u": st.session_state["username"]})
        
    if not df_analytics.empty:
        total_audits = len(df_analytics)
        approved_count = len(df_analytics[df_analytics["status"] == "✅ Approved"])
        discrepancy_count = total_audits - approved_count
        
        col1, col2, col3 = st.columns(3)
        col1.metric("Total Invoices Audited", total_audits)
        col2.metric("Approved Invoices", approved_count)
        col3.metric("Discrepancies Flagged", discrepancy_count)
        
        st.markdown("---")
        st.subheader("Audit Status Distribution")
        status_counts = df_analytics["status"].value_counts()
        st.bar_chart(status_counts)
    else:
        st.info("No data available for analytics yet. Process some invoices first!")

elif app_mode == "🚨 Automated Alerts & Notifications":
    st.subheader("🚨 Automated Discrepancy Alerts Center")
    st.write("Review all flagged invoices and financial violations detected by the auditing engine.")
    
    if st.session_state["role"] == "Admin":
        query = sqlalchemy.text("SELECT * FROM audits WHERE status != '✅ Approved' ORDER BY timestamp DESC")
        df_alerts = pd.read_sql(query, engine)
        st.info("Showing system-wide discrepancy alerts (AdminView)")
    else:
        query = sqlalchemy.text("SELECT * FROM audits WHERE username = :u AND status != '✅ Approved' ORDER BY timestamp DESC")
        df_alerts = pd.read_sql(query, engine, params={"u": st.session_state["username"]})
        st.info(f"Showing discrepancy alerts for user: {st.session_state['username']}")
        
    if not df_alerts.empty:
        st.error(f"⚠️ Total Active Discrepancy Alerts Requiring Attention: {len(df_alerts)}")
        st.dataframe(df_alerts, use_container_width=True)
        
        col_csv, col_pdf = st.columns(2)
        with col_csv:
            csv_alerts = df_alerts.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Download Alerts Report (CSV)",
                data=csv_alerts,
                file_name='discrepancy_alerts.csv',
                mime='text/csv',
            )
        with col_pdf:
            pdf_buffer = generate_executive_pdf(df_alerts, "Executive Financial Discrepancies Report")
            st.download_button(
                label="📄 Download Executive Report (PDF)",
                data=pdf_buffer,
                file_name='discrepancy_alerts_executive.pdf',
                mime='application/pdf',
            )
    else:
        st.success("🎉 Outstanding! No discrepancy alerts found. All invoices comply with contract benchmarks.")

elif app_mode == "🏢 Vendor Risk Assessment":
    st.subheader("🏢 Enterprise Vendor Risk & Compliance Assessment")
    st.write("Analyze compliance history and auditing performance per user/vendor account.")
    
    if st.session_state["role"] == "Admin":
        df_vendor = pd.read_sql("SELECT username, status, COUNT(*) as count FROM audits GROUP BY username, status", engine)
    else:
        query = sqlalchemy.text("SELECT username, status, COUNT(*) as count FROM audits WHERE username = :u GROUP BY username, status")
        df_vendor = pd.read_sql(query, engine, params={"u": st.session_state["username"]})
        
    if not df_vendor.empty:
        st.dataframe(df_vendor, use_container_width=True)
        st.info("💡 High discrepancy ratios indicate higher financial risk from specific vendors or operational lines.")
    else:
        st.info("No vendor assessment data available yet.")
