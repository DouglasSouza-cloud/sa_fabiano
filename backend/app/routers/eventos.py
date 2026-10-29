import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import bindparam, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth import dispositivo_autenticado
from app.config import settings
from app.database import get_db
from app.schemas import (
    Evento,
    EventoCracha,
    EventoFalha,
    EventoHeartbeat,
    EventoInventario,
    EventoLogOut,
    EventoPorta,
    EventoResposta,
)

router = APIRouter(prefix="/eventos", tags=["Eventos do armario"])


def _json(valor):
    """O MySQL devolve colunas JSON como texto; converte de volta."""
    if valor is None or isinstance(valor, (dict, list)):
        return valor
    return json.loads(valor)


def _resposta_anterior(db: Session, dispositivo_id: int, request_id: str) -> Optional[dict]:
    row = db.execute(
        text("SELECT resposta_json FROM leituras_log WHERE dispositivo_id = :d AND request_id = :r"),
        {"d": dispositivo_id, "r": request_id},
    ).first()
    if row is None:
        return None
    return _json(row.resposta_json) or {}


# ---------------- Processamento de cada tipo ----------------

def _cracha(db: Session, ev: EventoCracha):
    prof = db.execute(
        text("SELECT id, nome, ativo FROM professores WHERE uid_cracha = :uid"),
        {"uid": ev.uid_cracha},
    ).mappings().first()
    if prof is None:
        return "rejeitado", "Cracha nao cadastrado", {}, {"uid_cracha": ev.uid_cracha}
    if not prof["ativo"]:
        return "rejeitado", "Professor inativo", {}, {"uid_cracha": ev.uid_cracha}
    return (
        "processado",
        None,
        {"professor": {"id": prof["id"], "nome": prof["nome"]}},
        {"uid_cracha": ev.uid_cracha},
    )


def _inventario(db: Session, disp: dict, ev: EventoInventario, origem: str, agora: datetime):
    desconhecidos = list(ev.epcs)
    if ev.epcs:
        consulta = text("SELECT epc FROM tablets WHERE epc IN :epcs").bindparams(
            bindparam("epcs", expanding=True)
        )
        conhecidos = {r.epc for r in db.execute(consulta, {"epcs": ev.epcs})}
        desconhecidos = [e for e in ev.epcs if e not in conhecidos]

    motivos = []
    if not ev.completo:
        motivos.append("leitura incompleta")
    minimo = settings.inventario_qualidade_minima
    if ev.qualidade is not None and ev.qualidade < minimo:
        motivos.append(f"qualidade {ev.qualidade} abaixo do minimo {minimo}")
    valido = not motivos
    motivo = "; ".join(motivos) or None

    res = db.execute(
        text(
            "INSERT INTO inventario_snapshots "
            "(dispositivo_id, request_id, inventario_id, origem, completo, qualidade, valido, "
            " motivo_invalido, total_epcs, epcs, epcs_desconhecidos, num_leituras, lido_em, recebido_em) "
            "VALUES (:d, :r, :inv, :origem, :completo, :qualidade, :valido, "
            " :motivo, :total, :epcs, :desc, :nleit, :lido, :recebido)"
        ),
        {
            "d": disp["id"], "r": ev.request_id, "inv": ev.inventario_id, "origem": origem,
            "completo": ev.completo, "qualidade": ev.qualidade, "valido": valido,
            "motivo": motivo, "total": len(ev.epcs), "epcs": json.dumps(ev.epcs),
            "desc": json.dumps(desconhecidos), "nleit": ev.num_leituras,
            "lido": ev.lido_em, "recebido": agora,
        },
    )
    extras = {
        "snapshot_id": res.lastrowid,
        "valido": valido,
        "total_epcs": len(ev.epcs),
        "epcs_desconhecidos": desconhecidos,
    }
    resultado = "processado" if valido else "ignorado"
    return resultado, motivo, extras, {"completa": ev.completo, "snapshot_id": res.lastrowid}


# ---------------- Endpoints ----------------

