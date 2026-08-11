"""
UI module for Logistics SaaS Engine.

Contains Streamlit UI components, styling, templates, and HTML/CSS blocks.
Centralizes all presentation logic for consistent theming.
"""

from typing import Dict, Any, Tuple

import streamlit as st

from config import LANGUAGES


def get_styles_css() -> str:
    """
    Get the main CSS styles for the application.
    
    Returns:
        CSS string for injection into the page.
    """
    return """
    <style>
    /* 🔴 HIDDEN DEFAULT PAGE NAVIGATION 🔴 */
    [data-testid="stSidebarNav"] {
        display: none !important;
    }

    /* Hide the logo click trigger button (used for logo navigation) */
    button[data-testid="stBaseButton-secondary"]:has(p:empty),
    button[data-testid="stBaseButton-secondary"] p:empty {
        display: none !important;
    }
    [data-testid="stElementContainer"]:has(button[kind="secondary"] p:empty) {
        display: none !important;
        height: 0 !important;
        margin: 0 !important;
        padding: 0 !important;
        overflow: hidden !important;
    }

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
    
    /* Interactive custom container for sidebar logo button */
    .custom-logo-container {
        border-radius: 12px;
        background: linear-gradient(135deg, rgba(37, 99, 235, 0.8) 0%, rgba(29, 78, 216, 0.9) 100%);
        backdrop-filter: blur(10px);
        color: white;
        border: none;
        padding: 14px 16px;
        box-shadow: 0 4px 15px rgba(37, 99, 235, 0.3), inset 0 1px 0 rgba(255, 255, 255, 0.3);
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        text-align: center;
        cursor: pointer;
        margin-bottom: -0.5rem;
    }
    .custom-logo-container:hover {
        background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
        box-shadow: 0 0 25px rgba(59, 130, 246, 0.8), inset 0 1px 0 rgba(255, 255, 255, 0.5);
        transform: translateY(-1px);
    }

    .about-logo-container {
        width: 380px;
        margin: 0 auto 1.5rem auto;
        padding: 10px;
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
        cursor: pointer;
        display: block;
        transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    }
    .about-logo-container:hover {
        transform: scale(1.03);
        background: transparent !important;
        border: none !important;
        box-shadow: none !important;
    }
    .about-logo-container svg {
        transition: filter 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    }
    .about-logo-container:hover svg {
        filter: drop-shadow(0 0 15px rgba(59, 130, 246, 0.8)) drop-shadow(0 0 5px rgba(16, 185, 129, 0.6));
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
    """


def get_logo_html() -> str:
    """
    Get the sidebar logo HTML.
    
    Returns:
        HTML string for the logo component.
    """
    return """
<div style="text-decoration: none; display: block; margin-bottom: 1rem;">
    <div class="custom-logo-container">
        <div style="display: flex; align-items: center; justify-content: center;">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 120" width="100%" height="58">
                <defs>
                    <linearGradient id="primaryGradBtn" x1="0%" y1="0%" x2="100%" y2="100%">
                        <stop offset="0%" stop-color="#3b82f6" />
                        <stop offset="100%" stop-color="#1d4ed8" />
                    </linearGradient>
                    <linearGradient id="accentGradBtn" x1="0%" y1="0%" x2="100%" y2="0%">
                        <stop offset="0%" stop-color="#10b981" />
                        <stop offset="100%" stop-color="#059669" />
                    </linearGradient>
                </defs>
                <g transform="translate(10, -2) scale(1.15)">
                    <path d="M40 10 L70 25 L70 65 L40 80 L10 65 L10 25 Z" fill="none" stroke="url(#primaryGradBtn)" stroke-width="4" stroke-linejoin="round" />
                    <path d="M40 10 L40 50 M70 25 L40 50 L10 25" fill="none" stroke="url(#primaryGradBtn)" stroke-width="3" stroke-linejoin="round" opacity="0.6" />
                    <line x1="25" y1="42" x2="35" y2="47" stroke="#3b82f6" stroke-width="3" stroke-linecap="round" />
                    <line x1="45" y1="62" x2="55" y2="57" stroke="#3b82f6" stroke-width="3" stroke-linecap="round" />
                    <circle cx="55" cy="55" r="18" fill="#030712" stroke="#10b981" stroke-width="3" />
                    <path d="M47 55 L52 60 L63 48" fill="none" stroke="url(#accentGradBtn)" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" />
                </g>
                <text x="120" y="74" font-family="system-ui, -apple-system, sans-serif" font-size="30" font-weight="800" fill="#f8fafc">Logi<tspan fill="#3b82f6">Audit</tspan> <tspan font-size="18" font-weight="500" fill="#94a3b8">SaaS ENGINE</tspan></text>
            </svg>
        </div>
    </div>
</div>
"""


