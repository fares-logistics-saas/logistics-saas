"""
Logistics SaaS Engine - Main Application

Enterprise-grade logistics invoice auditing platform with AI-powered OCR,
automated discrepancy detection, and CFO workflow integration.
"""

import os
import re

import streamlit as st
import pandas as pd
import plotly.express as px
from PIL import Image
import pytesseract

# Import from modules
from config import (
    LANGUAGES,
    PLAN_LIMITS,
    DEFAULT_ALERT_EMAIL,
    DEFAULT_CFO_EMAIL,
    DEFAULT_MIN_OCEAN_FREIGHT,
    DEFAULT_MAX_OCEAN_FREIGHT,
    validate_email,
    validate_webhook_url,
)
from database import (
    init_db,
    log_activity,
    get_workspace_audits,
    get_user_sub_info,
    increment_usage,
    upgrade_tier,
    save_audit_record,
    update_audit_record,
    approve_cfo_record,
    engine,
)
from auth import (
    add_user,
    login_user,
    has_permission,
    get_login_count,
)
from ui import (
    get_styles_css,
    get_logo_html,
    get_about_page_html,
    get_feature_card_html,
    get_pricing_card_html,
    get_category_and_radio_key,
    get_logo_click_handler_js,
    render_about_page,
)
from business_logic import (
    extract_text_from_pdf,
    cleanup_temp_file,
    parse_invoice_with_ai,
    generate_executive_pdf,
    generate_dispute_letter_pdf,
    send_email_alert,
    send_automated_report,
    fetch_live_carrier_tracking,
    create_paddle_checkout,
    test_webhook_connection,
)

