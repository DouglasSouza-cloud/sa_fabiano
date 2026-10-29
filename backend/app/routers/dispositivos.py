import hashlib
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import DispositivoCreate, DispositivoCriado, DispositivoOut, DispositivoUpdate
from app.utils import erro_duplicado, montar_update

router = APIRouter(prefix="/dispositivos", tags=["Dispositivos"])

CAMPOS = "id, identificador, nome, ativo, simulado, ultimo_contato_em, ultimo_ip, criado_em"


def _buscar(db: Session, dispositivo_id: int) -> dict:
    row = db.execute(
        text(f"SELECT {CAMPOS} FROM dispositivos WHERE id = :id"), {"id": dispositivo_id}
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Dispositivo nao encontrado")
    return dict(row)


@router.post("", response_model=DispositivoCriado, status_code=201)
def criar(dados: DispositivoCreate, db: Session = Depends(get_db)):
    # A chave vai para o ESP32. O banco guarda so o hash (SHA-256, 64 caracteres).
    chave = secrets.token_urlsafe(32)
    chave_hash = hashlib.sha256(chave.encode()).hexdigest()
    try:
        res = db.execute(
            text(
                "INSERT INTO dispositivos (identificador, nome, chave_hash, simulado) "
                "VALUES (:identificador, :nome, :chave_hash, :simulado)"
            ),
            {**dados.model_dump(), "chave_hash": chave_hash},
        )
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise erro_duplicado(e, {"identificador": "Ja existe um dispositivo com esse identificador"})
    return {**_buscar(db, res.lastrowid), "chave": chave}


@router.get("", response_model=list[DispositivoOut])
def listar(ativo: Optional[bool] = None, db: Session = Depends(get_db)):
    where, params = "", {}
    if ativo is not None:
        where, params = "WHERE ativo = :ativo", {"ativo": ativo}
    rows = db.execute(
        text(f"SELECT {CAMPOS} FROM dispositivos {where} ORDER BY nome"), params
    ).mappings().all()
    return [dict(r) for r in rows]


@router.get("/{dispositivo_id}", response_model=DispositivoOut)
def obter(dispositivo_id: int, db: Session = Depends(get_db)):
    return _buscar(db, dispositivo_id)


@router.patch("/{dispositivo_id}", response_model=DispositivoOut)
def atualizar(dispositivo_id: int, dados: DispositivoUpdate, db: Session = Depends(get_db)):
    _buscar(db, dispositivo_id)
    campos = dados.model_dump(exclude_unset=True, exclude_none=True)
    if not campos:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")
    sql, params = montar_update("dispositivos", campos)
    db.execute(text(sql), {**params, "id": dispositivo_id})
    db.commit()
    return _buscar(db, dispositivo_id)
