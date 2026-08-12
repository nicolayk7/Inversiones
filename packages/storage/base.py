"""Root declarative base. Concrete tables (instruments, prices_daily, trade_ideas, ...) are added
per-engine starting Phase 1 — see architecture v1.0 §05 for the full frozen schema sketch."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass
