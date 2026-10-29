import re
from datetime import datetime
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator


def normalizar_uid(valor: str) -> str:
    """Aceita '01:02:03:04', '01-02-03-04' ou '01020304' e devolve '01:02:03:04'."""
    limpo = re.sub(r"[\s:\-]", "", valor).upper()
    if not re.fullmatch(r"[0-9A-F]+", limpo) or len(limpo) not in (8, 14, 20):
        raise ValueError("UID invalido: use 4, 7 ou 10 bytes em hexadecimal, ex.: 01:02:03:04")
    return ":".join(limpo[i:i + 2] for i in range(0, len(limpo), 2))


def normalizar_epc(valor: str) -> str:
    limpo = re.sub(r"[\s:\-]", "", valor).upper()
    if not re.fullmatch(r"[0-9A-F]{8,48}", limpo):
        raise ValueError("EPC invalido: use de 8 a 48 caracteres hexadecimais")
    return limpo


# ---------------- Professores ----------------

class ProfessorCreate(BaseModel):
    nome: str = Field(min_length=1, max_length=150)
    matricula: str = Field(min_length=1, max_length=40)
    uid_cracha: str

    @field_validator("nome", "matricula")
    @classmethod
    def sem_espacos_nas_pontas(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("nao pode ficar vazio")
        return v

    @field_validator("uid_cracha")
    @classmethod
    def validar_uid(cls, v: str) -> str:
        return normalizar_uid(v)


class ProfessorUpdate(BaseModel):
    nome: Optional[str] = Field(default=None, min_length=1, max_length=150)
    matricula: Optional[str] = Field(default=None, min_length=1, max_length=40)
    uid_cracha: Optional[str] = None
    ativo: Optional[bool] = None

    @field_validator("nome", "matricula")
    @classmethod
    def sem_espacos_nas_pontas(cls, v):
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("nao pode ficar vazio")
        return v

    @field_validator("uid_cracha")
    @classmethod
    def validar_uid(cls, v):
        return None if v is None else normalizar_uid(v)


class ProfessorOut(BaseModel):
    id: int
    nome: str
    matricula: str
    uid_cracha: str
    ativo: bool
    criado_em: datetime
    atualizado_em: datetime


# ---------------- Tablets ----------------

StatusTablet = Literal["disponivel", "emprestado", "manutencao", "indisponivel", "reservado"]
# Status que uma pessoa pode definir na mao. 'emprestado' e controlado pelas
# retiradas; 'reservado' nao e mais usado (a reserva e por quantidade).
StatusManual = Literal["disponivel", "manutencao", "indisponivel"]


class TabletCreate(BaseModel):
    patrimonio: str = Field(min_length=1, max_length=40)
    epc: str
    marca: Optional[str] = Field(default=None, max_length=60)
    modelo: Optional[str] = Field(default=None, max_length=80)
    numero_serie: Optional[str] = Field(default=None, max_length=80)

    @field_validator("patrimonio")
    @classmethod
    def limpar_patrimonio(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("nao pode ficar vazio")
        return v

    @field_validator("epc")
    @classmethod
    def validar_epc(cls, v: str) -> str:
        return normalizar_epc(v)


class TabletUpdate(BaseModel):
    patrimonio: Optional[str] = Field(default=None, min_length=1, max_length=40)
    epc: Optional[str] = None
    marca: Optional[str] = Field(default=None, max_length=60)
    modelo: Optional[str] = Field(default=None, max_length=80)
    numero_serie: Optional[str] = Field(default=None, max_length=80)
    status: Optional[StatusManual] = None

    @field_validator("patrimonio")
    @classmethod
    def limpar_patrimonio(cls, v):
        if v is None:
            return v
        v = v.strip()
        if not v:
            raise ValueError("nao pode ficar vazio")
        return v

    @field_validator("epc")
    @classmethod
    def validar_epc(cls, v):
        return None if v is None else normalizar_epc(v)


class TabletOut(BaseModel):
    id: int
    patrimonio: str
    epc: str
    marca: Optional[str]
    modelo: Optional[str]
    numero_serie: Optional[str]
    status: StatusTablet
    criado_em: datetime
    atualizado_em: datetime


# ---------------- Dispositivos (armarios / ESP32) ----------------

class DispositivoCreate(BaseModel):
    identificador: str = Field(min_length=1, max_length=60, pattern=r"^[A-Za-z0-9_\-]+$")
    nome: str = Field(min_length=1, max_length=120)
    simulado: bool = False

    @field_validator("nome")
    @classmethod
    def limpar_nome(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("nao pode ficar vazio")
        return v


class DispositivoUpdate(BaseModel):
    nome: Optional[str] = Field(default=None, min_length=1, max_length=120)
    ativo: Optional[bool] = None


class DispositivoOut(BaseModel):
    id: int
    identificador: str
    nome: str
    ativo: bool
    simulado: bool
    ultimo_contato_em: Optional[datetime]
    ultimo_ip: Optional[str]
    criado_em: datetime


class DispositivoCriado(DispositivoOut):
    chave: str = Field(description="Aparece so agora. Guarde: o banco guarda apenas o hash.")


# ---------------- Reservas ----------------

StatusReserva = Literal["ativa", "em_uso", "concluida", "cancelada", "expirada"]


def para_naive(dt: datetime) -> datetime:
    """O banco guarda DATETIME sem fuso. Se vier com fuso, converte para o horario local."""
    if dt.tzinfo is not None:
        dt = dt.astimezone().replace(tzinfo=None)
    return dt.replace(microsecond=0)


class ReservaCreate(BaseModel):
    professor_id: int = Field(gt=0)
    dispositivo_id: int = Field(gt=0)
    quantidade: int = Field(gt=0, le=500)
    inicio_em: datetime
    fim_em: datetime
    observacao: Optional[str] = Field(default=None, max_length=500)

    @field_validator("inicio_em", "fim_em")
    @classmethod
    def sem_fuso(cls, v: datetime) -> datetime:
        return para_naive(v)

    @model_validator(mode="after")
    def periodo_valido(self):
        if self.fim_em <= self.inicio_em:
            raise ValueError("fim_em deve ser depois de inicio_em")
        return self


class ReservaOut(BaseModel):
    id: int
    professor_id: int
    professor_nome: str
    dispositivo_id: int
    quantidade: int
    inicio_em: datetime
    fim_em: datetime
    status: StatusReserva
    observacao: Optional[str]
    criada_em: datetime
    atualizada_em: datetime


class DisponibilidadeOut(BaseModel):
    dispositivo_id: int
    inicio_em: datetime
    fim_em: datetime
    capacidade: int
    reservado: int
    disponivel: int


# ---------------- Eventos do armario (enviados pelo ESP32) ----------------

class EventoBase(BaseModel):
    # Identifica o envio. Se o ESP32 reenviar (rede caiu), a API reconhece e nao duplica.
    request_id: str = Field(min_length=1, max_length=64)
    lido_em: Optional[datetime] = None

    @field_validator("lido_em")
    @classmethod
    def lido_sem_fuso(cls, v):
        return None if v is None else para_naive(v)


class EventoCracha(EventoBase):
    tipo: Literal["cracha"]
    uid_cracha: str

    @field_validator("uid_cracha")
    @classmethod
    def validar_uid(cls, v: str) -> str:
        return normalizar_uid(v)


class EventoInventario(EventoBase):
    tipo: Literal["inventario"]
    epcs: list[str] = Field(max_length=500)
    completo: bool
    qualidade: Optional[float] = Field(default=None, ge=0, le=1)
    inventario_id: Optional[str] = Field(default=None, max_length=64)
    num_leituras: int = Field(default=0, ge=0)

    @field_validator("epcs")
    @classmethod
    def normalizar_lista(cls, v: list[str]) -> list[str]:
        # Normaliza e remove repetidos (a mesma tag pode ser lida varias vezes)
        return sorted({normalizar_epc(e) for e in v})


class EventoPorta(EventoBase):
    tipo: Literal["porta"]
    estado: Literal["aberta", "fechada"]


class EventoHeartbeat(EventoBase):
    tipo: Literal["heartbeat"]


class EventoFalha(EventoBase):
    tipo: Literal["falha_comunicacao", "erro_leitor"]
    detalhe: Optional[str] = Field(default=None, max_length=500)


Evento = Annotated[
    Union[EventoCracha, EventoInventario, EventoPorta, EventoHeartbeat, EventoFalha],
    Field(discriminator="tipo"),
]


class ProfessorIdentificado(BaseModel):
    id: int
    nome: str


class EventoResposta(BaseModel):
    request_id: str
    tipo: str
    resultado: Literal["processado", "ignorado", "rejeitado"]
    repetido: bool = False
    detalhe: Optional[str] = None
    # crachá
    professor: Optional[ProfessorIdentificado] = None
    # inventário
    snapshot_id: Optional[int] = None
    valido: Optional[bool] = None
    total_epcs: Optional[int] = None
    epcs_desconhecidos: Optional[list[str]] = None


class EventoLogOut(BaseModel):
    id: int
    dispositivo_id: int
    request_id: str
    tipo_evento: str
    origem: str
    uid_cracha: Optional[str]
    completa: Optional[bool]
    lido_em: Optional[datetime]
    recebido_em: datetime
    resultado: str
    detalhe: Optional[str]
    snapshot_id: Optional[int]
    payload_json: Optional[dict]


class TabletNoInventario(BaseModel):
    id: int
    patrimonio: str
    epc: str


class InventarioOut(BaseModel):
    snapshot_id: int
    dispositivo_id: int
    recebido_em: datetime
    lido_em: Optional[datetime]
    completo: bool
    qualidade: Optional[float]
    valido: bool
    motivo_invalido: Optional[str]
    total_epcs: int
    tablets: list[TabletNoInventario]
    epcs_desconhecidos: list[str]
