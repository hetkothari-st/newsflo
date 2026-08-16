"""One small thing every ledger write path needs.

The ledger's functions accept EITHER a SQLAlchemy `Session` (the app and the
tests) OR a `Connection` (the standalone review UI, which works inside
`engine.begin()`). Both have `.execute()`, which is why the duck typing
works -- but only one of them owns its transaction. Calling `.commit()` on a
Connection inside `engine.begin()` closes the caller's block underneath it.

So: commit a Session, never a Connection.
"""
from sqlalchemy.engine import Connection


def commit_if_owned(executor) -> bool:
    """Commit when we own the transaction. Returns True if we committed."""
    if isinstance(executor, Connection):
        return False
    commit = getattr(executor, "commit", None)
    if callable(commit):
        commit()
        return True
    return False
