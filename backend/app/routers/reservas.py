from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.schemas import (
    DisponibilidadeOut,
    ReservaCreate,
    ReservaOut,
    StatusReserva,
    para_naive,
)

router = APIRouter(prefix="/reservas", tags=["Reservas"])

# Aceita um inicio ligeiramente no passado (quem digita "agora" quase sempre erra por segundos)
FOLGA_INICIO = timedelta(minutes=5)

SELECT_RESERVA = (
    "SELECT r.*, p.nome AS professor_nome "
    "FROM reservas r INNER JOIN professores p ON p.id = r.professor_id"
)


# ---------------- Regras ----------------

def expirar_vencidas(db: Session, agora: datetime, commit: bool = True) -> None:
    """Reserva ativa vira 'expirada' quando passa da tolerancia depois do inicio
    OU quando chega ao fim, o que vier primeiro. Roda a cada uso dos endpoints."""
    limite = agora - timedelta(minutes=settings.reserva_tolerancia_minutos)
    db.execute(
        text(
            "UPDATE reservas SET status = 'expirada' "
            "WHERE status = 'ativa' AND (fim_em <= :agora OR inicio_em <= :limite)"
        ),
        {"agora": agora, "limite": limite},
    )
    if commit:
        db.commit()


def capacidade(db: Session) -> int:
    """Tablets em condicao de uso. Ainda nao existe vinculo tablet-armario no banco,
    entao a capacidade vale para o sistema todo (um armario)."""
    return db.execute(
        text("SELECT COUNT(*) FROM tablets WHERE status NOT IN ('manutencao', 'indisponivel')")
    ).scalar()


def pico_reservado(
    db: Session,
    dispositivo_id: int,
    inicio: datetime,
    fim: datetime,
    status: tuple = ("ativa", "em_uso"),
) -> int:
    """Maior quantidade de tablets reservados ao mesmo tempo dentro da janela.
    Nao e a soma das reservas: duas reservas seguidas nao se acumulam."""
    consulta = text(
        "SELECT inicio_em, fim_em, quantidade FROM reservas "
        "WHERE dispositivo_id = :d AND status IN :st "
        "AND inicio_em < :fim AND fim_em > :inicio"
    ).bindparams(bindparam("st", expanding=True))
    rows = db.execute(
        consulta, {"d": dispositivo_id, "inicio": inicio, "fim": fim, "st": list(status)}
    ).all()
    # O pico so pode mudar quando uma reserva comeca
    pontos = {inicio} | {r.inicio_em for r in rows if inicio < r.inicio_em < fim}
    return max(
        (sum(r.quantidade for r in rows if r.inicio_em <= t < r.fim_em) for t in pontos),
        default=0,
    )


def _buscar(db: Session, reserva_id: int) -> dict:
    row = db.execute(
        text(f"{SELECT_RESERVA} WHERE r.id = :id"), {"id": reserva_id}
    ).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Reserva nao encontrada")
    return dict(row)


# ---------------- Endpoints ----------------

@router.get("/disponibilidade", response_model=DisponibilidadeOut)
def disponibilidade(
    dispositivo_id: int,
    inicio_em: datetime,
    fim_em: datetime,
    db: Session = Depends(get_db),
):
    """Quantos tablets estao garantidos livres durante TODA a janela informada."""
    inicio, fim = para_naive(inicio_em), para_naive(fim_em)
    if fim <= inicio:
        raise HTTPException(status_code=422, detail="fim_em deve ser depois de inicio_em")
    expirar_vencidas(db, datetime.now())
    cap = capacidade(db)
    reservado = pico_reservado(db, dispositivo_id, inicio, fim)
    return {
        "dispositivo_id": dispositivo_id,
        "inicio_em": inicio,
        "fim_em": fim,
        "capacidade": cap,
        "reservado": reservado,
        "disponivel": max(cap - reservado, 0),
    }


