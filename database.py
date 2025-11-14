from datetime import datetime
from typing import Optional
from sqlalchemy import create_engine, Column, String, Text, DateTime, Integer
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from pydantic_settings import BaseSettings

Base = declarative_base()


class Summary(Base):
    __tablename__ = "summaries"

    id = Column(Integer, primary_key=True, index=True)
    video_id = Column(String(20), unique=True, index=True, nullable=False)
    title = Column(String(500), nullable=False)
    transcript_method = Column(String(50), nullable=False)
    summary = Column(Text, nullable=False)
    cost_estimate = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class DatabaseConfig(BaseSettings):
    database_url: str = "postgresql://youtube_user:youtube_pass@localhost:5432/youtube_summaries"

    class Config:
        env_file = ".env"


# Configuración de la base de datos
config = DatabaseConfig()
engine = create_engine(config.database_url)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db():
    """Inicializa la base de datos creando todas las tablas."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """Dependency para obtener una sesión de base de datos."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
