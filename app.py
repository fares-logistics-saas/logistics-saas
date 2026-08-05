import os
import re
import sqlite3
import platform
from PIL import Image
import pypdf
import pytesseract
from pdf2image import convert_from_path
import streamlit as st
import pandas as pd
import hashlib

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

# --- Initialize SQLite Database & Tables ---
def init_db():
    conn = sqlite3.connect("logistics_audits.db")
    cursor = conn.cursor()
    
    # Audits Table with username column
    cursor.execute("""
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
    """)
    
    # Users Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT,
            role TEXT
        )
    """)
    
    # Create default admin account if not exists (username: admin, password: password123)
    cursor.execute("SELECT * FROM users WHERE username = 'admin'")
    if not cursor.fetchone():
        hashed_pwd = make_hashes("password123")
        cursor.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)", ("admin", hashed_pwd, "Admin"))
        
    conn.commit()
    conn.close()

init_db()

def add_user(username, password, role="User"):
    conn = sqlite3.connect("logistics_audits.db")
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)", (username, make_hashes(password), role))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False

def login_user(username, password):
    conn = sqlite3.connect("logistics_audits.db")
    cursor = conn.cursor()
    cursor.execute("SELECT password, role FROM users WHERE username = ?", (username,))
    result = cursor.fetchone()
    conn.close()
    if result:
        stored_password, role = result
        if stored_password == make_hashes(password):
            return role
    return None

def save_to_db(record, username):
    conn = sqlite3.connect("logistics_audits.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO audits (filename, tracking_id, container_no, port, date, status, username)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (record["Filename"], record["Tracking ID"], record["Container No"], record["Port of Discharge"], record["Date"], record["Audit Status"], username))
    conn.commit()
    conn.close()

# Streamlit page configuration
st.set_page_config(
    page_title="Logistics Invoice Auditor", page_icon="📦", layout="wide"
)

# --- Authentication State Management ---
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
    st.session_state["username"] = ""
    st.session_state["role"] = ""

if not st.session_state["logged_in"]:
    st.title("🔐 Logistics SaaS - Secure Login")
    tab1, tab2 = st.tabs(["Login", "Register New Account"])
    
    with tab1:
        st.subheader("Login to your account")
        l_user = st.text_input("Username", key="login_user")
        l_pass = st.text_input("Password", type="password", key="login_pass")
        if st.button("Login"):
            role = login_user(l_user, l_pass)
            if role:
                st.session_state["logged_in"] = True
                st.session_state["username"] = l_user
                st.session_state["role"] = role
                st.success(f"Welcome back, {l_user}!")
                st.rerun()
            else:
                st.error("Invalid Username or Password")
                
    with tab2:
        st.subheader("Create a new corporate account")
        r_user = st.text_input("Choose Username", key="reg_user")
        r_pass = st.text_input("Choose Password", type="password", key="reg_pass")
        r_role = st.selectbox("Account Role", ["User", "Admin"])
        if st.button("Register"):
            if r_user and r_pass:
                success = add_user(r_user, r_pass, r_role)
                if success:
                    st.success("Account created successfully! Please switch to the Login tab.")
                else:
                    st.error("Username already exists. Please choose another.")
            else:
                st.warning("Please fill in all fields.")
    st.stop()

# --- Main App (Accessible only when logged in) ---
st.sidebar.write(f"👤 Logged in as: **{st.session_state['username']}** ({st.session_state['role']})")
if st.sidebar.button("Log out"):
    st.session_state["logged_in"] = False
    st.session_state["username"] = ""
    st.session_state["role"] = ""
    st.rerun()

st.title("📦 Logistics Invoice Auditor & Database Engine")
st.write(
    "Upload multiple logistics invoices for automated batch processing, contract auditing, and secure database logging."
)

# Sidebar for Contract Rules & Benchmarks
st.sidebar.header("📋 Contract Benchmark Rules")
max_ocean_freight = st.sidebar.number_input("Max Allowed Ocean Freight ($)", value=3000.0)
max_customs_fee = st.sidebar.number_input("Max Allowed Customs Fee (JOD)", value=700.0)

# Navigation
st.sidebar.markdown("---")
app_mode = st.sidebar.radio(
    "Navigation", 
    ["Process & Audit Invoices", "View Audit Database History", "Analytics & KPI Dashboard"]
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

def parse_invoice_data(text, filename):
    data = {
        "Filename": filename,
        "Tracking ID": "Not Found",
        "Container No": "Not Found",
        "Port of Discharge": "Not Found",
        "Date": "Not Found",
        "Audit Status": "✅ Approved"
    }
    
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
                parsed_data = parse_invoice_data(raw_text, uploaded_file.name)
                save_to_db(parsed_data, st.session_state["username"])
                batch_results.append(parsed_data)
                
        if batch_results:
            st.success("Batch Processing, Auditing & Secure Database Logging Complete!")
            st.subheader("📊 Consolidated Batch Audit Report")
            df_batch = pd.DataFrame(batch_results)
            st.dataframe(df_batch, use_container_width=True)
            
            csv_data = df_batch.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Download Consolidated Batch Report (CSV)",
                data=csv_data,
                file_name='batch_audit_report.csv',
                mime='text/csv',
            )

elif app_mode == "View Audit Database History":
    st.subheader("🗄️ Historical Audit Database Logs")
    conn = sqlite3.connect("logistics_audits.db")
    
    # Admins can see all logs, regular users see only their own logs
    if st.session_state["role"] == "Admin":
        df_history = pd.read_sql_query("SELECT * FROM audits ORDER BY timestamp DESC", conn)
        st.info("Showing all system audits (Admin View)")
    else:
        df_history = pd.read_sql_query("SELECT * FROM audits WHERE username = ? ORDER BY timestamp DESC", conn, params=(st.session_state["username"],))
        st.info(f"Showing audits for user: {st.session_state['username']}")
        
    conn.close()
    
    if not df_history.empty:
        st.dataframe(df_history, use_container_width=True)
        csv_history = df_history.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Download History (CSV)",
            data=csv_history,
            file_name='audit_history.csv',
            mime='text/csv',
        )
    else:
        st.info("No historical records found.")

elif app_mode == "Analytics & KPI Dashboard":
    st.subheader("📈 Executive Logistics Analytics & KPIs")
    conn = sqlite3.connect("logistics_audits.db")
    
    if st.session_state["role"] == "Admin":
        df_analytics = pd.read_sql_query("SELECT * FROM audits", conn)
    else:
        df_analytics = pd.read_sql_query("SELECT * FROM audits WHERE username = ?", conn, params=(st.session_state["username"],))
        
    conn.close()
    
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
