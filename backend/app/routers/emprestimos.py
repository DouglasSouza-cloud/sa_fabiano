from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.armario import expirar_sessoes
from app.database import get_db
from app.schemas import EmprestimoOut, StatusEmprestimo, TabletForaOut

router = APIRouter(prefix="/emprestimos", tags=["Emprestimos"])

SELECT_EMPRESTIMO = (
    "SELECT e.id, e.professor_id, p.nome AS professor_nome, e.dispositivo_id, e.reserva_id, "
    "e.status, e.origem, e.aberta_em, e.fechada_em "
    "FROM emprestimos e INNER JOIN professores p ON p.id = e.professor_id"
)


def _com_itens(db: Session, rows: list[dict]) -> list[dict]:
    if not rows:
        return []
    consulta = text(
        "SELECT i.emprestimo_id, i.tablet_id, t.patrimonio, i.retirado_em, i.devolvido_em, "
        "i.devolvido_por_professor_id FROM emprestimo_itens i "
        "INNER JOIN tablets t ON t.id = i.tablet_id "
        "WHERE i.emprestimo_id IN :ids ORDER BY i.id"
    ).bindparams(bindparam("ids", expanding=True))
    itens: dict[int, list] = {}
    for r in db.execute(consulta, {"ids": [r["id"] for r in rows]}).mappings():
        itens.setdefault(r["emprestimo_id"], []).append(dict(r))
    return [{**r, "itens": itens.get(r["id"], [])} for r in rows]


def _atualizar(db: Session) -> None:
    expirar_sessoes(db, datetime.now())
    db.commit()


@router.get("/tablets-fora", response_model=list[TabletForaOut])
def tablets_fora(db: Session = Depends(get_db)):
    """Quem esta com quais tablets agora."""
    rows = db.execute(
        text(
            "SELECT t.id AS tablet_id, t.patrimonio, t.epc, p.id AS professor_id, p.nome AS professor, "
            "p.matricula, e.id AS emprestimo_id, i.retirado_em "
            "FROM emprestimo_itens i "
            "INNER JOIN tablets t ON t.id = i.tablet_id "
            "INNER JOIN emprestimos e ON e.id = i.emprestimo_id "
            "INNER JOIN professores p ON p.id = e.professor_id "
            "WHERE i.devolvido_em IS NULL ORDER BY i.retirado_em, t.patrimonio"
        )
    ).mappings().all()
    return [dict(r) for r in rows]


@router.get("", response_model=list[EmprestimoOut])
def listar(
    professor_id: Optional[int] = None,
    dispositivo_id: Optional[int] = None,
    status: Optional[StatusEmprestimo] = None,
    limite: int = Query(default=50, ge=1, le=200),
    deslocamento: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    _atualizar(db)
    condicoes, params = [], {"limite": limite, "deslocamento": deslocamento}
    if professor_id is not None:
        condicoes.append("e.professor_id = :professor_id")
        params["professor_id"] = professor_id
    if dispositivo_id is not None:
        condicoes.append("e.dispositivo_id = :dispositivo_id")
        params["dispositivo_id"] = dispositivo_id
    if status is not None:
        condicoes.append("e.status = :status")
        params["status"] = status
    where = f"WHERE {' AND '.join(condicoes)}" if condicoes else ""
    rows = db.execute(
        text(f"{SELECT_EMPRESTIMO} {where} ORDER BY e.id DESC LIMIT :limite OFFSET :deslocamento"),
        params,
    ).mappings().all()
    return _com_itens(db, [dict(r) for r in rows])


@router.get("/{emprestimo_id}", response_model=EmprestimoOut)
def obter(emprestimo_id: int, db: Session = Depends(get_db)):
    _atualizar(db)
    row = db.execute(
        text(f"{SELECT_EMPRESTIMO} WHERE e.id = :id"), {"id": emprestimo_id}
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Emprestimo nao encontrado")
    return _com_itens(db, [dict(row)])[0]