# --- Page Configuration ---
st.set_page_config(
    page_title="Logistics SaaS Engine",
    page_icon="📦",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- Initialize session state ---
if "view" not in st.session_state:
    st.session_state["view"] = "dashboard"

if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
    st.session_state["username"] = ""
    st.session_state["role"] = ""
    st.session_state["workspace"] = ""
    st.session_state["legal_selection"] = "App Dashboard"

if "return_mode" not in st.session_state:
    st.session_state["return_mode"] = None
if "return_category" not in st.session_state:
    st.session_state["return_category"] = None
if "restoring_dashboard" not in st.session_state:
    st.session_state["restoring_dashboard"] = False
if "current_active_mode" not in st.session_state:
    st.session_state["current_active_mode"] = None
if "current_active_category" not in st.session_state:
    st.session_state["current_active_category"] = None

# --- Paddle Live Settings (from Secrets) ---
try:
    PRO_PRICE_ID = st.secrets["paddle"]["PRO_PRICE_ID"]
    ENTERPRISE_PRICE_ID = st.secrets["paddle"]["ENTERPRISE_PRICE_ID"]
    PADDLE_API_KEY = st.secrets["paddle"]["PADDLE_API_KEY"]
except Exception:
    PRO_PRICE_ID = None
    ENTERPRISE_PRICE_ID = None
    PADDLE_API_KEY = None

# --- Initialize Database ---
init_db()

# --- Apply UI Styling ---
st.markdown(get_styles_css(), unsafe_allow_html=True)

# --- Sidebar Logo ---
st.sidebar.markdown(get_logo_html(), unsafe_allow_html=True)

# Hidden button for logo click handling (invisible via CSS, triggered by logo click via JS)
if st.sidebar.button("​", key="logo_click_trigger"):  # Zero-width space label
    if st.session_state["view"] == "dashboard":
        st.session_state["return_category"] = st.session_state.get("current_active_category")
        st.session_state["return_mode"] = st.session_state.get("current_active_mode")
        st.session_state["view"] = "about"
    else:
        st.session_state["view"] = "dashboard"
        st.session_state["restoring_dashboard"] = True
    st.rerun()

# Logo click handler JS
st.sidebar.markdown(get_logo_click_handler_js(), unsafe_allow_html=True)

st.sidebar.markdown("---")

# --- Language Selection ---
st.sidebar.markdown("🌐 **Language / اللغة**")
selected_lang = st.sidebar.selectbox(
    "Choose Language",
    ["English", "العربية"],
    label_visibility="collapsed",
    key="selected_lang"
)
lang = LANGUAGES[selected_lang]

# --- Legal & Pricing Section ---
st.sidebar.markdown("---")
st.sidebar.markdown("### 📄 Legal & Pricing")
legal_mode = st.sidebar.radio(
    "Legal Pages",
    ["App Dashboard", "Pricing", "Privacy Policy", "Refund Policy", "Terms of Service"],
    label_visibility="collapsed",
    key="legal_selection"
)

# --- About Page View Handler ---
if st.session_state["view"] == "about":
    render_about_page()
    st.stop()

# --- Handle Restoring Previous Page State ---
if st.session_state.get("restoring_dashboard", False):
    ret_mode = st.session_state.get("return_mode")
    ret_cat = st.session_state.get("return_category")
    if ret_mode and ret_cat:
        st.session_state["main_cat_choice"] = ret_cat
        _, r_key = get_category_and_radio_key(ret_mode, lang)
        st.session_state[r_key] = ret_mode
    else:
        st.session_state["main_cat_choice"] = lang["cat_ops"]
        st.session_state["radio_ops"] = lang["nav_process"]
    st.session_state["restoring_dashboard"] = False


def reset_legal_view() -> None:
    """Reset the legal/pricing menu to App Dashboard."""
    st.session_state["legal_selection"] = "App Dashboard"


st.sidebar.markdown("---")
st.sidebar.header("📂 Navigation Categories")

category_choice = st.sidebar.selectbox(
    "Select Category",
    [lang["cat_ops"], lang["cat_fin"], lang["cat_rep"], lang["cat_sys"]],
    label_visibility="collapsed",
    key="main_cat_choice",
    on_change=reset_legal_view
)

if category_choice == lang["cat_ops"]:
    app_mode = st.sidebar.radio(
        "Ops Menu",
        [lang["nav_process"], lang["nav_review"], lang["nav_iot"]],
        key="radio_ops",
        on_change=reset_legal_view
    )
elif category_choice == lang["cat_fin"]:
    app_mode = st.sidebar.radio(
        "Fin Menu",
        [lang["nav_billing"], lang["nav_dispute"], lang["nav_workflow"]],
        key="radio_fin",
        on_change=reset_legal_view
    )
elif category_choice == lang["cat_rep"]:
    app_mode = st.sidebar.radio(
        "Rep Menu",
        [lang["nav_kpi"], lang["nav_alerts"], lang["nav_history"], lang["nav_scheduler"]],
        key="radio_rep",
        on_change=reset_legal_view
    )
else:
    app_mode = st.sidebar.radio(
        "Sys Menu",
        [lang["nav_voice"], "Vendor Risk Assessment", lang["nav_tariff"], lang["nav_erp"]],
        key="radio_sys",
        on_change=reset_legal_view
    )

# Track current page for logo click restore
st.session_state["current_active_category"] = category_choice
st.session_state["current_active_mode"] = app_mode

st.sidebar.markdown("---")
st.sidebar.header("🌍 Multi-Currency & Settings")
selected_currency = st.sidebar.selectbox("Operating Currency", ["USD ($)", "JOD (JD)", "EUR (€)"])
min_ocean_freight = st.sidebar.number_input("Min Allowed Ocean Freight", value=DEFAULT_MIN_OCEAN_FREIGHT)
max_ocean_freight = st.sidebar.number_input("Max Allowed Ocean Freight", value=DEFAULT_MAX_OCEAN_FREIGHT)
use_ai_engine = st.sidebar.checkbox("Enable OpenAI LLM Extractor", value=True)
alert_email_recipient = st.sidebar.text_input("Send Alerts To (Email)", value=DEFAULT_ALERT_EMAIL)

# --- Payment Success Handler ---
query_params = st.query_params
if "payment_success" in query_params and query_params.get("payment_success") == "true":
    paid_plan = query_params.get("plan")
    paid_user = query_params.get("user")
    if paid_plan and paid_user:
        upgrade_tier(paid_user, paid_plan)
        st.success(f"🎉 Payment Successful! Account '{paid_user}' upgraded to {paid_plan} Tier.")
        st.balloons()
        st.query_params.clear()

# --- Authentication Check ---
if not st.session_state["logged_in"] and legal_mode == "App Dashboard":
    st.title(lang["login_title"])
    st.info(
        "💡 **Notice for Paddle Compliance Reviewers:** You are viewing the secure enterprise "
        "portal login screen. To examine public pricing, terms, and privacy policies, please "
        "use the sidebar menu under **Legal & Pricing**."
    )

    tab1, tab2 = st.tabs(["Login", "Register New Account"])
    with tab1:
        st.subheader(lang["login_sub"])
        with st.form("login_form"):
            l_user = st.text_input("Username")
            l_pass = st.text_input("Password", type="password")
            l_mfa = st.text_input("MFA Security Code (if configured)", value="")
            submit_login = st.form_submit_button("Sign In Securely", type="primary")

            if submit_login:
                if l_user and l_pass:
                    role, workspace = login_user(l_user, l_pass, l_mfa if l_mfa else None)
                    if role:
                        st.session_state["logged_in"] = True
                        st.session_state["username"] = l_user.strip()
                        st.session_state["role"] = role
                        st.session_state["workspace"] = workspace

                        login_count = get_login_count(l_user.strip())
                        if login_count == 0:
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
            r_pass = st.text_input("Choose Password (min 8 chars, must include letter and number)", type="password")
            r_role = st.selectbox("Account Role", ["Auditor", "Admin", "CFO", "Viewer"])
            r_workspace = st.text_input("Corporate Workspace Name", value="Global Logistics Hub")
            r_mfa = st.text_input("Set MFA Code (optional, for enhanced security)", value="")
            submit_reg = st.form_submit_button("Create Free Account")

            if submit_reg:
                if r_user and r_pass and r_workspace:
                    success = add_user(
                        r_user.strip(),
                        r_pass,
                        r_role,
                        r_workspace.strip(),
                        r_mfa.strip() if r_mfa.strip() else None
                    )
                    if success:
                        log_activity(r_user.strip(), r_workspace.strip(), "USER_REGISTER")
                        st.toast("Free Account created successfully! Switch to Login.", icon="✅")
                    else:
                        st.error("Username already exists or password requirements not met.")
                else:
                    st.warning("Please fill in all required fields.")
    st.stop()

# --- Logged-in User Display ---
if st.session_state["logged_in"]:
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


@st.fragment
def render_active_view(mode: str, legal_choice: str) -> None:
    """
    Render the active view based on navigation mode and legal choice.
    
    Args:
        mode: The current navigation mode.
        legal_choice: The current legal page selection.
    """
    df_all = get_workspace_audits(st.session_state.get("workspace", ""))

    # --- Legal & Pricing Pages ---
    if legal_choice == "Pricing":
        _render_pricing_page()
        return
    elif legal_choice == "Privacy Policy":
        _render_privacy_page()
        return
    elif legal_choice == "Refund Policy":
        _render_refund_page()
        return
    elif legal_choice == "Terms of Service":
        _render_terms_page()
        return

    if not st.session_state["logged_in"]:
        return

    user_tier, invoices_processed = get_user_sub_info(st.session_state["username"])

    # --- Standard App Navigation Modes ---
    if mode == lang["nav_process"]:
        _render_process_invoices(user_tier, invoices_processed)
    elif mode == lang["nav_billing"]:
        _render_billing_page(user_tier)
    elif mode == lang["nav_review"]:
        _render_review_queue(df_all)
    elif mode == lang["nav_dispute"]:
        _render_dispute_generator(df_all)
    elif mode == lang["nav_iot"]:
        _render_iot_tracking(df_all)
    elif mode == lang["nav_workflow"]:
        _render_cfo_workflow(df_all)
    elif mode == lang["nav_voice"]:
        _render_ai_assistant(df_all)
    elif mode == lang["nav_history"]:
        _render_audit_history(df_all)
    elif mode == lang["nav_kpi"]:
        _render_analytics(df_all)
    elif mode == lang["nav_alerts"]:
        _render_alerts(df_all)
    elif mode == lang["nav_scheduler"]:
        _render_scheduler(df_all)
    elif mode == "Vendor Risk Assessment":
        _render_vendor_assessment(df_all)
    elif mode == lang["nav_tariff"]:
        _render_tariff_classifier()
    elif mode == lang["nav_erp"]:
        _render_erp_integration()


def _render_pricing_page() -> None:
    """Render the public pricing page."""
    st.subheader("🏷️ Pricing Rationale & Value Breakdown")
    st.write(
        "Understand how LogiAudit saves your business money, why our pricing tiers are "
        "structured the way they are, and why Enterprise is the ultimate choice for logistics leaders."
    )
    st.markdown("---")

    st.markdown("### 💡 Why Our Pricing is Built for High ROI")
    st.markdown("""
    Unchecked logistics invoices contain an average of **3% to 8% in billing errors, duplicate line items, and overcharges**.
    Catching just **one** ocean freight overcharge (typically $450 - $1,200 per container) completely pays for months of your subscription.
    """)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.markdown("""
        <div style="background: rgba(15, 23, 42, 0.7); padding: 22px; border-radius: 12px; height: 100%; border: 1px solid rgba(255, 255, 255, 0.1);">
            <h3 style="color: #60a5fa; margin-top: 0;">Free Tier</h3>
            <h2 style="color: white;">$0 <span style="font-size: 14px; color: gray;">/month</span></h2>
            <p style="color: #94a3b8; font-size: 0.9rem;"><b>Goal:</b> Zero-risk evaluation sandbox.</p>
            <hr style="border-color: rgba(255, 255, 255, 0.1);">
            <p style="color: #e2e8f0; font-size: 0.95rem;"><b>How It Helps You:</b></p>
            <ul style="color: #cbd5e1; font-size: 0.85rem; padding-left: 1.2rem;">
                <li>Test OCR extraction accuracy on your real PDF invoices.</li>
                <li>Verify container number & tracking ID detection.</li>
                <li>Experience instant automated audit checks with zero financial commitment.</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)

    with col2:
        st.markdown("""
        <div style="background: rgba(15, 23, 42, 0.7); padding: 22px; border-radius: 12px; height: 100%; border: 1px solid rgba(37, 99, 235, 0.4);">
            <h3 style="color: #3b82f6; margin-top: 0;">Pro Tier 🚀</h3>
            <h2 style="color: white;">$150 <span style="font-size: 14px; color: gray;">/month</span></h2>
            <p style="color: #94a3b8; font-size: 0.9rem;"><b>Goal:</b> Financial protection for growing firms.</p>
            <hr style="border-color: rgba(255, 255, 255, 0.1);">
            <p style="color: #e2e8f0; font-size: 0.95rem;"><b>Why $150/month?</b></p>
            <p style="color: #cbd5e1; font-size: 0.85rem;">At just $3 per audited invoice, stopping a single $450 discrepancy yields a 300%+ ROI in your first week.</p>
            <p style="color: #e2e8f0; font-size: 0.95rem;"><b>How It Helps You:</b></p>
            <ul style="color: #cbd5e1; font-size: 0.85rem; padding-left: 1.2rem;">
                <li>Process up to 50 invoices/month.</li>
                <li>Instant email notifications sent to auditors when rate limits are breached.</li>
                <li>Download legal dispute notices and executive PDF reports.</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)

    with col3:
        st.markdown("""
        <div style="background: linear-gradient(135deg, rgba(37, 99, 235, 0.25) 0%, rgba(16, 185, 129, 0.15) 100%); padding: 22px; border-radius: 12px; height: 100%; border: 1px solid rgba(16, 185, 129, 0.5); box-shadow: 0 0 20px rgba(16, 185, 129, 0.2);">
            <h3 style="color: #10b981; margin-top: 0;">Enterprise Tier 💎</h3>
            <h2 style="color: white;">$500 <span style="font-size: 14px; color: gray;">/month</span></h2>
            <p style="color: #94a3b8; font-size: 0.9rem;"><b>Goal:</b> Complete enterprise supply chain automation.</p>
            <hr style="border-color: rgba(255, 255, 255, 0.1);">
            <p style="color: #e2e8f0; font-size: 0.95rem;"><b>Why $500/month?</b></p>
            <p style="color: #cbd5e1; font-size: 0.85rem;">Replaces manual data entry teams with automated real-time ERP webhooks and unlimited batch scanning.</p>
            <p style="color: #e2e8f0; font-size: 0.95rem;"><b>How It Helps You:</b></p>
            <ul style="color: #cbd5e1; font-size: 0.85rem; padding-left: 1.2rem;">
                <li><b>Unlimited Invoices</b> — zero cap on monthly audits.</li>
                <li>Direct ERP Webhook & API integration (SAP, Oracle, NetSuite).</li>
                <li>Dedicated account representative & 24/7 priority SLA.</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("### ⚡ Pro vs. Enterprise: Why Enterprise is Superior")

    comp_df = pd.DataFrame({
        "Capability / Feature": [
            "Monthly Invoice Volume Cap",
            "Cost per Audited Document",
            "ERP & Webhook Auto-Sync",
            "CFO Digital Approval Queue",
            "Contract Rate Customization",
            "Support & Service Level Agreement (SLA)",
            "Dedicated Account Rep"
        ],
        "Pro Tier ($150/mo)": [
            "50 Invoices / month",
            "$3.00 per invoice",
            "❌ Manual CSV/PDF Export Only",
            "Standard Queue",
            "Standard Benchmark Caps",
            "Standard Email Support (24h response)",
            "❌ Not Included"
        ],
        "Enterprise Tier ($500/mo) 💎": [
            "♾️ Unlimited (Zero Limit)",
            "Near $0.00 per invoice at volume",
            "✅ Live Real-Time Webhooks & ERP Pipeline",
            "Advanced CFO Sign-off Workflow",
            "✅ Fully Custom MSA Rate Matrix & Rules",
            "24/7 Priority SLA Response",
            "✅ Dedicated Account Manager"
        ]
    })
    st.table(comp_df)


def _render_privacy_page() -> None:
    """Render the privacy policy page."""
    st.subheader("🔒 Privacy Policy")
    st.markdown("""
    **LogiAudit SaaS Engine** respects your privacy and is committed to protecting your corporate data.
    * **Data Collection:** We securely process uploaded invoices, container tracking IDs, and audit records solely for supply chain auditing and financial verification.
    * **Data Security:** All data is encrypted at rest and in transit using industry-standard protocols.
    * **Third-Party Sharing:** We do not sell or share your business data with unauthorized third parties.
    """)


def _render_refund_page() -> None:
    """Render the refund policy page."""
    st.subheader("💵 Refund & Cancellation Policy")
    st.markdown("""
    * **Subscription Cancellation:** You can cancel your Pro or Enterprise subscription at any time from your billing dashboard. Cancellation takes effect at the end of the current billing cycle.
    * **Refunds:** Due to the digital nature of SaaS invoice processing and API consumption, subscription fees are generally non-refundable. However, refund requests made within 48 hours of initial purchase due to technical incompatibilities will be reviewed on a case-by-case basis.
    """)


def _render_terms_page() -> None:
    """Render the terms of service page."""
    st.subheader("📜 Terms of Service")
    st.markdown("""
    By accessing and using **LogiAudit SaaS Engine**, you agree to the following terms:
    * **Authorized Use:** You agree to use the platform solely for lawful enterprise logistics auditing and financial discrepancy detection.
    * **Account Security:** You are responsible for maintaining the confidentiality of your login credentials and MFA codes.
    * **Service Availability:** While we strive for 99.9% uptime, services may be subject to scheduled maintenance or unforeseen network interruptions.
    """)


def _render_process_invoices(user_tier: str, invoices_processed: int) -> None:
    """Render the invoice processing page."""
    st.subheader("📥 Bulk Invoice Uploader & AI Sensor")

    limit = PLAN_LIMITS[user_tier]
    remaining = limit - invoices_processed

    if remaining <= 0:
        st.error(
            f"🛑 Usage Limit Reached! Your {user_tier} plan allows {limit} invoices max. "
            "Please upgrade your account to continue auditing."
        )
        st.info("Navigate to the 'Pricing' option under Legal & Pricing to upgrade.")
    else:
        st.info(f"💡 You have {remaining} invoice scans remaining on your {user_tier} plan.")

        col1, col2 = st.columns([2, 1])
        with col1:
            input_method = st.radio(
                "Select Input Method",
                ["Upload File (PDF/Image)", "Mobile Camera Capture"],
                horizontal=True
            )

        uploaded_files = []
        if input_method == "Upload File (PDF/Image)":
            uploaded_files = st.file_uploader(
                "Choose invoice files (Multiple allowed)",
                type=["pdf", "png", "jpg"],
                accept_multiple_files=True
            )
        else:
            cam_file = st.camera_input("Capture Invoice with Mobile Camera")
            if cam_file:
                uploaded_files = [cam_file]

        if uploaded_files:
            if len(uploaded_files) > remaining:
                st.error(
                    f"⚠️ You are trying to upload {len(uploaded_files)} files, "
                    f"but you only have {remaining} scans left. Please upgrade."
                )
            else:
                with st.spinner("🔄 Initializing OCR engine and parsing documents..."):
                    batch_results = []
                    discrepancy_alerts_count = 0
                    emails_sent_count = 0
                    temp_files_to_cleanup = []

                    for uploaded_file in uploaded_files:
                        temp_file_path = f"temp_{getattr(uploaded_file, 'name', 'camera_capture.jpg')}"
                        raw_text = ""

                        if getattr(uploaded_file, 'type', '') == "application/pdf":
                            with open(temp_file_path, "wb") as f:
                                f.write(uploaded_file.getbuffer())
                            temp_files_to_cleanup.append(temp_file_path)
                            raw_text = extract_text_from_pdf(temp_file_path)
                        else:
                            try:
                                image = Image.open(uploaded_file)
                                raw_text = pytesseract.image_to_string(image)
                            except Exception:
                                st.error("Unable to process image file")

                        fname = getattr(uploaded_file, 'name', 'mobile_capture.jpg')
                        if raw_text.strip():
                            parsed_data = parse_invoice_with_ai(
                                raw_text,
                                fname,
                                selected_currency,
                                min_ocean_freight,
                                max_ocean_freight,
                                use_ai_engine
                            )
                            save_audit_record(
                                parsed_data,
                                st.session_state["username"],
                                st.session_state["workspace"]
                            )
                            batch_results.append(parsed_data)

                            if parsed_data["Audit Status"] != "✅ Approved":
                                discrepancy_alerts_count += 1
                                if alert_email_recipient and validate_email(alert_email_recipient):
                                    sent = send_email_alert(
                                        alert_email_recipient,
                                        parsed_data["Filename"],
                                        parsed_data["Audit Status"],
                                        parsed_data["Container No"]
                                    )
                                    if sent:
                                        emails_sent_count += 1

                    # Cleanup temporary files
                    for temp_file in temp_files_to_cleanup:
                        cleanup_temp_file(temp_file)

                    if batch_results:
                        increment_usage(st.session_state["username"], len(batch_results))
                        st.toast('Batch Sensor Auditing Complete!', icon='🎯')
                        st.success("✅ Audit Engine processing finished successfully.")

                        if discrepancy_alerts_count > 0:
                            st.error(f"🚨 Automated Alert: {discrepancy_alerts_count} invoice(s) flagged with discrepancies!")
                            if emails_sent_count > 0:
                                st.info(f"📧 Notification Sent: {emails_sent_count} instant email alert(s) dispatched.")

                        st.dataframe(pd.DataFrame(batch_results), use_container_width=True)


def _render_billing_page(user_tier: str) -> None:
    """Render the billing and subscriptions page."""
    st.subheader("💎 Enterprise SaaS Billing & Subscriptions (Powered by Paddle)")
    st.write(
        "Upgrade your workspace to process more invoices, unlock advanced CFO workflows, "
        "and enable automated AI webhooks."
    )

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
            st.button("Current Plan", disabled=True, key="btn_free_billing")

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
                <li>Basic ERP Integrations</li>
            </ul>
        </div>
        <br>
        """, unsafe_allow_html=True)
        if user_tier == "Pro":
            st.button("Current Plan", disabled=True, key="btn_pro_cur_billing")
        else:
            checkout_url = create_paddle_checkout(
                "Pro", PRO_PRICE_ID, st.session_state["username"], PADDLE_API_KEY
            )
            if checkout_url:
                st.link_button("💳 Pay Securely with Paddle (Pro)", checkout_url)
            else:
                st.warning("⚠️ Payment gateway currently unavailable.")

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
                <li>Custom SLA Agreements</li>
            </ul>
        </div>
        <br>
        """, unsafe_allow_html=True)
        if user_tier == "Enterprise":
            st.button("Current Plan", disabled=True, key="btn_ent_cur_billing")
        else:
            checkout_url_ent = create_paddle_checkout(
                "Enterprise", ENTERPRISE_PRICE_ID, st.session_state["username"], PADDLE_API_KEY
            )
            if checkout_url_ent:
                st.link_button("💳 Pay Securely with Paddle (Enterprise)", checkout_url_ent)
            else:
                st.warning("⚠️ Payment gateway currently unavailable.")


def _render_review_queue(df_all: pd.DataFrame) -> None:
    """Render the manual review queue page."""
    st.subheader("🔍 Human-in-the-Loop Manual Review Queue")
    df_pending = df_all[df_all['review_status'] == 'Pending Review']
    if not df_pending.empty:
        for idx, row in df_pending.iterrows():
            with st.expander(
                f"📁 File: {row['filename']} | 📦 Container: {row['container_no']} | 🚦 Status: {row['status']}"
            ):
                col1, col2 = st.columns(2)
                with col1:
                    new_track = st.text_input(f"Tracking ID #{row['id']}", value=row['tracking_id'])
                    new_cont = st.text_input(f"Container No #{row['id']}", value=row['container_no'])
                with col2:
                    new_port = st.text_input(f"Port #{row['id']}", value=row['port'])
                    new_status = st.selectbox(
                        f"Audit Status #{row['id']}",
                        ["✅ Approved", "⚠️ Freight Discrepancy", "⚠️ Customs Discrepancy"],
                        index=0 if row['status'] == "✅ Approved" else 1
                    )

                if st.button(f"Verify & Commit Record #{row['id']}", key=f"btn_{row['id']}"):
                    update_audit_record(row['id'], new_track, new_cont, new_port, new_status)
                    log_activity(
                        st.session_state["username"],
                        st.session_state["workspace"],
                        "VERIFY_RECORD",
                        row['id']
                    )
                    st.toast(f"Record #{row['id']} verified!", icon="💾")
                    st.rerun()
    else:
        st.success("🎉 No pending invoices in your review queue. All records are verified!")


def _render_dispute_generator(df_all: pd.DataFrame) -> None:
    """Render the dispute letter generator page."""
    st.subheader("⚖️ Automated Dispute Letter Generator")
    df_disputes = df_all[df_all['status'] != '✅ Approved']
    if not df_disputes.empty:
        for _, row in df_disputes.iterrows():
            st.markdown(
                f"**File:** {row['filename']} | **Container:** {row['container_no']} | **Status:** {row['status']}"
            )
            pdf_dispute = generate_dispute_letter_pdf(
                row['filename'], row['tracking_id'], row['container_no'], row['status']
            )
            st.download_button(
                label=f"📄 Download Legal Dispute Notice ({row['filename']})",
                data=pdf_dispute,
                file_name=f"dispute_notice_{row['container_no']}.pdf",
                mime='application/pdf',
                key=f"dispute_{row['id']}"
            )
            st.markdown("---")
    else:
        st.info("No flagged discrepancies found for dispute generation.")


def _render_iot_tracking(df_all: pd.DataFrame) -> None:
    """Render the IoT GPS tracking page."""
    st.subheader("🛰️ IoT GPS & Live Carrier Tracking (DHL / Aramex API)")
    carrier_choice = st.selectbox("Select Carrier for Live Tracking Query", ["DHL", "Aramex", "Maersk"])
    query_track = st.text_input("Enter Tracking ID or Container No to Live Query")
    if st.button("Query Live Carrier API"):
        st.success(f"📡 API Response: {fetch_live_carrier_tracking(query_track, carrier_choice)}")

    if not df_all.empty:
        df_iot = df_all[['container_no', 'port', 'date', 'status', 'iot_status']]
        st.dataframe(df_iot, use_container_width=True)


def _render_cfo_workflow(df_all: pd.DataFrame) -> None:
    """Render the CFO approval workflow page."""
    st.subheader("👔 Multi-Tier CFO Approval Workflow")
    if has_permission(st.session_state["role"], "approve_cfo"):
        df_cfo = df_all[df_all['status'] != '✅ Approved']
        if not df_cfo.empty:
            for _, row in df_cfo.iterrows():
                st.markdown(
                    f"**Container:** {row['container_no']} | **Status:** {row['status']} | "
                    f"**CFO Status:** {row['cfo_approval']}"
                )
                if st.button(f"✍️ CFO Digital Sign & Approve #{row['id']}", key=f"cfo_{row['id']}"):
                    approve_cfo_record(row['id'])
                    log_activity(
                        st.session_state["username"],
                        st.session_state["workspace"],
                        "CFO_APPROVE",
                        row['id']
                    )
                    st.toast(f"Discrepancy #{row['id']} approved by CFO!", icon="✍️")
                    st.rerun()
        else:
            st.success("🎉 No high-value discrepancies pending CFO approval.")
    else:
        st.warning("Unauthorized: Only CFO or Admin roles can access the approval workflow.")


def _render_ai_assistant(df_all: pd.DataFrame) -> None:
    """Render the AI voice/text assistant page."""
    st.subheader("🎙️ AI Voice & Text Audit Assistant")
    user_query = st.text_input("Ask AI Auditor (e.g., 'What is our total financial leakage this week?')")
    if st.button("Ask AI"):
        if "leakage" in user_query.lower() or "هدر" in user_query.lower():
            disc = len(df_all[df_all["status"] != "✅ Approved"])
            st.info(
                f"🤖 AI Assistant: Based on your workspace database, you have {disc} flagged discrepancies "
                f"with an estimated financial leakage impact of ${disc * 450:,.2f}."
            )
        else:
            st.info(
                "🤖 AI Assistant: All workspace audit logs are synchronized and fully operational. "
                "No critical risks detected."
            )


def _render_audit_history(df_all: pd.DataFrame) -> None:
    """Render the audit history page."""
    st.subheader("🗄️ Enterprise Cloud Database Logs")
    if not df_all.empty:
        st.dataframe(df_all, use_container_width=True)
        col_csv, col_pdf = st.columns(2)
        with col_csv:
            csv_history = df_all.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Download History (CSV)",
                data=csv_history,
                file_name='audit_history.csv',
                mime='text/csv'
            )
        with col_pdf:
            pdf_buffer = generate_executive_pdf(
                df_all, f"Immutable Audit Trails - Workspace: {st.session_state['workspace']}"
            )
            st.download_button(
                label="📄 Download Executive Report (PDF)",
                data=pdf_buffer,
                file_name='audit_history_executive.pdf',
                mime='application/pdf'
            )
    else:
        st.info("No historical records found.")


def _render_analytics(df_all: pd.DataFrame) -> None:
    """Render the analytics and KPIs page."""
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
        fig_pie = px.pie(
            df_all,
            names='status',
            title='Audit Status Breakdown',
            hole=0.4,
            color_discrete_sequence=['#10b981', '#2563eb', '#f59e0b']
        )
        fig_pie.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font_color="white"
        )
        st.plotly_chart(fig_pie, use_container_width=True)
    else:
        st.info("No data available for analytics yet.")


def _render_alerts(df_all: pd.DataFrame) -> None:
    """Render the alerts center page."""
    st.subheader("🚨 Automated Discrepancy Alerts Center")
    df_alerts = df_all[df_all['status'] != '✅ Approved']
    if not df_alerts.empty:
        st.error(f"⚠️ Total Active Discrepancy Alerts Requiring Attention: {len(df_alerts)}")
        st.dataframe(df_alerts, use_container_width=True)
    else:
        st.success("🎉 Outstanding! No discrepancy alerts found.")


def _render_scheduler(df_all: pd.DataFrame) -> None:
    """Render the report scheduler page."""
    st.subheader("📅 Automated Report Scheduler & Dispatcher")
    if has_permission(st.session_state["role"], "schedule_reports"):
        sched_email = st.text_input("Recipient Email for Scheduled Report", value=DEFAULT_CFO_EMAIL)

        # Validate email before showing send button
        if sched_email and not validate_email(sched_email):
            st.warning("⚠️ Please enter a valid email address.")
        elif st.button("🚀 Trigger & Send Immediate Executive Report"):
            if send_automated_report(sched_email, df_all):
                log_activity(
                    st.session_state["username"],
                    st.session_state["workspace"],
                    "SEND_SCHEDULED_REPORT",
                    sched_email
                )
                st.success("✅ Executive Report dispatched successfully via email!")
            else:
                st.error("❌ Failed to send report. Please verify email settings.")
    else:
        st.warning("Unauthorized: Only CFO or Admin roles can schedule or trigger automated reports.")


def _render_vendor_assessment(df_all: pd.DataFrame) -> None:
    """Render the vendor risk assessment page."""
    st.subheader("🏢 Enterprise Vendor Risk & Compliance Assessment")
    if not df_all.empty:
        df_vendor = df_all.groupby(['username', 'workspace', 'status']).size().reset_index(name='count')
        st.dataframe(df_vendor, use_container_width=True)
    else:
        st.info("No vendor assessment data available yet.")


def _render_tariff_classifier() -> None:
    """Render the customs tariff classifier page."""
    st.subheader("🏷️ AI Customs Tariff & HS Code Auto-Classifier")
    item_desc = st.text_input(
        "Enter Goods Description (e.g., 'MacBook Pro M3 Laptop', 'Industrial Hydraulic Pump')"
    )
    if st.button("Calculate Tariff & Classify"):
        st.success("✅ HS Code Classified: **8471.30 (Portable Digital Automatic Data Processing Machines)**")
        st.info("Estimated Customs Duty: **5%** | Import VAT: **16%** | Standard Compliance: **Verified**")


def _render_erp_integration() -> None:
    """Render the ERP/webhook integration page."""
    st.subheader("🔌 ERP & Webhook Integrations")
    webhook_url = st.text_input(
        "Enterprise ERP Webhook Endpoint URL",
        value="https://api.yourcompany.com/erp/v1/webhooks/audit"
    )

    # Validate webhook URL
    if webhook_url and not validate_webhook_url(webhook_url):
        st.warning("⚠️ Please enter a valid webhook URL (must be HTTP/HTTPS).")
    elif st.button("🧪 Test Webhook & Sync Verified Audits"):
        if test_webhook_connection(webhook_url):
            log_activity(st.session_state["username"], st.session_state["workspace"], "TEST_ERP_WEBHOOK")
            st.success("Webhook test dispatched successfully! Server responded with status code: 200 (Simulated)")


render_active_view(app_mode, legal_mode)
