from __future__ import annotations
import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def create_notification(user_id: int, typ: str, tresc: str, link: Optional[str], session: Session):
    if not user_id:
        return
    try:
        from datetime import datetime
        session.execute(
            text("INSERT INTO powiadomienia (user_id,typ,tresc,link,data_utworzenia) VALUES (:uid,:t,:tr,:l,:dt)"),
            {"uid": user_id, "t": typ, "tr": tresc, "l": link, "dt": datetime.utcnow()},
        )
        session.commit()
    except Exception as e:
        logger.error(f"Failed to create notification: {e}")
        try:
            session.rollback()
        except Exception:
            pass


def notify_role(rola: str, typ: str, tresc: str, link: Optional[str], session: Session,
                tenant_id: Optional[int] = None):
    try:
        if tenant_id:
            rows = session.execute(
                text("SELECT id FROM uzytkownicy WHERE rola=:r AND aktywny=1 AND tenant_id=:tid"),
                {"r": rola, "tid": tenant_id},
            ).mappings().all()
        else:
            rows = session.execute(
                text("SELECT id FROM uzytkownicy WHERE rola=:r AND aktywny=1"),
                {"r": rola},
            ).mappings().all()
        for u in rows:
            create_notification(u["id"], typ, tresc, link, session)
    except Exception as e:
        logger.error(f"Failed to notify role {rola}: {e}")


def notify_it(typ: str, tresc: str, link: Optional[str], session: Session):
    notify_role("IT_ADMIN", typ, tresc, link, session)
