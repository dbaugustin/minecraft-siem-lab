"""Print an argon2id hash for the dashboard password.

Usage:
    python scripts/hash_password.py

Paste the output into .env as DASHBOARD_ADMIN_PASSWORD_HASH='...'. Single quotes
matter: the hash contains '$' characters.
"""

import getpass
import sys

from argon2 import PasswordHasher


def main():
    password = getpass.getpass("New dashboard password: ")
    if len(password) < 12:
        sys.exit("Use at least 12 characters.")
    if getpass.getpass("Confirm: ") != password:
        sys.exit("Passwords did not match.")
    print(PasswordHasher().hash(password))


if __name__ == "__main__":
    main()
