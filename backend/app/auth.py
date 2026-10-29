import hashlib
from datetime import datetime
from typing import Optional

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import get_db


def dispositivo_autenticado(
    request: Request,
    x_device_key: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
) -> dict:
    """Identifica o ESP32 pela chave enviada no cabecalho X-Device-Key.
    O banco guarda so o SHA-256 da chave (gerada em POST /dispositivos)."""
    if not x_device_key or not x_device_key.strip():
        raise HTTPException(status_code=401, detail="Chave do dispositivo ausente (cabecalho X-Device-Key)")

    chave_hash = hashlib.sha256(x_device_key.strip().encode()).hexdigest()
    dispositivo = db.execute(
        text("SELECT id, identificador, ativo, simulado FROM dispositivos WHERE chave_hash = :h"),
        {"h": chave_hash},
    ).mappings().first()
    if dispositivo is None:
        raise HTTPException(status_code=401, detail="Chave do dispositivo invalida")
    if not dispositivo["ativo"]:
        raise HTTPException(status_code=403, detail="Dispositivo inativo")

    # Qualquer chamada autenticada conta como "o dispositivo esta vivo"
    db.execute(
        text("UPDATE dispositivos SET ultimo_contato_em = :agora, ultimo_ip = :ip WHERE id = :id"),
        {
            "agora": datetime.now(),
            "ip": request.client.host if request.client else None,
            "id": dispositivo["id"],
        },
    )
    db.commit()
    return dict(dispositivo)
