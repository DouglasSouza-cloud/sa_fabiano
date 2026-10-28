from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import ProfessorCreate, ProfessorOut, ProfessorUpdate
from app.utils import erro_duplicado, montar_update

router = APIRouter(prefix="/professores", tags=["Professores"])

DUPLICADOS = {
    "matricula": "Ja existe um professor com essa matricula",
    "uid_cracha": "Esse cracha ja esta cadastrado para outro professor",
}


def _buscar(db: Session, professor_id: int) -> dict:
    row = db.execute(
        text("SELECT * FROM professores WHERE id = :id"), {"id": professor_id}
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Professor nao encontrado")
    return dict(row)


@router.post("", response_model=ProfessorOut, status_code=201)
def criar(dados: ProfessorCreate, db: Session = Depends(get_db)):
    try:
        res = db.execute(
            text(
                "INSERT INTO professores (nome, matricula, uid_cracha) "
                "VALUES (:nome, :matricula, :uid_cracha)"
            ),
            dados.model_dump(),
        )
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise erro_duplicado(e, DUPLICADOS)
    return _buscar(db, res.lastrowid)


@router.get("", response_model=list[ProfessorOut])
def listar(
    ativo: Optional[bool] = None,
    busca: Optional[str] = Query(default=None, description="Parte do nome ou da matricula"),
    limite: int = Query(default=50, ge=1, le=200),
    deslocamento: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    condicoes, params = [], {"limite": limite, "deslocamento": deslocamento}
    if ativo is not None:
        condicoes.append("ativo = :ativo")
        params["ativo"] = ativo
    if busca:
        condicoes.append("(nome LIKE :busca OR matricula LIKE :busca)")
        params["busca"] = f"%{busca}%"
    where = f"WHERE {' AND '.join(condicoes)}" if condicoes else ""
    rows = db.execute(
        text(f"SELECT * FROM professores {where} ORDER BY nome LIMIT :limite OFFSET :deslocamento"),
        params,
    ).mappings().all()
    return [dict(r) for r in rows]


@router.get("/{professor_id}", response_model=ProfessorOut)
def obter(professor_id: int, db: Session = Depends(get_db)):
    return _buscar(db, professor_id)


@router.patch("/{professor_id}", response_model=ProfessorOut)
def atualizar(professor_id: int, dados: ProfessorUpdate, db: Session = Depends(get_db)):
    _buscar(db, professor_id)  # 404 se nao existir
    # Todos os campos do professor sao obrigatorios no banco: ignora nulls
    campos = dados.model_dump(exclude_unset=True, exclude_none=True)
    if not campos:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")
    sql, params = montar_update("professores", campos)
    try:
        db.execute(text(sql), {**params, "id": professor_id})
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise erro_duplicado(e, DUPLICADOS)
    return _buscar(db, professor_id)
