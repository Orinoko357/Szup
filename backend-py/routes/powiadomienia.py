from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_session
from dependencies import CurrentUser, get_current_user

router = APIRouter()


@router.get("/")
async def get_unread(session: Session = Depends(get_session),
                      current_user: CurrentUser = Depends(get_current_user)):
    rows = session.execute(
        text("SELECT * FROM powiadomienia WHERE user_id=:uid AND przeczytane=0 ORDER BY data_utworzenia DESC LIMIT 20"),
        {"uid": current_user.userId},
    ).mappings().all()
    cnt = session.execute(
        text("SELECT COUNT(*) as cnt FROM powiadomienia WHERE user_id=:uid AND przeczytane=0"),
        {"uid": current_user.userId},
    ).mappings().first()
    return {"items": [dict(r) for r in rows], "nieprzeczytane": cnt["cnt"] if cnt else 0}


@router.get("/wszystkie")
async def get_all(page: int = 1, limit: int = 30,
                   session: Session = Depends(get_session),
                   current_user: CurrentUser = Depends(get_current_user)):
    offset = (page - 1) * limit
    rows = session.execute(
        text("SELECT * FROM powiadomienia WHERE user_id=:uid ORDER BY data_utworzenia DESC LIMIT :lim OFFSET :off"),
        {"uid": current_user.userId, "lim": limit, "off": offset},
    ).mappings().all()
    cnt = session.execute(
        text("SELECT COUNT(*) as cnt FROM powiadomienia WHERE user_id=:uid"),
        {"uid": current_user.userId},
    ).mappings().first()
    return {"items": [dict(r) for r in rows], "total": cnt["cnt"] if cnt else 0}


@router.patch("/{powiadomienie_id}/przeczytaj")
async def przeczytaj(powiadomienie_id: int, session: Session = Depends(get_session),
                      current_user: CurrentUser = Depends(get_current_user)):
    session.execute(
        text("UPDATE powiadomienia SET przeczytane=1 WHERE id=:id AND user_id=:uid"),
        {"id": powiadomienie_id, "uid": current_user.userId},
    )
    session.commit()
    return {"message": "Oznaczono jako przeczytane."}


@router.patch("/przeczytaj-wszystkie")
async def przeczytaj_wszystkie(session: Session = Depends(get_session),
                                current_user: CurrentUser = Depends(get_current_user)):
    result = session.execute(
        text("UPDATE powiadomienia SET przeczytane=1 WHERE user_id=:uid AND przeczytane=0"),
        {"uid": current_user.userId},
    )
    session.commit()
    return {"message": f"Oznaczono {result.rowcount} powiadomień jako przeczytane."}
