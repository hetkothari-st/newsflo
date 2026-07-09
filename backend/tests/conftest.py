import pytest
from sqlalchemy.orm import sessionmaker

from app.db import Base, get_engine
from app import models  # noqa: F401  ensures models are registered on Base


@pytest.fixture()
def db_session():
    engine = get_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
