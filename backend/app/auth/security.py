import bcrypt


def hash_password(password: str) -> str:
    """Return a bcrypt hash of ``password``. Only the hash is ever persisted —
    the raw password is never stored or logged."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    """Return True iff ``password`` matches the stored bcrypt ``hashed`` value."""
    return bcrypt.checkpw(password.encode(), hashed.encode())
