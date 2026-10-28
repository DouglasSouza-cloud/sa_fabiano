from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import StatusTablet, TabletCreate, TabletOut, TabletUpdate
from app.utils import erro_duplicado, montar_update

router = APIRouter(prefix="/tablets", tags=["Tablets"])

DUPLICADOS = {
    "patrimonio": "Ja existe um tablet com esse patrimonio",
    "epc": "Essa tag (EPC) ja esta cadastrada em outro tablet",
}


def _buscar(db: Session, tablet_id: int) -> dict:
    row = db.execute(
        text("SELECT * FROM tablets WHERE id = :id"), {"id": tablet_id}
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Tablet nao encontrado")
    return dict(row)


@router.post("", response_model=TabletOut, status_code=201)
def criar(dados: TabletCreate, db: Session = Depends(get_db)):
    try:
        res = db.execute(
            text(
                "INSERT INTO tablets (patrimonio, epc, marca, modelo, numero_serie) "
                "VALUES (:patrimonio, :epc, :marca, :modelo, :numero_serie)"
            ),
            dados.model_dump(),
        )
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise erro_duplicado(e, DUPLICADOS)
    return _buscar(db, res.lastrowid)


@router.get("", response_model=list[TabletOut])
def listar(
    status: Optional[StatusTablet] = None,
    busca: Optional[str] = Query(default=None, description="Parte do patrimonio, marca ou modelo"),
    limite: int = Query(default=50, ge=1, le=200),
    deslocamento: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    condicoes, params = [], {"limite": limite, "deslocamento": deslocamento}
    if status is not None:
        condicoes.append("status = :status")
        params["status"] = status
    if busca:
        condicoes.append("(patrimonio LIKE :busca OR marca LIKE :busca OR modelo LIKE :busca)")
        params["busca"] = f"%{busca}%"
    where = f"WHERE {' AND '.join(condicoes)}" if condicoes else ""
    rows = db.execute(
        text(f"SELECT * FROM tablets {where} ORDER BY patrimonio LIMIT :limite OFFSET :deslocamento"),
        params,
    ).mappings().all()
    return [dict(r) for r in rows]


@router.get("/{tablet_id}", response_model=TabletOut)
def obter(tablet_id: int, db: Session = Depends(get_db)):
    return _buscar(db, tablet_id)


@router.patch("/{tablet_id}", response_model=TabletOut)
def atualizar(tablet_id: int, dados: TabletUpdate, db: Session = Depends(get_db)):
    atual = _buscar(db, tablet_id)  # 404 se nao existir
    campos = dados.model_dump(exclude_unset=True)
    # patrimonio, epc e status sao obrigatorios no banco: ignora nulls.
    # marca, modelo e numero_serie aceitam null (limpar o campo).
    for obrigatorio in ("patrimonio", "epc", "status"):
        if campos.get(obrigatorio, "") is None:
            campos.pop(obrigatorio)
    if not campos:
        raise HTTPException(status_code=400, detail="Nenhum campo para atualizar")

    if "status" in campos and atual["status"] == "emprestado":
        raise HTTPException(
            status_code=409,
            detail="Tablet emprestado: o status so muda quando ele for devolvido",
        )

    sql, params = montar_update("tablets", campos)
    try:
        db.execute(text(sql), {**params, "id": tablet_id})
        db.commit()
    except IntegrityError as e:
        db.rollback()
        raise erro_duplicado(e, DUPLICADOS)
    return _buscar(db, tablet_id)
