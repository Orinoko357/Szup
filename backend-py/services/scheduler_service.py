from __future__ import annotations
import logging
from datetime import datetime, date

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from config import settings

logger = logging.getLogger(__name__)
_scheduler: BackgroundScheduler | None = None


def _get_session():
    from database import SessionLocal
    return SessionLocal()


def run_reminders():
    logger.debug("Scheduler: running reminders")
    session = _get_session()
    try:
        rows = session.execute(
            __import__("sqlalchemy").text(
                """SELECT we.id, we.wniosek_id, we.zatwierdzajacy_id, we.przypomnienie_dni,
                          w.numer, p.uzytkownik_id
                     FROM wnioski_etapy we
                     JOIN wnioski w ON w.id=we.wniosek_id
                     JOIN pracownicy p ON p.id=we.zatwierdzajacy_id
                    WHERE we.status='OCZEKUJE'
                      AND we.data_przypomnienia IS NULL
                      AND we.przypomnienie_dni IS NOT NULL
                      AND datetime(we.data_przypisania, '+' || we.przypomnienie_dni || ' days') <= datetime('now')"""
            )
        ).mappings().all()

        from services.notification_service import create_notification
        for row in rows:
            row = dict(row)
            try:
                create_notification(
                    row["uzytkownik_id"], "PRZYPOMNIENIE_ZATWIERDZENIA",
                    f"Przypomnienie: wniosek {row['numer']} oczekuje na Twoją akceptację.",
                    f"/wnioski/{row['wniosek_id']}", session,
                )
                session.execute(
                    __import__("sqlalchemy").text("UPDATE wnioski_etapy SET data_przypomnienia=:dt WHERE id=:id"),
                    {"dt": datetime.utcnow(), "id": row["id"]},
                )
                session.commit()
            except Exception as e:
                logger.error(f"Reminder error for etap {row['id']}: {e}")

        if rows:
            logger.info(f"Reminders sent: {len(rows)}")
    except Exception as e:
        logger.error(f"run_reminders failed: {e}")
    finally:
        session.close()


def run_eskalacje():
    logger.debug("Scheduler: running escalations")
    session = _get_session()
    try:
        from sqlalchemy import text
        rows = session.execute(
            text("""SELECT we.id, we.wniosek_id, we.zatwierdzajacy_id, we.eskalacja_dni,
                           w.numer, w.tenant_id,
                           przel.uzytkownik_id as przel_user_id, przel.id as przel_prac_id
                      FROM wnioski_etapy we
                      JOIN wnioski w ON w.id=we.wniosek_id
                      JOIN pracownicy p ON p.id=we.zatwierdzajacy_id
                      LEFT JOIN pracownicy przel ON przel.id=p.przelozony_id
                     WHERE we.status='OCZEKUJE'
                       AND we.data_eskalacji IS NULL
                       AND we.eskalacja_dni IS NOT NULL
                       AND datetime(we.data_przypisania, '+' || we.eskalacja_dni || ' days') <= datetime('now')""")
        ).mappings().all()

        from services.notification_service import create_notification
        from dependencies import write_audit
        for row in rows:
            row = dict(row)
            try:
                if row.get("przel_user_id"):
                    create_notification(
                        row["przel_user_id"], "ESKALACJA",
                        f"ESKALACJA: Wniosek {row['numer']} nie został zatwierdzony w terminie. Proszę o interwencję.",
                        f"/wnioski/{row['wniosek_id']}", session,
                    )
                session.execute(
                    text("UPDATE wnioski_etapy SET data_eskalacji=:dt, eskalacja_do=:eid WHERE id=:id"),
                    {"dt": datetime.utcnow(), "eid": row.get("przel_prac_id"), "id": row["id"]},
                )
                session.commit()
                write_audit(session, tenant_id=row.get("tenant_id"), akcja="ESKALACJA",
                            tabela_docelowa="wnioski_etapy", rekord_id=row["id"],
                            nowe_dane={"wniosekId": row["wniosek_id"], "eskalacjaDo": row.get("przel_prac_id")})
            except Exception as e:
                logger.error(f"Escalation error for etap {row['id']}: {e}")

        if rows:
            logger.info(f"Escalations processed: {len(rows)}")
    except Exception as e:
        logger.error(f"run_eskalacje failed: {e}")
    finally:
        session.close()


