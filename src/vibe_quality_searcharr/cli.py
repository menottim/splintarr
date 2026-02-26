"""
Management CLI for Vibe-Quality-Searcharr.

Provides administrative commands that require shell access:
- Password reset for locked/forgotten accounts

Usage:
    python -m vibe_quality_searcharr.cli reset-password
"""

import getpass
import re
import sys

import structlog

logger = structlog.get_logger()


def reset_password() -> None:
    """Reset a user's password from the command line."""
    from vibe_quality_searcharr.core.security import hash_password
    from vibe_quality_searcharr.database import get_session_factory, init_db
    from vibe_quality_searcharr.models.user import User

    init_db()
    session_factory = get_session_factory()
    db = session_factory()

    try:
        username = input("Username: ").strip()
        if not username:
            print("Error: Username cannot be empty")
            sys.exit(1)

        user = db.query(User).filter(User.username == username).first()
        if not user:
            print(f"Error: User '{username}' not found")
            sys.exit(1)

        new_password = getpass.getpass("New password: ")
        confirm_password = getpass.getpass("Confirm new password: ")

        if new_password != confirm_password:
            print("Error: Passwords do not match")
            sys.exit(1)

        if len(new_password) < 12:
            print("Error: Password must be at least 12 characters long")
            sys.exit(1)
        if len(new_password) > 128:
            print("Error: Password must not exceed 128 characters")
            sys.exit(1)
        if not re.search(r"[a-z]", new_password):
            print("Error: Password must contain at least one lowercase letter")
            sys.exit(1)
        if not re.search(r"[A-Z]", new_password):
            print("Error: Password must contain at least one uppercase letter")
            sys.exit(1)
        if not re.search(r"[0-9]", new_password):
            print("Error: Password must contain at least one digit")
            sys.exit(1)
        if not re.search(r'[!@#$%^&*(),.?":{}|<>_\-+=\[\]\\;/`~]', new_password):
            print("Error: Password must contain at least one special character")
            sys.exit(1)

        user.password_hash = hash_password(new_password)
        user.reset_failed_login()
        db.commit()

        print(f"Password reset successfully for user '{username}'")
        if user.account_locked_until:
            print("Account has been unlocked.")

    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(1)
    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
        sys.exit(1)
    finally:
        db.close()


def main() -> None:
    """CLI entry point."""
    if len(sys.argv) < 2:
        print("Usage: python -m vibe_quality_searcharr.cli <command>")
        print("")
        print("Commands:")
        print("  reset-password    Reset a user's password and unlock the account")
        sys.exit(1)

    command = sys.argv[1]
    if command == "reset-password":
        reset_password()
    else:
        print(f"Unknown command: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
