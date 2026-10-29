from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.routers import dispositivos, eventos, inventarios, professores, reservas, tablets

app = FastAPI(title="Heimdall - Controle de Tablets")

app.include_router(professores.router)
app.include_router(tablets.router)
app.include_router(dispositivos.router)
app.include_router(reservas.router)
app.include_router(eventos.router)
app.include_router(inventarios.router)


@app.get("/health")
def health(db: Session = Depends(get_db)):
    """Confirma que a API esta no ar e consegue falar com o banco."""
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="Banco de dados indisponivel")
    return {"status": "ok"}
