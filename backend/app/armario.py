"""Regras do armario: sessao de retirada, limite por reserva, delta do inventario
e ocorrencias.

Nenhuma funcao daqui faz commit. Quem chama (o endpoint de eventos) fecha a
transacao, entao o evento, a sessao, os itens e as ocorrencias sao gravados
juntos ou nada e gravado.
"""
import json
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.config import settings
from app.routers.reservas import expirar_vencidas, pico_reservado

INDISPONIVEIS = ("manutencao", "indisponivel")


def _lista(valor) -> list:
    if valor is None:
        return []
    return valor if isinstance(valor, list) else json.loads(valor)


def _origem(dispositivo: dict) -> str:
    return "simulacao" if dispositivo["simulado"] else "real"


# ---------------- Apoio ----------------

def trava_dispositivo(db: Session, dispositivo_id: int) -> None:
    """Um evento por vez em cada armario. Dois crachas ou inventarios simultaneos
    esperam um ao outro, entao nunca decidem em cima de dados velhos."""
    db.execute(
        text("SELECT id FROM dispositivos WHERE id = :id FOR UPDATE"), {"id": dispositivo_id}
    ).first()


def abrir_ocorrencia(
    db: Session, agora: datetime, origem: str, dispositivo_id: int, tipo: str, descricao: str,
    emprestimo_id: Optional[int] = None, tablet_id: Optional[int] = None,
    snapshot_id: Optional[int] = None,
) -> int:
    db.execute(
        text(
            "INSERT INTO ocorrencias "
            "(tipo, origem, dispositivo_id, emprestimo_id, tablet_id, snapshot_id, descricao, criada_em) "
            "VALUES (:tipo, :origem, :d, :emp, :tab, :snap, :desc, :agora)"
        ),
        {"tipo": tipo, "origem": origem, "d": dispositivo_id, "emp": emprestimo_id,
         "tab": tablet_id, "snap": snapshot_id, "desc": descricao, "agora": agora},
    )
    return 1


def expirar_sessoes(db: Session, agora: datetime) -> None:
    """Cracha passou e ninguem retirou nada dentro da janela: a sessao expira."""
    limite = agora - timedelta(minutes=settings.sessao_janela_minutos)
    db.execute(
        text(
            "UPDATE emprestimos SET status = 'expirada', fechada_em = :agora "
            "WHERE status = 'aberta' AND aberta_em <= :limite "
            "AND NOT EXISTS (SELECT 1 FROM emprestimo_itens i WHERE i.emprestimo_id = emprestimos.id)"
        ),
        {"agora": agora, "limite": limite},
    )


def concluir_reservas(db: Session, agora: datetime) -> None:
    """Reserva em uso vira 'concluida' quando nao ha mais tablet fora e o prazo acabou
    ou todos os tablets reservados ja foram retirados."""
    db.execute(
        text(
            "UPDATE reservas r SET r.status = 'concluida' "
            "WHERE r.status = 'em_uso' "
            "AND NOT EXISTS (SELECT 1 FROM emprestimos e "
            "                JOIN emprestimo_itens i ON i.emprestimo_id = e.id "
            "                WHERE e.reserva_id = r.id AND i.devolvido_em IS NULL) "
            "AND (r.fim_em <= :agora OR r.quantidade <= "
            "     (SELECT COUNT(*) FROM emprestimos e2 "
            "      JOIN emprestimo_itens i2 ON i2.emprestimo_id = e2.id WHERE e2.reserva_id = r.id))"
        ),
        {"agora": agora},
    )


def snapshot_referencia(db: Session, dispositivo_id: int) -> Optional[dict]:
    """Ultimo inventario valido aplicado: o que o armario tinha da ultima vez."""
    row = db.execute(
        text(
            "SELECT id, epcs FROM inventario_snapshots "
            "WHERE dispositivo_id = :d AND referencia = TRUE ORDER BY id DESC LIMIT 1"
        ),
        {"d": dispositivo_id},
    ).mappings().first()
    if row is None:
        return None
    return {"id": row["id"], "epcs": _lista(row["epcs"])}


def _tablets_por_epc(db: Session, epcs) -> dict:
    epcs = list(epcs)
    if not epcs:
        return {}
    consulta = text(
        "SELECT id, epc, patrimonio, status FROM tablets WHERE epc IN :epcs"
    ).bindparams(bindparam("epcs", expanding=True))
    return {r["epc"]: dict(r) for r in db.execute(consulta, {"epcs": epcs}).mappings()}


def _usaveis(db: Session, epcs) -> int:
    return sum(1 for t in _tablets_por_epc(db, epcs).values() if t["status"] not in INDISPONIVEIS)