@router.post("", response_model=ReservaOut, status_code=201)
def criar(dados: ReservaCreate, db: Session = Depends(get_db)):
    agora = datetime.now()

    # Regras de tempo
    if dados.inicio_em < agora - FOLGA_INICIO:
        raise HTTPException(status_code=422, detail="O inicio da reserva ja passou")
    limite = agora + timedelta(hours=settings.reserva_antecedencia_max_horas)
    if dados.inicio_em > limite:
        raise HTTPException(
            status_code=422,
            detail=f"So e possivel reservar com ate {settings.reserva_antecedencia_max_horas}h de antecedencia",
        )

    professor = db.execute(
        text("SELECT ativo FROM professores WHERE id = :id"), {"id": dados.professor_id}
    ).first()
    if professor is None:
        raise HTTPException(status_code=404, detail="Professor nao encontrado")
    if not professor.ativo:
        raise HTTPException(status_code=409, detail="Professor inativo")

    expirar_vencidas(db, agora)

    # Trava a linha do armario: duas reservas simultaneas nao conseguem passar
    # da capacidade ao mesmo tempo (a segunda espera a primeira terminar).
    dispositivo = db.execute(
        text("SELECT ativo FROM dispositivos WHERE id = :id FOR UPDATE"),
        {"id": dados.dispositivo_id},
    ).first()
    if dispositivo is None:
        raise HTTPException(status_code=404, detail="Dispositivo nao encontrado")
    if not dispositivo.ativo:
        raise HTTPException(status_code=409, detail="Dispositivo inativo")

    cap = capacidade(db)
    pico = pico_reservado(db, dados.dispositivo_id, dados.inicio_em, dados.fim_em)
    livres = max(cap - pico, 0)
    if dados.quantidade > livres:
        raise HTTPException(
            status_code=409,
            detail=f"Sem tablets suficientes nesse horario: pedido {dados.quantidade}, disponiveis {livres}",
        )

    res = db.execute(
        text(
            "INSERT INTO reservas (professor_id, dispositivo_id, quantidade, inicio_em, fim_em, observacao) "
            "VALUES (:professor_id, :dispositivo_id, :quantidade, :inicio_em, :fim_em, :observacao)"
        ),
        dados.model_dump(),
    )
    db.commit()
    return _buscar(db, res.lastrowid)


@router.get("", response_model=list[ReservaOut])
def listar(
    professor_id: Optional[int] = None,
    dispositivo_id: Optional[int] = None,
    status: Optional[StatusReserva] = None,
    de: Optional[datetime] = Query(default=None, description="Reservas que comecam a partir daqui"),
    ate: Optional[datetime] = Query(default=None, description="Reservas que comecam antes daqui"),
    limite: int = Query(default=50, ge=1, le=200),
    deslocamento: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    expirar_vencidas(db, datetime.now())
    condicoes, params = [], {"limite": limite, "deslocamento": deslocamento}
    if professor_id is not None:
        condicoes.append("r.professor_id = :professor_id")
        params["professor_id"] = professor_id
    if dispositivo_id is not None:
        condicoes.append("r.dispositivo_id = :dispositivo_id")
        params["dispositivo_id"] = dispositivo_id
    if status is not None:
        condicoes.append("r.status = :status")
        params["status"] = status
    if de is not None:
        condicoes.append("r.inicio_em >= :de")
        params["de"] = para_naive(de)
    if ate is not None:
        condicoes.append("r.inicio_em < :ate")
        params["ate"] = para_naive(ate)
    where = f"WHERE {' AND '.join(condicoes)}" if condicoes else ""
    rows = db.execute(
        text(f"{SELECT_RESERVA} {where} ORDER BY r.inicio_em DESC LIMIT :limite OFFSET :deslocamento"),
        params,
    ).mappings().all()
    return [dict(r) for r in rows]


@router.get("/{reserva_id}", response_model=ReservaOut)
def obter(reserva_id: int, db: Session = Depends(get_db)):
    expirar_vencidas(db, datetime.now())
    return _buscar(db, reserva_id)


@router.post("/{reserva_id}/cancelar", response_model=ReservaOut)
def cancelar(reserva_id: int, db: Session = Depends(get_db)):
    expirar_vencidas(db, datetime.now())
    reserva = _buscar(db, reserva_id)
    if reserva["status"] != "ativa":
        raise HTTPException(
            status_code=409,
            detail=f"Reserva {reserva['status']}: so reservas ativas podem ser canceladas",
        )
    res = db.execute(
        text("UPDATE reservas SET status = 'cancelada' WHERE id = :id AND status = 'ativa'"),
        {"id": reserva_id},
    )
    db.commit()
    if res.rowcount == 0:  # mudou de estado entre a leitura e a escrita
        raise HTTPException(status_code=409, detail="A reserva mudou de estado, tente de novo")
    return _buscar(db, reserva_id)
