from __future__ import annotations
import os
import time
from datetime import datetime
from typing import Optional

from sqlalchemy import create_engine, Column, String, Integer, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker, Session

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./legalgenius.db")
# For SQLite, need check_same_thread=False when used with FastAPI threads
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class UserCredit(Base):
    __tablename__ = "user_credits"

    user_id = Column(String, primary_key=True)
    email = Column(String, nullable=True)

    # Euro-based balance (in cents)
    euro_balance_cents = Column(Integer, default=0, nullable=False)
    total_spent_cents = Column(Integer, default=0, nullable=False)

    # Lifetime token usage counters (for analytics/visibility)
    total_in_used = Column(Integer, default=0, nullable=False)
    total_out_used = Column(Integer, default=0, nullable=False)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def as_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "email": self.email,
            "euro_balance_cents": self.euro_balance_cents,
            "total_spent_cents": self.total_spent_cents,
            "total_in_used": self.total_in_used,
            "total_out_used": self.total_out_used,
            "updated_at": int(self.updated_at.timestamp()),
            "created_at": int(self.created_at.timestamp()),
        }


def init_db() -> None:
    Base.metadata.create_all(bind=engine)
    # Lightweight migration: ensure new euro columns exist
    try:
        if DATABASE_URL.startswith("sqlite"):
            with engine.connect() as conn:
                # Fetch current columns
                res = conn.exec_driver_sql("PRAGMA table_info(user_credits)")
                cols = {row[1] for row in res.fetchall()}  # row[1] = name
                if "euro_balance_cents" not in cols:
                    conn.exec_driver_sql("ALTER TABLE user_credits ADD COLUMN euro_balance_cents INTEGER NOT NULL DEFAULT 0")
                if "total_spent_cents" not in cols:
                    conn.exec_driver_sql("ALTER TABLE user_credits ADD COLUMN total_spent_cents INTEGER NOT NULL DEFAULT 0")
                if "total_in_used" not in cols:
                    conn.exec_driver_sql("ALTER TABLE user_credits ADD COLUMN total_in_used INTEGER NOT NULL DEFAULT 0")
                if "total_out_used" not in cols:
                    conn.exec_driver_sql("ALTER TABLE user_credits ADD COLUMN total_out_used INTEGER NOT NULL DEFAULT 0")
    except Exception:
        # Best-effort; avoid blocking startup
        pass


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_or_create_user(db: Session, user_id: str, email: Optional[str]) -> UserCredit:
    uc: Optional[UserCredit] = db.get(UserCredit, user_id)
    if uc is None:
        uc = UserCredit(user_id=user_id, email=email or None)
        db.add(uc)
        db.commit()
        db.refresh(uc)
    else:
        # keep most recent email if changed
        if email and uc.email != email:
            uc.email = email
            uc.updated_at = datetime.utcnow()
            db.add(uc)
            db.commit()
            db.refresh(uc)
    return uc


def _price_in_eur_per_1k() -> float:
    try:
        return float(os.environ.get("PRICE_IN_EUR_PER_1K", "0.002"))
    except Exception:
        return 0.002


def _price_out_eur_per_1k() -> float:
    try:
        return float(os.environ.get("PRICE_OUT_EUR_PER_1K", "0.006"))
    except Exception:
        return 0.006


def deduct_tokens(db: Session, user_id: str, tokens_in: int, tokens_out: int) -> UserCredit:
    uc: Optional[UserCredit] = db.get(UserCredit, user_id)
    if uc is None:
        raise ValueError("UserCredit not found for user_id")
    # Update usage
    uc.total_in_used += max(0, int(tokens_in or 0))
    uc.total_out_used += max(0, int(tokens_out or 0))

    # Compute euro cost based on per-1K token pricing
    price_in = _price_in_eur_per_1k()
    price_out = _price_out_eur_per_1k()
    cost_eur = (max(0, int(tokens_in or 0)) / 1000.0) * price_in + (max(0, int(tokens_out or 0)) / 1000.0) * price_out
    cost_cents = int(round(cost_eur * 100))
    uc.euro_balance_cents -= cost_cents
    uc.total_spent_cents += cost_cents
    uc.updated_at = datetime.utcnow()
    db.add(uc)
    db.commit()
    db.refresh(uc)
    return uc


