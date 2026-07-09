import csv
import io

from sqlalchemy.orm import Session

from app.models import Company, Holding


def load_holdings_from_csv(session: Session, user_id: int, csv_file) -> int:
    """Load holdings from a file-like object with ``Ticker,Quantity`` columns.

    ``csv_file`` may be a text stream or a binary stream — it works directly with
    FastAPI's ``UploadFile.file`` (a binary SpooledTemporaryFile). Rows whose
    ticker is unknown are skipped (they do not fail the whole batch). Existing
    ``(user_id, company_id)`` holdings are updated (upsert), not duplicated.
    Returns the number of rows successfully upserted (skipped unknown-ticker rows
    are not counted).
    """
    raw = csv_file.read()
    text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    reader = csv.DictReader(io.StringIO(text))

    processed = 0
    for row in reader:
        ticker = (row.get("Ticker") or "").strip()
        if not ticker:
            continue
        company = session.query(Company).filter_by(ticker=ticker).one_or_none()
        if company is None:
            continue
        quantity = float(row["Quantity"])
        existing = (
            session.query(Holding)
            .filter_by(user_id=user_id, company_id=company.id)
            .one_or_none()
        )
        if existing is not None:
            existing.quantity = quantity
        else:
            session.add(Holding(user_id=user_id, company_id=company.id, quantity=quantity))
        processed += 1
    session.commit()
    return processed