def janela_aberta(db: Session, dispositivo_id: int, agora: datetime) -> Optional[dict]:
    """Sessao esperando retirada: cracha passou, ainda sem tablet ligado a ela."""
    limite = agora - timedelta(minutes=settings.sessao_janela_minutos)
    row = db.execute(
        text(
            "SELECT e.id, e.professor_id, e.reserva_id, e.aberta_em, p.nome AS professor_nome "
            "FROM emprestimos e JOIN professores p ON p.id = e.professor_id "
            "WHERE e.dispositivo_id = :d AND e.status = 'aberta' AND e.aberta_em > :limite "
            "AND NOT EXISTS (SELECT 1 FROM emprestimo_itens i WHERE i.emprestimo_id = e.id) "
            "ORDER BY e.id DESC LIMIT 1"
        ),
        {"d": dispositivo_id, "limite": limite},
    ).mappings().first()
    return dict(row) if row else None


# ---------------- Limites ----------------

def restante_da_reserva(db: Session, reserva_id: int, quantidade: int) -> int:
    """Quantos tablets a reserva ainda pode retirar (conta tudo que ja saiu por ela)."""
    usados = db.execute(
        text(
            "SELECT COUNT(*) FROM emprestimo_itens i JOIN emprestimos e ON e.id = i.emprestimo_id "
            "WHERE e.reserva_id = :r"
        ),
        {"r": reserva_id},
    ).scalar()
    return quantidade - usados


def limite_sem_reserva(db: Session, dispositivo_id: int, ref_epcs: list, a_partir_de: datetime) -> int:
    """Retirada sem reserva: o que esta no armario, menos o que ainda vai ser pego por
    reservas que comecam dentro do horizonte. Reserva ja em uso so desconta o que falta retirar."""
    presentes = _usaveis(db, ref_epcs)
    fim = a_partir_de + timedelta(minutes=settings.retirada_livre_horizonte_minutos)
    ativas = pico_reservado(db, dispositivo_id, a_partir_de, fim, status=("ativa",))
    em_uso = db.execute(
        text(
            "SELECT COALESCE(SUM(GREATEST(r.quantidade - "
            "  (SELECT COUNT(*) FROM emprestimos e JOIN emprestimo_itens i ON i.emprestimo_id = e.id "
            "   WHERE e.reserva_id = r.id), 0)), 0) "
            "FROM reservas r WHERE r.dispositivo_id = :d AND r.status = 'em_uso' "
            "AND r.inicio_em < :fim AND r.fim_em > :ini"
        ),
        {"d": dispositivo_id, "fim": fim, "ini": a_partir_de},
    ).scalar()
    return max(presentes - ativas - int(em_uso), 0)


# ---------------- Cracha: abre a sessao ----------------

def abrir_sessao(db: Session, dispositivo: dict, professor: dict, request_id: str, agora: datetime):
    """Decide se o armario destrava e abre a sessao de retirada.
    Devolve (resultado, detalhe, extras) no formato da resposta do evento."""
    d = dispositivo["id"]
    origem = _origem(dispositivo)
    ident = {"id": professor["id"], "nome": professor["nome"]}

    def negar(motivo: str):
        return "rejeitado", motivo, {"professor": ident, "destravar": False}

    expirar_vencidas(db, agora, commit=False)
    expirar_sessoes(db, agora)

    ref = snapshot_referencia(db, d)
    if ref is None:
        return negar("Armario ainda sem inventario: aguarde a primeira leitura")

    janela = janela_aberta(db, d, agora)
    if janela and janela["professor_id"] != professor["id"]:
        abrir_ocorrencia(
            db, agora, origem, d, "sessoes_concorrentes",
            f"{professor['nome']} passou o cracha durante a sessao #{janela['id']} de {janela['professor_nome']}",
            emprestimo_id=janela["id"],
        )
        return negar("Outra sessao de retirada esta em andamento")

    # Reserva vigente do professor (comecou e ainda nao terminou)
    reserva = db.execute(
        text(
            "SELECT id, quantidade FROM reservas WHERE professor_id = :p AND dispositivo_id = :d "
            "AND status IN ('ativa', 'em_uso') AND inicio_em <= :agora AND fim_em > :agora "
            "ORDER BY inicio_em LIMIT 1"
        ),
        {"p": professor["id"], "d": d, "agora": agora},
    ).mappings().first()

    reserva_id, limite = None, 0
    if reserva:
        restante = restante_da_reserva(db, reserva["id"], reserva["quantidade"])
        if restante > 0:
            reserva_id = reserva["id"]
            limite = min(restante, _usaveis(db, ref["epcs"]))
    if reserva_id is None:
        limite = limite_sem_reserva(db, d, ref["epcs"], agora)

    if limite <= 0:
        return negar("Sem tablets disponiveis para retirada")

    if janela:  # mesmo professor passou o cracha de novo: reaproveita a sessao
        emprestimo_id = janela["id"]
    else:
        emprestimo_id = db.execute(
            text(
                "INSERT INTO emprestimos (professor_id, dispositivo_id, reserva_id, request_id, origem, "
                " status, aberta_em, snapshot_inicial_id) "
                "VALUES (:p, :d, :r, :req, :origem, 'aberta', :agora, :snap)"
            ),
            {"p": professor["id"], "d": d, "r": reserva_id, "req": request_id,
             "origem": origem, "agora": agora, "snap": ref["id"]},
        ).lastrowid

    return "processado", None, {
        "professor": ident, "destravar": True, "emprestimo_id": emprestimo_id,
        "reserva_id": reserva_id, "limite": limite,
    }