def get_about_page_html() -> str:
    """
    Get the about page HTML content.
    
    Returns:
        HTML string for the about page.
    """
    return """<div style="text-align: center; padding: 2rem 1rem 1rem 1rem;">
<div id="about-main-logo" class="about-logo-container" style="cursor: pointer;">
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 120" width="100%" height="100%">
<defs>
<linearGradient id="primaryGradBig" x1="0%" y1="0%" x2="100%" y2="100%">
<stop offset="0%" stop-color="#3b82f6" />
<stop offset="100%" stop-color="#1d4ed8" />
</linearGradient>
<linearGradient id="accentGradBig" x1="0%" y1="0%" x2="100%" y2="0%">
<stop offset="0%" stop-color="#10b981" />
<stop offset="100%" stop-color="#059669" />
</linearGradient>
</defs>
<g transform="translate(120, 4) scale(1.05)">
<path d="M40 10 L70 25 L70 65 L40 80 L10 65 L10 25 Z" fill="none" stroke="url(#primaryGradBig)" stroke-width="4" stroke-linejoin="round" />
<path d="M40 10 L40 50 M70 25 L40 50 L10 25" fill="none" stroke="url(#primaryGradBig)" stroke-width="3" stroke-linejoin="round" opacity="0.6" />
<line x1="25" y1="42" x2="35" y2="47" stroke="#3b82f6" stroke-width="3" stroke-linecap="round" />
<line x1="45" y1="62" x2="55" y2="57" stroke="#3b82f6" stroke-width="3" stroke-linecap="round" />
<circle cx="55" cy="55" r="18" fill="#030712" stroke="#10b981" stroke-width="3" />
<path d="M47 55 L52 60 L63 48" fill="none" stroke="url(#accentGradBig)" stroke-width="4" stroke-linecap="round" stroke-linejoin="round" />
</g>
<text x="160" y="108" font-family="system-ui, -apple-system, sans-serif" font-size="17" font-weight="800" fill="#f8fafc" text-anchor="middle">Logi<tspan fill="#3b82f6">Audit</tspan> <tspan font-size="11" font-weight="500" fill="#94a3b8">SaaS ENGINE</tspan></text>
</svg>
</div>
<h1 style="font-size: 2.5rem; font-weight: 800; color: #f8fafc; margin-bottom: 1rem;">Automated Logistics & Freight Auditing Engine</h1>
<p style="font-size: 1.1rem; color: #94a3b8; max-width: 750px; margin: 0 auto 3rem auto; line-height: 1.6;">
LogiAudit is an enterprise-grade SaaS platform designed to stop financial leakage in your supply chain. By leveraging AI-powered OCR and intelligent matching, we automatically audit your freight invoices, detect overcharges, and ensure compliance with your contracted rates.
</p>
</div>"""


def get_feature_card_html(title: str, description: str) -> str:
    """
    Generate HTML for a feature card.
    
    Args:
        title: The card title.
        description: The card description text.
        
    Returns:
        HTML string for the feature card.
    """
    return f"""
        <div style="background: rgba(15, 23, 42, 0.7); border: 1px solid rgba(59, 130, 246, 0.3); padding: 30px; border-radius: 16px; height: 100%; box-shadow: 0 10px 30px rgba(0,0,0,0.5);">
            <h3 style="color: #f8fafc; font-size: 1.25rem; font-weight: 700; margin-bottom: 1rem;">{title}</h3>
            <p style="color: #94a3b8; font-size: 0.95rem; line-height: 1.6;">
                {description}
            </p>
        </div>
    """


def get_pricing_card_html(
    title: str,
    price: str,
    period: str,
    goal: str,
    features: list,
    is_highlighted: bool = False,
    highlight_color: str = "#3b82f6"
) -> str:
    """
    Generate HTML for a pricing card.
    
    Args:
        title: Plan title.
        price: Price amount.
        period: Billing period.
        goal: Plan goal description.
        features: List of feature strings.
        is_highlighted: Whether this is a featured plan.
        highlight_color: Color for highlighted plan border.
        
    Returns:
        HTML string for the pricing card.
    """
    border_style = f"1px solid rgba({highlight_color.replace('#', '')}, 0.4)" if is_highlighted else "1px solid rgba(255, 255, 255, 0.1)"
    background = f"linear-gradient(135deg, rgba(37, 99, 235, 0.2) 0%, rgba(29, 78, 216, 0.4) 100%)" if is_highlighted else "rgba(15, 23, 42, 0.7)"
    box_shadow = "0 0 20px rgba(37,99,235,0.4)" if is_highlighted else "none"
    
    features_html = "\n".join([f"<li>{f}</li>" for f in features])
    
    return f"""
    <div style="background: {background}; padding: 20px; border-radius: 12px; text-align: center; border: {border_style}; box-shadow: {box_shadow};">
        <h2 style="color: white;">{title}</h2>
        <h1 style="color: #60a5fa;">{price}<span style="font-size: 14px; color: gray;">/{period}</span></h1>
        <p>{goal}</p>
        <hr style="border-color: rgba(96, 165, 250, 0.3);">
        <ul style="text-align: left; color: white;">
            {features_html}
        </ul>
    </div>
    <br>
    """


