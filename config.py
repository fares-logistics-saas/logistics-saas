"""
Configuration module for Logistics SaaS Engine.

Contains all application constants, environment settings, and configurable values.
Centralizes hardcoded values for easy maintenance and environment-specific deployment.
"""

import os
import platform
import secrets
import logging
from typing import Dict, Any

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# --- Platform-specific paths ---
if platform.system() == "Windows":
    TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
    POPPLER_PATH = r"C:\poppler\Library\bin"
else:
    TESSERACT_CMD = "/usr/bin/tesseract"
    POPPLER_PATH = None

# --- Database Configuration ---
DEFAULT_DB_URL = "sqlite:///logistics_audits.db"

# --- RBAC Permissions Matrix ---
PERMISSIONS: Dict[str, list] = {
    "Admin": ["all"],
    "CFO": ["view_reports", "approve_cfo", "view_history", "analytics", "schedule_reports"],
    "Auditor": ["process", "view_history", "iot", "tariff"],
    "Viewer": ["view_history", "analytics"]
}

# --- Subscription Plan Limits ---
PLAN_LIMITS: Dict[str, float] = {
    "Free": 5,
    "Pro": 50,
    "Enterprise": float('inf')
}

# --- Default Values ---
DEFAULT_WORKSPACE = "Default Corp"
DEFAULT_SUBSCRIPTION_TIER = "Free"
DEFAULT_IOT_STATUS = "GPS Active (On Schedule)"
DEFAULT_CFO_APPROVAL = "Pending CFO Sign-off"
DEFAULT_REVIEW_STATUS = "Pending Review"

# --- Email Configuration Defaults ---
DEFAULT_ALERT_EMAIL = os.environ.get("DEFAULT_ALERT_EMAIL", "admin@logistics-saas.com")
DEFAULT_CFO_EMAIL = os.environ.get("DEFAULT_CFO_EMAIL", "cfo@logistics-saas.com")

# --- API Endpoints ---
PADDLE_API_URL = "https://api.paddle.com/transactions"

# --- Audit Thresholds (can be overridden via environment) ---
DEFAULT_MIN_OCEAN_FREIGHT = float(os.environ.get("MIN_OCEAN_FREIGHT", "700.0"))
DEFAULT_MAX_OCEAN_FREIGHT = float(os.environ.get("MAX_OCEAN_FREIGHT", "3000.0"))

# --- Security Configuration ---
# Password hashing rounds for bcrypt (higher = more secure but slower)
BCRYPT_ROUNDS = 12

# Minimum password length
MIN_PASSWORD_LENGTH = 8


def generate_secure_password(length: int = 32) -> str:
    """
    Generate a cryptographically secure random password.
    
    Args:
        length: Length of the password to generate.
        
    Returns:
        A secure random password string.
    """
    return secrets.token_urlsafe(length)


def get_default_admin_password() -> str:
    """
    Get the default admin password from environment or generate a secure one.
    
    For production, the admin password should be set via environment variable
    ADMIN_DEFAULT_PASSWORD. If not set, a secure random password is generated
    and logged (for initial setup only).
    
    Returns:
        The admin password to use for initial setup.
    """
    env_password = os.environ.get("ADMIN_DEFAULT_PASSWORD")
    if env_password:
        return env_password
    
    # Generate a secure random password for first-time setup
    secure_password = generate_secure_password(24)
    logger.warning(
        "No ADMIN_DEFAULT_PASSWORD environment variable set. "
        "Generated secure admin password for initial setup. "
        "Please check server logs for the password and change it immediately after first login."
    )
    logger.info(f"Generated admin password: {secure_password}")
    return secure_password


# --- Validation Patterns ---
import re

# Email validation pattern (RFC 5322 simplified)
EMAIL_PATTERN = re.compile(
    r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
)