def set_credits(db: Session, user_id: str, euro_balance_cents: Optional[int] = None, email: Optional[str] = None) -> UserCredit:
    uc = db.get(UserCredit, user_id)
    if uc is None:
        # Detect legacy columns that might still exist in the SQLite table, e.g. 'in_balance'/'out_balance'
        legacy_cols: set[str] = set()
        try:
            # Works for SQLite; for other DBs it's harmless if it fails
            # Use engine.connect() to avoid closing the Session's connection
            with engine.connect() as conn:
                res = conn.exec_driver_sql("PRAGMA table_info(user_credits)")
                cols = {row[1] for row in res.fetchall()}  # row[1] is the column name
                if "in_balance" in cols:
                    legacy_cols.add("in_balance")
                if "out_balance" in cols:
                    legacy_cols.add("out_balance")
        except Exception:
            pass

        # If legacy NOT NULL columns exist, perform a manual INSERT that populates them
        if legacy_cols:
            now = datetime.utcnow()
            euro_cents_val = int(euro_balance_cents) if euro_balance_cents is not None else 0
            total_spent = 0
            total_in_used = 0
            total_out_used = 0

            # Build dynamic SQL including legacy columns when present
            cols = [
                "user_id", "email", "euro_balance_cents", "total_spent_cents",
                "total_in_used", "total_out_used", "created_at", "updated_at",
            ]
            vals = [
                user_id, (email or None), euro_cents_val, total_spent,
                total_in_used, total_out_used, now, now,
            ]
            if "in_balance" in legacy_cols:
                cols.append("in_balance")
                vals.append(0)
            if "out_balance" in legacy_cols:
                cols.append("out_balance")
                vals.append(0)

            placeholders = ", ".join([":" + str(i) for i in range(len(vals))])
            col_list = ", ".join(cols)

            try:
                # Use engine.connect() to avoid interfering with the Session lifecycle
                with engine.connect() as conn:
                    conn.exec_driver_sql(
                        f"INSERT INTO user_credits ({col_list}) VALUES ({placeholders})",
                        {str(i): vals[i] for i in range(len(vals))},
                    )
                    # Explicitly commit so the ORM session can see the row
                    conn.commit()
                # Make sure the ORM session can see the newly inserted row
                try:
                    db.expire_all()
                except Exception:
                    pass
                # Retrieve ORM instance after manual insert
                uc = db.get(UserCredit, user_id)
                if uc is None:
                    # As a fallback, fetch via raw SQL and merge into the session
                    try:
                        with engine.connect() as conn:
                            res = conn.exec_driver_sql(
                                "SELECT user_id, email, euro_balance_cents, total_spent_cents, total_in_used, total_out_used, created_at, updated_at FROM user_credits WHERE user_id = :uid",
                                {"uid": user_id},
                            )
                            row = res.fetchone()
                        if row:
                            uc = UserCredit(
                                user_id=row[0],
                                email=row[1],
                                euro_balance_cents=row[2],
                                total_spent_cents=row[3],
                                total_in_used=row[4],
                                total_out_used=row[5],
                            )
                            # created_at / updated_at will be refreshed after merge
                            uc = db.merge(uc)
                    except Exception:
                        pass
            except Exception:
                # Fallback to ORM creation if manual insert fails for any reason
                uc = UserCredit(user_id=user_id, email=email or None)
        else:
            # Normal path: use ORM to create a new row
            uc = UserCredit(user_id=user_id, email=email or None)

    # Apply updates/overrides
    if euro_balance_cents is not None:
        uc.euro_balance_cents = int(euro_balance_cents)
    if email and uc.email != email:
        uc.email = email
    uc.updated_at = datetime.utcnow()
    db.add(uc)
    db.commit()
    db.refresh(uc)
    return uc
