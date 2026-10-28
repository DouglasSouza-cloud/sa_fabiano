from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError


def erro_duplicado(erro: IntegrityError, mensagens: dict[str, str]) -> HTTPException:
    """Traduz erro de chave unica do MySQL numa resposta 409 que diz qual campo repetiu."""
    texto = str(erro.orig)
    for coluna, mensagem in mensagens.items():
        if coluna in texto:
            return HTTPException(status_code=409, detail=mensagem)
    return HTTPException(status_code=409, detail="Registro duplicado ou invalido")


def montar_update(tabela: str, campos: dict) -> tuple[str, dict]:
    """Monta 'UPDATE ... SET a=:a, b=:b WHERE id=:id'. As chaves vem dos
    modelos Pydantic (lista fixa), nunca direto do usuario."""
    sets = ", ".join(f"{c} = :{c}" for c in campos)
    return f"UPDATE {tabela} SET {sets} WHERE id = :id", campos
