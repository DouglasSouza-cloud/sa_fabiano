from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import OcorrenciaOut, ResolverOcorrencia, TipoOcorrencia

router = APIRouter(prefix="/ocorrencias", tags=["Ocorrencias"])

CAMPOS = (
    "id, tipo, status, origem, dispositivo_id, emprestimo_id, tablet_id, snapshot_id, "
    "descricao, criada_em, resolvida_em, resolucao"
)


def _buscar(db: Session, ocorrencia_id: int) -> dict:
    row = db.execute(
        text(f"SELECT {CAMPOS} FROM ocorrencias WHERE id = :id"), {"id": ocorrencia_id}
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Ocorrencia nao encontrada")
    return dict(row)


def _encerrar(db: Session, ocorrencia_id: int, novo_status: str, texto: str) -> dict:
    atual = _buscar(db, ocorrencia_id)
    if atual["status"] != "aberta":
        raise HTTPException(status_code=409, detail=f"Ocorrencia ja {atual['status']}")
    # resolvida_por fica vazio ate existir login de administrador
    db.execute(
        text(
            "UPDATE ocorrencias SET status = :st, resolvida_em = :agora, resolucao = :res "
            "WHERE id = :id AND status = 'aberta'"
        ),
        {"st": novo_status, "agora": datetime.now(), "res": texto, "id": ocorrencia_id},
    )
    db.commit()
    return _buscar(db, ocorrencia_id)


@router.get("", response_model=list[OcorrenciaOut])
def listar(
    status: Optional[Literal["aberta", "resolvida", "descartada"]] = None,
    tipo: Optional[TipoOcorrencia] = None,
    dispositivo_id: Optional[int] = None,
    limite: int = Query(default=50, ge=1, le=200),
    deslocamento: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    condicoes, params = [], {"limite": limite, "deslocamento": deslocamento}
    if status:
        condicoes.append("status = :status")
        params["status"] = status
    if tipo:
        condicoes.append("tipo = :tipo")
        params["tipo"] = tipo
    if dispositivo_id is not None:
        condicoes.append("dispositivo_id = :dispositivo_id")
        params["dispositivo_id"] = dispositivo_id
    where = f"WHERE {' AND '.join(condicoes)}" if condicoes else ""
    rows = db.execute(
        text(f"SELECT {CAMPOS} FROM ocorrencias {where} ORDER BY id DESC LIMIT :limite OFFSET :deslocamento"),
        params,
    ).mappings().all()
    return [dict(r) for r in rows]


@router.get("/{ocorrencia_id}", response_model=OcorrenciaOut)
def obter(ocorrencia_id: int, db: Session = Depends(get_db)):
    return _buscar(db, ocorrencia_id)


@router.post("/{ocorrencia_id}/resolver", response_model=OcorrenciaOut)
def resolver(ocorrencia_id: int, dados: ResolverOcorrencia, db: Session = Depends(get_db)):
    return _encerrar(db, ocorrencia_id, "resolvida", dados.resolucao)


@router.post("/{ocorrencia_id}/descartar", response_model=OcorrenciaOut)
def descartar(ocorrencia_id: int, dados: ResolverOcorrencia, db: Session = Depends(get_db)):
    return _encerrar(db, ocorrencia_id, "descartada", dados.resolucao)
