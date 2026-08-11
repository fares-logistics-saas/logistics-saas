"""
Database module for Logistics SaaS Engine.

Handles all database operations including connection management, table initialization,
migrations, and CRUD operations for audits, users, and activity logs.
"""

import logging
from typing import Optional, Tuple, Any, Dict

import pandas as pd
import sqlalchemy
from sqlalchemy import text
import streamlit as st

from config import (
    DEFAULT_DB_URL,
    DEFAULT_WORKSPACE,
    DEFAULT_SUBSCRIPTION_TIER,
    DEFAULT_IOT_STATUS,
    DEFAULT_CFO_APPROVAL,
    DEFAULT_REVIEW_STATUS,
    logger,
)

# Module logger
db_logger = logging.getLogger(__name__)


@st.cache_resource
def get_db_engine() -> sqlalchemy.Engine:
    """
    Create and cache the database engine connection.
    
    Attempts to use PostgreSQL from Streamlit secrets, falls back to SQLite.
    
    Returns:
        SQLAlchemy Engine instance.
    """
    db_url = DEFAULT_DB_URL
    try:
        if "postgres" in st.secrets and "url" in st.secrets["postgres"]:
            secret_url = st.secrets["postgres"]["url"]
            if "hostname" not in secret_url and "port" not in secret_url and "username" not in secret_url:
                db_url = secret_url
    except Exception:
        db_logger.info("Using default SQLite database")
    
    return sqlalchemy.create_engine(db_url, pool_pre_ping=True)


# Global engine instance
engine = get_db_engine()


def _create_sqlite_tables(conn: sqlalchemy.Connection) -> None:
    """Create tables for SQLite database."""
    conn.execute(text("""
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
    # Note: mfa_code column is kept for backward compatibility but no longer has
    # a default value of '1234'. NULL means MFA is not configured for the user.
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT,
            role TEXT,
            workspace TEXT DEFAULT 'Default Corp',
            mfa_code TEXT,
            subscription_tier TEXT DEFAULT 'Free',
            invoices_processed INTEGER DEFAULT 0
        )
    """))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS activity_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            workspace TEXT,
            action TEXT,
            target_id TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """))


def _create_postgres_tables(conn: sqlalchemy.Connection) -> None:
    """Create tables for PostgreSQL database."""
    conn.execute(text("""
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
    # Note: mfa_code column is kept for backward compatibility but no longer has
    # a default value of '1234'. NULL means MFA is not configured for the user.
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password TEXT,
            role TEXT,
            workspace TEXT DEFAULT 'Default Corp',
            mfa_code TEXT,
            subscription_tier TEXT DEFAULT 'Free',
            invoices_processed INTEGER DEFAULT 0
        )
    """))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS activity_logs (
            id SERIAL PRIMARY KEY,
            username TEXT,
            workspace TEXT,
            action TEXT,
            target_id TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """))


