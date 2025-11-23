from sqlalchemy.orm import declarative_base, sessionmaker
from sqlalchemy import create_engine, Column, String, Float, DateTime, Integer, ForeignKey, Index

# SQLite файл рядом с приложением
engine = create_engine("sqlite:///meteo.db", echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

Base = declarative_base()

class Station(Base):
    __tablename__ = "stations"
    id   = Column(String(32), primary_key=True)   # используем code как id
    code = Column(String(32), unique=True, index=True)
    name = Column(String(128))
    lat  = Column(Float, nullable=True)
    lon  = Column(Float, nullable=True)

class Measurement(Base):
    __tablename__ = "measurements"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    ts          = Column(DateTime, index=True)            # UTC
    station_id  = Column(String(32), ForeignKey("stations.id"), index=True)
    field       = Column(String(8), index=True)           # Sa0, Ta1, Hr1, Pa2 ...
    sensor_idx  = Column(Integer, nullable=True)          # резерв под id внутри поля
    value       = Column(Float, nullable=True)

Index("idx_meas_station_ts_field", Measurement.station_id, Measurement.ts, Measurement.field)