# ---------------- Inventario: delta -> retirada / devolucao ----------------

def processar_inventario(
    db: Session, dispositivo: dict, snapshot_id: int, epcs: list, desconhecidos: list, agora: datetime
) -> dict:
    """Aplica um inventario VALIDO: fecha devolucoes, registra retiradas na sessao
    aberta, abre ocorrencias e passa a ser a nova referencia."""
    d = dispositivo["id"]
    origem = _origem(dispositivo)
    atuais = set(epcs)
    n_ocorr = 0

    expirar_vencidas(db, agora, commit=False)
    expirar_sessoes(db, agora)
    ref = snapshot_referencia(db, d)
    janela = janela_aberta(db, d, agora)
    retirados, devolvidos = [], []
    resumo = {}

    # ---- Devolucoes: tablet com emprestimo aberto que apareceu no armario
    abertos = []
    if atuais:
        consulta = text(
            "SELECT i.id AS item_id, i.emprestimo_id, i.tablet_id, e.professor_id, t.patrimonio "
            "FROM emprestimo_itens i JOIN emprestimos e ON e.id = i.emprestimo_id "
            "JOIN tablets t ON t.id = i.tablet_id "
            "WHERE i.devolvido_em IS NULL AND t.epc IN :epcs"
        ).bindparams(bindparam("epcs", expanding=True))
        abertos = db.execute(consulta, {"epcs": list(atuais)}).mappings().all()

    quem_devolve = janela["professor_id"] if janela else None
    afetados = set()
    for it in abertos:
        db.execute(
            text(
                "UPDATE emprestimo_itens SET devolvido_em = :agora, snapshot_devolucao_id = :snap, "
                "devolvido_por_professor_id = :prof WHERE id = :id"
            ),
            {"agora": agora, "snap": snapshot_id, "prof": quem_devolve, "id": it["item_id"]},
        )
        db.execute(
            text("UPDATE tablets SET status = 'disponivel' WHERE id = :t AND status = 'emprestado'"),
            {"t": it["tablet_id"]},
        )
        devolvidos.append(it["patrimonio"])
        afetados.add(it["emprestimo_id"])
        if quem_devolve is not None and quem_devolve != it["professor_id"]:
            n_ocorr += abrir_ocorrencia(
                db, agora, origem, d, "devolucao_outro_professor",
                f"Tablet {it['patrimonio']} devolvido na sessao de outro professor "
                f"(emprestimo #{it['emprestimo_id']})",
                emprestimo_id=it["emprestimo_id"], tablet_id=it["tablet_id"], snapshot_id=snapshot_id,
            )
    for emp_id in afetados:
        restam = db.execute(
            text("SELECT COUNT(*) FROM emprestimo_itens WHERE emprestimo_id = :e AND devolvido_em IS NULL"),
            {"e": emp_id},
        ).scalar()
        if restam == 0:
            db.execute(
                text("UPDATE emprestimos SET status = 'fechada', fechada_em = :agora "
                     "WHERE id = :e AND status = 'aberta'"),
                {"agora": agora, "e": emp_id},
            )

    # ---- Tablets que voltaram apos sumirem sem sessao: resolve a ocorrencia sozinho
    presentes = _tablets_por_epc(db, atuais)
    if presentes:
        consulta = text(
            "UPDATE ocorrencias SET status = 'resolvida', resolvida_em = :agora, "
            "resolucao = 'Tablet voltou ao armario (inventario automatico)' "
            "WHERE tipo = 'retirada_sem_sessao' AND status = 'aberta' AND tablet_id IN :ids"
        ).bindparams(bindparam("ids", expanding=True))
        db.execute(consulta, {"agora": agora, "ids": [t["id"] for t in presentes.values()]})

    # ---- Retiradas: estava no inventario anterior e nao esta mais
    if ref is not None:
        saiu = _tablets_por_epc(db, [e for e in ref["epcs"] if e not in atuais])
        sairam = []
        for t in saiu.values():
            ja_fora = db.execute(
                text("SELECT 1 FROM emprestimo_itens WHERE tablet_id = :t AND devolvido_em IS NULL"),
                {"t": t["id"]},
            ).first()
            if ja_fora:
                n_ocorr += abrir_ocorrencia(
                    db, agora, origem, d, "outro",
                    f"Tablet {t['patrimonio']} sumiu do armario mas ja constava como emprestado",
                    tablet_id=t["id"], snapshot_id=snapshot_id,
                )
            else:
                sairam.append(t)

        if sairam and janela is None:
            for t in sairam:
                n_ocorr += abrir_ocorrencia(
                    db, agora, origem, d, "retirada_sem_sessao",
                    f"Tablet {t['patrimonio']} saiu do armario sem cracha",
                    tablet_id=t["id"], snapshot_id=snapshot_id,
                )
        elif sairam:
            if janela["reserva_id"]:
                qtd = db.execute(
                    text("SELECT quantidade FROM reservas WHERE id = :r"), {"r": janela["reserva_id"]}
                ).scalar()
                limite = restante_da_reserva(db, janela["reserva_id"], qtd)
            else:
                limite = limite_sem_reserva(db, d, ref["epcs"], janela["aberta_em"])

            for t in sairam:
                db.execute(
                    text(
                        "INSERT INTO emprestimo_itens (emprestimo_id, tablet_id, retirado_em, snapshot_retirada_id) "
                        "VALUES (:e, :t, :agora, :snap)"
                    ),
                    {"e": janela["id"], "t": t["id"], "agora": agora, "snap": snapshot_id},
                )
                db.execute(
                    text("UPDATE tablets SET status = 'emprestado' "
                         "WHERE id = :t AND status IN ('disponivel', 'reservado')"),
                    {"t": t["id"]},
                )
                retirados.append(t["patrimonio"])
                if t["status"] in INDISPONIVEIS:
                    n_ocorr += abrir_ocorrencia(
                        db, agora, origem, d, "tablet_indisponivel_retirado",
                        f"Tablet {t['patrimonio']} ({t['status']}) foi retirado por {janela['professor_nome']}",
                        emprestimo_id=janela["id"], tablet_id=t["id"], snapshot_id=snapshot_id,
                    )
            if janela["reserva_id"]:
                db.execute(
                    text("UPDATE reservas SET status = 'em_uso' WHERE id = :r AND status = 'ativa'"),
                    {"r": janela["reserva_id"]},
                )
            if len(sairam) > limite:
                n_ocorr += abrir_ocorrencia(
                    db, agora, origem, d, "retirada_acima_do_limite",
                    f"{janela['professor_nome']} retirou {len(sairam)} tablets, permitido {max(limite, 0)}: "
                    + ", ".join(t["patrimonio"] for t in sairam),
                    emprestimo_id=janela["id"], snapshot_id=snapshot_id,
                )
            resumo["emprestimo_id"] = janela["id"]

        # Cracha so para devolver: a sessao cumpriu o papel e fecha
        if not sairam and devolvidos and janela is not None:
            db.execute(
                text("UPDATE emprestimos SET status = 'fechada', fechada_em = :agora "
                     "WHERE id = :e AND status = 'aberta'"),
                {"agora": agora, "e": janela["id"]},
            )
            resumo["emprestimo_id"] = janela["id"]

    # ---- Tags que nao estao no cadastro (uma ocorrencia aberta por tag)
    for epc in desconhecidos:
        existe = db.execute(
            text(
                "SELECT 1 FROM ocorrencias WHERE tipo = 'epc_desconhecido' AND status = 'aberta' "
                "AND dispositivo_id = :d AND descricao LIKE :pad LIMIT 1"
            ),
            {"d": d, "pad": f"%{epc}%"},
        ).first()
        if not existe:
            n_ocorr += abrir_ocorrencia(
                db, agora, origem, d, "epc_desconhecido",
                f"Tag {epc} detectada no armario e nao cadastrada", snapshot_id=snapshot_id,
            )

    # ---- Este inventario passa a ser a referencia
    db.execute(
        text("UPDATE inventario_snapshots SET referencia = FALSE WHERE dispositivo_id = :d AND referencia = TRUE"),
        {"d": d},
    )
    db.execute(
        text("UPDATE inventario_snapshots SET referencia = TRUE, confirmado = TRUE WHERE id = :s"),
        {"s": snapshot_id},
    )
    concluir_reservas(db, agora)

    resumo.update({"retirados": retirados, "devolvidos": devolvidos, "ocorrencias_abertas": n_ocorr})
    return resumo
