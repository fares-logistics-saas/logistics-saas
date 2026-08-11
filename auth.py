"""
Authentication module for Logistics SaaS Engine.

Handles user authentication, password hashing with bcrypt, MFA verification,
user registration, and role-based access control (RBAC).
"""

import logging
from typing import Optional, Tuple

import bcrypt
import streamlit as st
from sqlalchemy import text

from config import (
    PERMISSIONS,
    BCRYPT_ROUNDS,
    MIN_PASSWORD_LENGTH,
    get_default_admin_password as _get_default_admin_password,
    logger,
)

# Module logger
auth_logger = logging.getLogger(__name__)


def hash_password(password: str) -> str:
    """
    Hash a password using bcrypt with secure salt.
    
    Args:
        password: The plain text password to hash.
        
    Returns:
        The bcrypt hashed password as a string.
    """
    salt = bcrypt.gensalt(rounds=BCRYPT_ROUNDS)
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')


def verify_password(password: str, hashed_password: str) -> bool:
    """
    Verify a password against its bcrypt hash.
    
    Args:
        password: The plain text password to verify.
        hashed_password: The bcrypt hash to verify against.
        
    Returns:
        True if the password matches, False otherwise.
    """
    try:
        return bcrypt.checkpw(
            password.encode('utf-8'),
            hashed_password.encode('utf-8')
        )
    except Exception as e:
        auth_logger.error("Password verification failed", exc_info=True)
        return False


def get_default_admin_password() -> str:
    """
    Get the default admin password for initial setup.
    
    Delegates to config module for secure password generation.
    
    Returns:
        The admin password string.
    """
    return _get_default_admin_password()


def validate_password_strength(password: str) -> Tuple[bool, str]:
    """
    Validate password meets minimum security requirements.
    
    Args:
        password: The password to validate.
        
    Returns:
        Tuple of (is_valid, error_message).
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        return False, f"Password must be at least {MIN_PASSWORD_LENGTH} characters long."
    
    # Check for at least one letter and one number
    has_letter = any(c.isalpha() for c in password)
    has_digit = any(c.isdigit() for c in password)
    
    if not has_letter or not has_digit:
        return False, "Password must contain at least one letter and one number."
    
    return True, ""


def has_permission(role: str, action: str) -> bool:
    """
    Check if a role has permission to perform an action.
    
    Args:
        role: The user's role.
        action: The action to check permission for.
        
    Returns:
        True if the role has permission, False otherwise.
    """
    if role not in PERMISSIONS:
        return False
    return "all" in PERMISSIONS[role] or action in PERMISSIONS[role]


def add_user(
    username: str,
    password: str,
    role: str = "Auditor",
    workspace: str = "Default Corp",
    mfa_code: Optional[str] = None
) -> bool:
    """
    Create a new user account.
    
    Args:
        username: The username for the new account.
        password: The password for the new account.
        role: The role to assign (default: Auditor).
        workspace: The workspace to assign (default: Default Corp).
        mfa_code: Optional MFA code for authentication.
        
    Returns:
        True if user was created successfully, False otherwise.
    """
    from database import engine
    
    # Validate password strength
    is_valid, error_msg = validate_password_strength(password)
    if not is_valid:
        st.error(error_msg)
        return False
    
    try:
        with engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT INTO users (username, password, role, workspace, mfa_code, subscription_tier, invoices_processed) 
                    VALUES (:u, :p, :r, :w, :m, 'Free', 0)
                """),
                {
                    "u": username,
                    "p": hash_password(password),
                    "r": role,
                    "w": workspace,
                    "m": mfa_code
                }
            )
        st.cache_data.clear()
        auth_logger.info(f"New user created: {username}")
        return True
    except Exception as e:
        auth_logger.error(f"Failed to create user: {username}", exc_info=True)
        return False


def login_user(
    username: str,
    password: str,
    mfa_input: Optional[str] = None
) -> Tuple[Optional[str], Optional[str]]:
    """
    Authenticate a user with username, password, and optional MFA.
    
    Args:
        username: The username to authenticate.
        password: The password to verify.
        mfa_input: Optional MFA code to verify.
        
    Returns:
        Tuple of (role, workspace) if authentication succeeds, (None, None) otherwise.
    """
    from database import engine
    
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT password, role, workspace, mfa_code FROM users WHERE username = :u"),
                {"u": username.strip()}
            ).fetchone()
            
            if result:
                stored_password, role, workspace, stored_mfa = result
                
                # Verify password using bcrypt
                if verify_password(password, stored_password):
                    # If MFA is configured (not NULL and not empty), verify the code
                    # Note: Users with old '1234' default need to update their MFA or set it to NULL
                    if stored_mfa and stored_mfa.strip():
                        if not mfa_input or mfa_input.strip() != stored_mfa:
                            auth_logger.warning(f"MFA verification failed for user: {username}")
                            return None, None
                    
                    auth_logger.info(f"User logged in successfully: {username}")
                    return role, workspace
                else:
                    auth_logger.warning(f"Invalid password for user: {username}")
                    
    except Exception as e:
        auth_logger.error(f"Login error for user: {username}", exc_info=True)
    
    return None, None


def get_login_count(username: str) -> int:
    """
    Get the number of times a user has logged in.
    
    Args:
        username: The username to check.
        
    Returns:
        The number of login records found.
    """
    from database import engine
    
    try:
        with engine.connect() as conn:
            count = conn.execute(
                text("SELECT COUNT(*) FROM activity_logs WHERE username = :u AND action = 'USER_LOGIN'"),
                {"u": username.strip()}
            ).scalar()
            return count or 0
    except Exception as e:
        auth_logger.error(f"Failed to get login count for user: {username}", exc_info=True)
        return 0
