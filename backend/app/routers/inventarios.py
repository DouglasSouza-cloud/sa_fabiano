import json

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas import InventarioOut

router = APIRouter(prefix="/inventarios", tags=["Inventario"])


def _lista(valor) -> list:
    if valor is None:
        return []
    return valor if isinstance(valor, list) else json.loads(valor)


@router.get("/ultimo", response_model=InventarioOut)
def ultimo(
    dispositivo_id: int,
    apenas_validos: bool = Query(default=True, description="Ignora leituras incompletas ou de baixa qualidade"),
    db: Session = Depends(get_db),
):
    """O que o armario informou ter dentro na ultima leitura, com o patrimonio de cada tablet."""
    filtro = "AND valido = TRUE" if apenas_validos else ""
    snap = db.execute(
        text(
            "SELECT id, dispositivo_id, recebido_em, lido_em, completo, qualidade, valido, "
            "motivo_invalido, total_epcs, epcs, epcs_desconhecidos "
            f"FROM inventario_snapshots WHERE dispositivo_id = :d {filtro} ORDER BY id DESC LIMIT 1"
        ),
        {"d": dispositivo_id},
    ).mappings().first()
    if snap is None:
        raise HTTPException(status_code=404, detail="Nenhum inventario recebido desse dispositivo")

    epcs = _lista(snap["epcs"])
    tablets = []
    if epcs:
        consulta = text(
            "SELECT id, patrimonio, epc FROM tablets WHERE epc IN :epcs ORDER BY patrimonio"
        ).bindparams(bindparam("epcs", expanding=True))
        tablets = [dict(r) for r in db.execute(consulta, {"epcs": epcs}).mappings()]

    return {
        "snapshot_id": snap["id"],
        "dispositivo_id": snap["dispositivo_id"],
        "recebido_em": snap["recebido_em"],
        "lido_em": snap["lido_em"],
        "completo": bool(snap["completo"]),
        "qualidade": float(snap["qualidade"]) if snap["qualidade"] is not None else None,
        "valido": bool(snap["valido"]),
        "motivo_invalido": snap["motivo_invalido"],
        "total_epcs": snap["total_epcs"],
        "tablets": tablets,
        "epcs_desconhecidos": _lista(snap["epcs_desconhecidos"]),
    }