# Webhook URL validation pattern (must be HTTPS in production)
WEBHOOK_URL_PATTERN = re.compile(
    r'^https?://[a-zA-Z0-9.-]+(?:\.[a-zA-Z]{2,})+(?:/[^\s]*)?$'
)


def validate_email(email: str) -> bool:
    """
    Validate an email address format.
    
    Args:
        email: The email address to validate.
        
    Returns:
        True if the email format is valid, False otherwise.
    """
    if not email or not isinstance(email, str):
        return False
    return bool(EMAIL_PATTERN.match(email.strip()))


def validate_webhook_url(url: str) -> bool:
    """
    Validate a webhook URL format.
    
    Args:
        url: The webhook URL to validate.
        
    Returns:
        True if the URL format is valid, False otherwise.
    """
    if not url or not isinstance(url, str):
        return False
    return bool(WEBHOOK_URL_PATTERN.match(url.strip()))


# --- Language Configuration ---
LANGUAGES: Dict[str, Dict[str, str]] = {
    "English": {
        "login_title": "🔐 Enterprise SSO & MFA Secure Login",
        "login_sub": "Corporate Login with Multi-Factor Authentication",
        "reg_sub": "Create a new corporate account",
        "main_title": "📦 Logistics Invoice Auditor & Database Engine",
        "main_desc": "Upload multiple logistics invoices for automated high-speed batch processing, strict contract auditing, and secure enterprise database logging.",
        
        # Simplified navigation categories
        "cat_ops": "📥 Workflow",
        "cat_fin": "💼 Finance",
        "cat_rep": "📊 Reports",
        "cat_sys": "⚙️ Advanced",

        "nav_process": "Upload & Audit Invoices",
        "nav_review": "Review Queue",
        "nav_iot": "GPS & Live Tracking",
        
        "nav_billing": "💎 Billing & Subscriptions",
        "nav_dispute": "Dispute Generator",
        "nav_workflow": "CFO Approval",
        
        "nav_history": "Audit History",
        "nav_kpi": "Analytics & KPIs",
        "nav_alerts": "Alerts Center",
        "nav_scheduler": "Report Scheduler",
        
        "nav_voice": "AI Assistant",
        "nav_vendor": "Vendor Assessment",
        "nav_tariff": "Tariff Classifier",
        "nav_erp": "ERP & Webhooks",
    },
    "العربية": {
        "login_title": "🔐 تسجيل الدخول الآمن للمؤسسات (SSO & MFA)",
        "login_sub": "تسجيل الدخول المؤسسي مع المصادقة الثنائية",
        "reg_sub": "إنشاء حساب مؤسسي جديد",
        "main_title": "📦 محرك تدقيق فواتير الشحن وقاعدة البيانات",
        "main_desc": "قم برفع فواتير الشحن المتعددة للمعالجة الآلية السريعة، التدقيق الصارم، وحفظ السجلات في قاعدة البيانات السحابية.",
        
        # Simplified navigation categories
        "cat_ops": "📥 سير العمل",
        "cat_fin": "💼 الإدارة المالية",
        "cat_rep": "📊 التقارير",
        "cat_sys": "⚙️ متقدم",

        "nav_process": "رفع وتدقيق الفواتير",
        "nav_review": "قائمة المراجعة",
        "nav_iot": "التتبع المباشر (GPS)",
        
        "nav_billing": "💎 الفوترة والاشتراكات",
        "nav_dispute": "منشئ خطابات النزاع",
        "nav_workflow": "موافقات المدير المالي",
        
        "nav_history": "سجل التدقيق",
        "nav_kpi": "التحليلات والمؤشرات",
        "nav_alerts": "مركز التنبيهات",
        "nav_scheduler": "جدولة التقارير",
        
        "nav_voice": "المساعد الذكي",
        "nav_vendor": "تقييم الموردين",
        "nav_tariff": "محلل الرسوم الجمركية",
        "nav_erp": "ربط أنظمة الـ ERP",
    }
}