def _run_migrations(eng: sqlalchemy.Engine) -> None:
    """
    Run database migrations to add new columns to existing tables.
    
    Args:
        eng: SQLAlchemy engine instance.
    """
    migrations = [
        "ALTER TABLE users ADD COLUMN workspace TEXT DEFAULT 'Default Corp'",
        "ALTER TABLE users ADD COLUMN mfa_code TEXT",
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
    
    for migration in migrations:
        try:
            with eng.begin() as conn:
                conn.execute(text(migration))
        except Exception as e:
            # Column already exists or other expected error during migration
            db_logger.debug(f"Migration skipped (likely already applied): {migration[:50]}...")


@st.cache_resource
def init_db() -> None:
    """
    Initialize database tables and run migrations.
    
    Creates all required tables if they don't exist and applies any pending
    schema migrations. Also creates default admin user if not present.
    """
    from auth import hash_password, get_default_admin_password
    
    db_url_str = str(engine.url)
    
    with engine.begin() as conn:
        if "sqlite" in db_url_str:
            _create_sqlite_tables(conn)
        else:
            _create_postgres_tables(conn)
    
    _run_migrations(engine)
    
    # Create default admin user if not exists
    with engine.begin() as conn:
        result = conn.execute(
            text("SELECT * FROM users WHERE username = 'admin'")
        ).fetchone()
        
        if not result:
            admin_password = get_default_admin_password()
            hashed_pwd = hash_password(admin_password)
            conn.execute(
                text("""
                    INSERT INTO users (username, password, role, workspace, mfa_code, subscription_tier) 
                    VALUES (:u, :p, :r, :w, :m, :s)
                """),
                {
                    "u": "admin",
                    "p": hashed_pwd,
                    "r": "Admin",
                    "w": "Global Logistics Hub",
                    "m": None,  # No default MFA - must be configured by user
                    "s": "Enterprise"
                }
            )
            db_logger.info("Default admin user created. Please change the password immediately.")


def log_activity(
    username: str,
    workspace: str,
    action: str,
    target_id: str = "N/A"
) -> None:
    """
    Log user activity to the activity_logs table.
    
    Args:
        username: The username performing the action.
        workspace: The workspace context.
        action: Description of the action performed.
        target_id: Optional identifier of the target object.
    """
    try:
        with engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO activity_logs (username, workspace, action, target_id)
                    VALUES (:u, :w, :a, :t)
                """),
                {"u": username, "w": workspace, "a": action, "t": str(target_id)}
            )
    except Exception as e:
        db_logger.error(f"Failed to log activity: {action}", exc_info=True)
        st.toast("⚠️ Activity logging temporarily unavailable", icon="⚠️")


@st.cache_data(ttl=60, show_spinner=False)
def get_workspace_audits(workspace: str) -> pd.DataFrame:
    """
    Retrieve all audit records for a specific workspace.
    
    Args:
        workspace: The workspace to filter audits by.
        
    Returns:
        DataFrame containing audit records, empty DataFrame if none found.
    """
    if not workspace:
        return pd.DataFrame()
    try:
        return pd.read_sql(
            text("SELECT * FROM audits WHERE workspace = :w ORDER BY timestamp DESC"),
            engine,
            params={"w": workspace}
        )
    except Exception as e:
        db_logger.error(f"Failed to fetch workspace audits for: {workspace}", exc_info=True)
        st.error("Unable to retrieve audit records. Please try again later.")
        return pd.DataFrame()


@st.cache_data(ttl=15, show_spinner=False)
def get_user_sub_info(username: str) -> Tuple[str, int]:
    """
    Get user subscription tier and invoice count.
    
    Args:
        username: The username to look up.
        
    Returns:
        Tuple of (subscription_tier, invoices_processed).
    """
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT subscription_tier, invoices_processed FROM users WHERE username = :u"),
                {"u": username}
            ).fetchone()
            if result:
                return result[0], result[1]
    except Exception as e:
        db_logger.error(f"Failed to get subscription info for user: {username}", exc_info=True)
    return "Free", 0


def increment_usage(username: str, count: int) -> None:
    """
    Increment the invoice processing count for a user.
    
    Args:
        username: The username to update.
        count: Number of invoices to add to the count.
    """
    try:
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE users SET invoices_processed = invoices_processed + :c WHERE username = :u"),
                {"c": count, "u": username}
            )
        st.cache_data.clear()
    except Exception as e:
        db_logger.error(f"Failed to increment usage for user: {username}", exc_info=True)
        st.toast("❌ Unable to update usage count", icon="❌")


def upgrade_tier(username: str, new_tier: str) -> None:
    """
    Upgrade a user's subscription tier.
    
    Args:
        username: The username to upgrade.
        new_tier: The new subscription tier name.
    """
    try:
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE users SET subscription_tier = :t WHERE username = :u"),
                {"t": new_tier, "u": username}
            )
        st.cache_data.clear()
        st.toast(f"Workspace upgraded successfully to {new_tier}!", icon="💎")
    except Exception as e:
        db_logger.error(f"Failed to upgrade tier for user: {username}", exc_info=True)
        st.error("Failed to upgrade subscription. Please contact support.")


def save_audit_record(
    record: Dict[str, Any],
    username: str,
    workspace: str
) -> None:
    """
    Save an audit record to the database.
    
    Args:
        record: Dictionary containing audit record fields.
        username: The username saving the record.
        workspace: The workspace context.
    """
    import hashlib
    
    try:
        record_str = f"{record['Filename']}-{record['Tracking ID']}-{record['Container No']}-{record['Audit Status']}-{workspace}"
        audit_hash = hashlib.sha256(record_str.encode('utf-8')).hexdigest()
        
        with engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO audits (filename, tracking_id, container_no, port, hs_code, stamp_status, iot_status, cfo_approval, date, currency, status, review_status, audit_hash, workspace, username)
                    VALUES (:f, :t, :c, :p, :hs, :st, :iot, :cfo, :d, :cur, :s, :rs, :h, :w, :u)
                """),
                {
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
                }
            )
        log_activity(username, workspace, "SAVE_AUDIT_RECORD", record["Filename"])
        st.cache_data.clear()
    except Exception as e:
        db_logger.error(f"Failed to save audit record: {record.get('Filename', 'unknown')}", exc_info=True)
        st.error("Unable to save audit record. Please try again.")


def update_audit_record(
    record_id: int,
    tracking_id: str,
    container_no: str,
    port: str,
    status: str
) -> None:
    """
    Update an existing audit record.
    
    Args:
        record_id: The ID of the record to update.
        tracking_id: New tracking ID value.
        container_no: New container number value.
        port: New port value.
        status: New audit status value.
    """
    try:
        with engine.begin() as conn:
            conn.execute(
                text("""
                    UPDATE audits 
                    SET tracking_id = :t, container_no = :c, port = :p, status = :s, review_status = 'Verified' 
                    WHERE id = :id
                """),
                {"t": tracking_id, "c": container_no, "p": port, "s": status, "id": record_id}
            )
        st.cache_data.clear()
    except Exception as e:
        db_logger.error(f"Failed to update audit record: {record_id}", exc_info=True)
        st.error("Unable to update record. Please try again.")


def approve_cfo_record(record_id: int) -> None:
    """
    Mark an audit record as CFO approved.
    
    Args:
        record_id: The ID of the record to approve.
    """
    try:
        with engine.begin() as conn:
            conn.execute(
                text("UPDATE audits SET cfo_approval = 'Approved by CFO' WHERE id = :id"),
                {"id": record_id}
            )
        st.cache_data.clear()
    except Exception as e:
        db_logger.error(f"Failed to approve CFO record: {record_id}", exc_info=True)
        st.error("Unable to process CFO approval. Please try again.")