def get_category_and_radio_key(
    mode_name: str,
    lang_dict: Dict[str, str]
) -> Tuple[str, str]:
    """
    Get the category and radio key for a given mode name.
    
    Args:
        mode_name: The navigation mode name.
        lang_dict: The language dictionary for labels.
        
    Returns:
        Tuple of (category_name, radio_key).
    """
    ops_list = [lang_dict["nav_process"], lang_dict["nav_review"], lang_dict["nav_iot"]]
    fin_list = [lang_dict["nav_billing"], lang_dict["nav_dispute"], lang_dict["nav_workflow"]]
    rep_list = [lang_dict["nav_kpi"], lang_dict["nav_alerts"], lang_dict["nav_history"], lang_dict["nav_scheduler"]]
    sys_list = [lang_dict["nav_voice"], "Vendor Risk Assessment", lang_dict["nav_tariff"], lang_dict["nav_erp"]]
    
    if mode_name in ops_list:
        return lang_dict["cat_ops"], "radio_ops"
    elif mode_name in fin_list:
        return lang_dict["cat_fin"], "radio_fin"
    elif mode_name in rep_list:
        return lang_dict["cat_rep"], "radio_rep"
    elif mode_name in sys_list:
        return lang_dict["cat_sys"], "radio_sys"
    return lang_dict["cat_ops"], "radio_ops"


def get_logo_click_handler_js() -> str:
    """
    Get JavaScript for logo click handling.
    
    The logo container is made clickable to trigger navigation to the about page.
    This uses a hidden Streamlit button as a bridge since JavaScript cannot
    directly invoke Python code.
    
    Returns:
        HTML string with embedded JavaScript.
    """
    return """<div style='display:none;'><img src='x' onerror="setTimeout(()=>{
        let c=document.querySelector('.custom-logo-container');
        // Find the hidden button by its key attribute (rendered as data-testid or similar)
        let buttons=document.querySelectorAll('section[data-testid=stSidebar] button');
        let b=null;
        for(let btn of buttons){
            // Find button with empty or zero-width space content
            let txt=btn.textContent.trim();
            if(txt===''||txt==='\\u200B'){b=btn;break;}
        }
        if(b){
            let p=b.closest('[data-testid=\\'stElementContainer\\']');
            if(p){p.style.display='none';p.style.height='0';p.style.overflow='hidden';}
        }
        if(c&&b){c.style.cursor='pointer';c.onclick=()=>b.click();}
    },50);"></div>"""


def render_about_page() -> None:
    """Render the about/landing page."""
    st.markdown(get_about_page_html(), unsafe_allow_html=True)
    
    # JavaScript to make the about page logo clickable (triggers the dashboard button)
    st.markdown("""<div style='display:none;'><img src='x' onerror="setTimeout(function(){
        var aboutLogo=document.getElementById('about-main-logo');
        var dashBtn=document.querySelector('button[data-testid=stBaseButton-primary]');
        if(aboutLogo&&dashBtn){aboutLogo.style.cursor='pointer';aboutLogo.onclick=function(){dashBtn.click();};}
    },100);"></div>""", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown(get_feature_card_html(
            "🤖 AI-Powered Extraction",
            "Automatically extract tracking IDs, container numbers, and ocean freight costs from complex PDF invoices in seconds with zero manual data entry."
        ), unsafe_allow_html=True)
        
    with col2:
        st.markdown(get_feature_card_html(
            "💰 Financial Protection",
            "Instantly flag discrepancies where billed amounts exceed your master service agreement (MSA) caps. Stop paying for errors and overcharges."
        ), unsafe_allow_html=True)
        
    with col3:
        st.markdown(get_feature_card_html(
            "⚖️ Automated Disputes",
            "Generate legal-grade dispute notices instantly to request credit notes and chargebacks from vendors. Syncs seamlessly with CFO workflows."
        ), unsafe_allow_html=True)

    st.markdown("<br><br>", unsafe_allow_html=True)
    
    col_btn1, col_btn2, col_btn3 = st.columns([1, 2, 1])
    with col_btn2:
        if st.button("🚀 Enter Workspace Dashboard", use_container_width=True, type="primary"):
            st.session_state["view"] = "dashboard"
            st.session_state["restoring_dashboard"] = True
            st.rerun()