def run_nis2_reviews():
    logger.debug("Scheduler: running NIS2 reviews")
    session = _get_session()
    try:
        from sqlalchemy import text
        tenants = session.execute(
            text("SELECT id, dni_do_przegladu FROM tenants WHERE aktywny=1")
        ).mappings().all()

        from services.notification_service import notify_it
        for tenant in tenants:
            tenant = dict(tenant)
            result = session.execute(
                text("""UPDATE uprawnienia SET wymaga_przegladu=1
                         WHERE aktywne=1 AND tenant_id=:tid AND wymaga_przegladu=0
                           AND (data_ostatniego_przegladu IS NULL
                                OR date(data_ostatniego_przegladu, '+' || :dni || ' days') <= date('now'))"""),
                {"tid": tenant["id"], "dni": tenant["dni_do_przegladu"]},
            )
            session.commit()
            if result.rowcount > 0:
                notify_it("PRZEGLAD_WYMAGANY",
                           f"{result.rowcount} uprawnień w jednostce #{tenant['id']} wymaga przeglądu NIS2.",
                           "/przeglady", session)
                logger.info(f"NIS2 review flagged: {result.rowcount} for tenant {tenant['id']}")
    except Exception as e:
        logger.error(f"run_nis2_reviews failed: {e}")
    finally:
        session.close()


def run_reset_numeracji():
    logger.debug("Scheduler: checking numbering reset")
    session = _get_session()
    try:
        from sqlalchemy import text
        row = session.execute(text("SELECT * FROM konfiguracja_numeracji WHERE id=1")).mappings().first()
        if not row:
            return
        cfg = dict(row)
        today = date.today()
        last_reset_str = cfg.get("ostatni_reset")
        if not last_reset_str:
            return
        try:
            last_reset = date.fromisoformat(str(last_reset_str)[:10])
        except Exception:
            return

        needs_reset = False
        if cfg.get("reset_co") == "ROK" and last_reset.year < today.year:
            needs_reset = True
        elif cfg.get("reset_co") == "MIESIAC":
            if last_reset.year < today.year or (last_reset.year == today.year and last_reset.month < today.month):
                needs_reset = True

        if needs_reset:
            session.execute(
                text("UPDATE konfiguracja_numeracji SET ostatni_numer=0, ostatni_reset=:d WHERE id=1"),
                {"d": today.isoformat()},
            )
            session.commit()
            logger.info("Numbering sequence reset")
    except Exception as e:
        logger.error(f"run_reset_numeracji failed: {e}")
    finally:
        session.close()


def start():
    global _scheduler
    if not settings.SCHEDULER_ENABLED:
        logger.info("Scheduler disabled (SCHEDULER_ENABLED=false)")
        return

    _scheduler = BackgroundScheduler()

    _scheduler.add_job(run_reminders, CronTrigger(hour=8, minute=0), id="reminders", replace_existing=True)
    _scheduler.add_job(run_eskalacje, CronTrigger(hour=8, minute=30), id="escalations", replace_existing=True)
    _scheduler.add_job(run_nis2_reviews, CronTrigger(hour=9, minute=0), id="nis2_reviews", replace_existing=True)
    _scheduler.add_job(run_reset_numeracji, CronTrigger(hour=0, minute=5), id="reset_numeracji", replace_existing=True)

    _scheduler.start()
    logger.info("Scheduler started")


def stop():
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown()
        logger.info("Scheduler stopped")
