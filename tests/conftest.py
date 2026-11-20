import pytest

from hobees.config import settings
from hobees.db.models import Base
from hobees.db.session import dispose_engine, get_engine


@pytest.fixture(scope="session", autouse=True)
def initialize_test_database():
    original_database_url = settings.database_url
    if not original_database_url:
        settings.database_url = "sqlite:///:memory:"

    dispose_engine()
    engine = get_engine()
    Base.metadata.create_all(engine)

    yield

    dispose_engine()
    settings.database_url = original_database_url
