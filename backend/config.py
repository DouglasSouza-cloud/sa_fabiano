from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Banco de dados
    db_host: str = "localhost"
    db_port: int = 3306
    db_user: str = "heimdall"
    db_password: str = ""
    db_name: str = "heimdall"

    # Regras de reserva (ajustar aqui nao mexe no banco)
    reserva_antecedencia_max_horas: int = 24
    reserva_tolerancia_minutos: int = 30

    @property
    def database_url(self) -> str:
        return (
            f"mysql+pymysql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}?charset=utf8mb4"
        )


settings = Settings()
