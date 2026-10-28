import re
from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


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