@router.post("", response_model=EventoResposta, response_model_exclude_none=True)
def receber(
    evento: Evento,
    dispositivo: dict = Depends(dispositivo_autenticado),
    db: Session = Depends(get_db),
):
    """Recebe um evento do ESP32. Cabecalho obrigatorio: X-Device-Key.
    O mesmo request_id enviado de novo devolve a resposta original (repetido=true)."""
    anterior = _resposta_anterior(db, dispositivo["id"], evento.request_id)
    if anterior is not None:
        return {**anterior, "repetido": True}

    agora = datetime.now()
    origem = "simulacao" if dispositivo["simulado"] else "real"

    try:
        if isinstance(evento, EventoCracha):
            resultado, detalhe, extras, log = _cracha(db, evento)
        elif isinstance(evento, EventoInventario):
            resultado, detalhe, extras, log = _inventario(db, dispositivo, evento, origem, agora)
        elif isinstance(evento, EventoPorta):
            resultado, detalhe, extras, log = "processado", f"porta {evento.estado}", {}, {}
        elif isinstance(evento, EventoFalha):
            resultado, detalhe, extras, log = "processado", evento.detalhe, {}, {}
        else:  # heartbeat
            resultado, detalhe, extras, log = "processado", None, {}, {}

        resposta = {
            "request_id": evento.request_id,
            "tipo": evento.tipo,
            "resultado": resultado,
            "detalhe": detalhe,
            **extras,
        }
        resposta = {k: v for k, v in resposta.items() if v is not None}

        db.execute(
            text(
                "INSERT INTO leituras_log "
                "(dispositivo_id, request_id, tipo_evento, origem, uid_cracha, completa, lido_em, "
                " recebido_em, resultado, detalhe, http_status, payload_json, resposta_json, snapshot_id) "
                "VALUES (:d, :r, :tipo, :origem, :uid, :completa, :lido, "
                " :recebido, :resultado, :detalhe, 200, :payload, :resposta, :snapshot)"
            ),
            {
                "d": dispositivo["id"], "r": evento.request_id, "tipo": evento.tipo,
                "origem": origem, "uid": log.get("uid_cracha"), "completa": log.get("completa"),
                "lido": evento.lido_em, "recebido": agora, "resultado": resultado,
                "detalhe": detalhe,
                "payload": json.dumps(evento.model_dump(mode="json"), ensure_ascii=False),
                "resposta": json.dumps(resposta, ensure_ascii=False),
                "snapshot": log.get("snapshot_id"),
            },
        )
        db.commit()
    except IntegrityError:
        # Dois envios do mesmo request_id ao mesmo tempo: o segundo cai aqui
        db.rollback()
        anterior = _resposta_anterior(db, dispositivo["id"], evento.request_id)
        if anterior is None:
            raise
        return {**anterior, "repetido": True}

    return resposta


@router.get("", response_model=list[EventoLogOut])
def listar(
    dispositivo_id: Optional[int] = None,
    tipo: Optional[str] = Query(default=None, description="cracha, inventario, porta, heartbeat, ..."),
    resultado: Optional[str] = Query(default=None, description="processado, ignorado, rejeitado"),
    limite: int = Query(default=50, ge=1, le=200),
    deslocamento: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """Log de tudo que os armarios enviaram, do mais recente para o mais antigo."""
    condicoes, params = [], {"limite": limite, "deslocamento": deslocamento}
    if dispositivo_id is not None:
        condicoes.append("dispositivo_id = :dispositivo_id")
        params["dispositivo_id"] = dispositivo_id
    if tipo:
        condicoes.append("tipo_evento = :tipo")
        params["tipo"] = tipo
    if resultado:
        condicoes.append("resultado = :resultado")
        params["resultado"] = resultado
    where = f"WHERE {' AND '.join(condicoes)}" if condicoes else ""
    rows = db.execute(
        text(
            "SELECT id, dispositivo_id, request_id, tipo_evento, origem, uid_cracha, completa, "
            f"lido_em, recebido_em, resultado, detalhe, snapshot_id, payload_json FROM leituras_log {where} "
            "ORDER BY id DESC LIMIT :limite OFFSET :deslocamento"
        ),
        params,
    ).mappings().all()
    return [{**dict(r), "payload_json": _json(r["payload_json"])} for r in rows]
