from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings

# pool_pre_ping evita erro quando o MySQL derruba conexoes ociosas
engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False)


def get_db():
    """Dependencia do FastAPI: uma sessao por requisicao."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
