from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from auth import (
    build_token_payload,
    create_access_token,
    create_refresh_token,
    hash_token,
    verify_password,
    verify_refresh_token,
)
from config import settings
from database import get_session
from dependencies import CurrentUser, get_client_ip, get_current_user, write_audit
from services.ldap_service import ldap_authenticate

router = APIRouter()

REFRESH_COOKIE = "refreshToken"
REFRESH_MAX_AGE = 7 * 24 * 60 * 60


def _set_refresh_cookie(response: Response, token: str):
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=token,
        httponly=True,
        secure=settings.is_production,
        samesite="lax",
        max_age=REFRESH_MAX_AGE,
    )


def _store_refresh_token(session: Session, user_id: int, token: str):
    from models import RefreshToken
    h = hash_token(token)
    expires = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    rt = RefreshToken(user_id=user_id, token_hash=h, wygasa=expires)
    session.add(rt)
    session.commit()


class LoginRequest(BaseModel):
    username: str
    password: str


class LdapLoginRequest(BaseModel):
    username: str
    password: str
    domena_id: Optional[int] = None


@router.post("/login")
async def login(body: LoginRequest, request: Request, response: Response, session: Session = Depends(get_session)):
    ip = get_client_ip(request)
    row = session.execute(
        text("SELECT * FROM uzytkownicy WHERE username = :u AND rola = 'SUPERADMIN'"),
        {"u": body.username},
    ).mappings().first()

    if not row:
        write_audit(session, akcja="LOGIN_FAIL", nowe_dane={"username": body.username, "reason": "NOT_FOUND"}, ip_adres=ip)
        raise HTTPException(status_code=401, detail="Nieprawidłowe dane logowania.")

    user = dict(row)
    if not user.get("aktywny"):
        raise HTTPException(status_code=403, detail="Konto zablokowane.")

    if user.get("zablokowany_do"):
        zab = user["zablokowany_do"]
        if isinstance(zab, str):
            zab = datetime.fromisoformat(zab)
        if zab.replace(tzinfo=None) > datetime.utcnow():
            raise HTTPException(status_code=403, detail=f"Konto zablokowane do {zab}.")

    if not user.get("hash_hasla") or not verify_password(body.password, user["hash_hasla"]):
        fails = (user.get("nieudane_logowania") or 0) + 1
        lock_until = None
        if fails >= 5:
            lock_until = (datetime.now(timezone.utc) + timedelta(minutes=15)).replace(tzinfo=None)
        session.execute(
            text("UPDATE uzytkownicy SET nieudane_logowania=:f, zablokowany_do=:z WHERE id=:id"),
            {"f": fails, "z": lock_until, "id": user["id"]},
        )
        session.commit()
        write_audit(session, user_id=user["id"], username=body.username, akcja="LOGIN_FAIL",
                    nowe_dane={"reason": "WRONG_PASSWORD"}, ip_adres=ip)
        raise HTTPException(status_code=401, detail="Nieprawidłowe dane logowania.")

    session.execute(
        text("UPDATE uzytkownicy SET nieudane_logowania=0, zablokowany_do=NULL, ostatnie_logowanie=:t WHERE id=:id"),
        {"t": datetime.utcnow(), "id": user["id"]},
    )
    session.commit()

    from models import Uzytkownik as U
    u_obj = type("U", (), user)()
    payload = {"userId": user["id"], "username": user["username"], "email": user.get("email"),
                "rola": user["rola"], "tenantId": user.get("tenant_id")}
    access_token = create_access_token(payload)
    refresh_token = create_refresh_token(payload)
    _store_refresh_token(session, user["id"], refresh_token)
    _set_refresh_cookie(response, refresh_token)

    write_audit(session, user_id=user["id"], username=user["username"], rola=user["rola"],
                akcja="LOGIN_SUCCESS", ip_adres=ip)
    return {
        "accessToken": access_token,
        "user": {"id": user["id"], "username": user["username"], "rola": user["rola"],
                 "imie": user.get("imie"), "nazwisko": user.get("nazwisko")},
    }


@router.post("/ldap-login")
async def ldap_login(body: LdapLoginRequest, request: Request, response: Response, session: Session = Depends(get_session)):
    ip = get_client_ip(request)
    try:
        ldap_result = await ldap_authenticate(body.username, body.password, body.domena_id, session)
    except Exception as e:
        row = session.execute(
            text("SELECT id, nieudane_logowania FROM uzytkownicy WHERE username=:u"),
            {"u": body.username},
        ).mappings().first()
        if row:
            fails = (row["nieudane_logowania"] or 0) + 1
            lock_until = None
            if fails >= 5:
                lock_until = (datetime.now(timezone.utc) + timedelta(minutes=15)).replace(tzinfo=None)
            session.execute(
                text("UPDATE uzytkownicy SET nieudane_logowania=:f, zablokowany_do=:z WHERE id=:id"),
                {"f": fails, "z": lock_until, "id": row["id"]},
            )
            session.commit()
        write_audit(session, akcja="LDAP_LOGIN_FAIL", nowe_dane={"username": body.username, "reason": str(e)}, ip_adres=ip)
        raise HTTPException(status_code=401, detail=str(e) or "Błąd uwierzytelniania LDAP.")

    user = session.execute(
        text("SELECT * FROM uzytkownicy WHERE email=:e OR username=:u LIMIT 1"),
        {"e": ldap_result.get("email", ""), "u": body.username},
    ).mappings().first()

    if not user:
        write_audit(session, akcja="LDAP_LOGIN_FAIL", nowe_dane={"username": body.username, "reason": "NO_LOCAL_ACCOUNT"}, ip_adres=ip)
        raise HTTPException(status_code=401, detail="Brak konta. Skontaktuj się z IT.")

    user = dict(user)
    if not user.get("aktywny"):
        raise HTTPException(status_code=403, detail="Konto zablokowane.")

    session.execute(
        text("UPDATE uzytkownicy SET nieudane_logowania=0, zablokowany_do=NULL, ostatnie_logowanie=:t WHERE id=:id"),
        {"t": datetime.utcnow(), "id": user["id"]},
    )
    session.commit()

    payload = {"userId": user["id"], "username": user["username"], "email": user.get("email"),
                "rola": user["rola"], "tenantId": user.get("tenant_id")}
    access_token = create_access_token(payload)
    refresh_token = create_refresh_token(payload)
    _store_refresh_token(session, user["id"], refresh_token)
    _set_refresh_cookie(response, refresh_token)

    write_audit(session, user_id=user["id"], username=user["username"], rola=user["rola"],
                akcja="LDAP_LOGIN_SUCCESS", ip_adres=ip)
    return {
        "accessToken": access_token,
        "user": {"id": user["id"], "username": user["username"], "rola": user["rola"],
                 "imie": user.get("imie"), "nazwisko": user.get("nazwisko"), "tenantId": user.get("tenant_id")},
    }


@router.post("/refresh")
async def refresh(request: Request, response: Response, session: Session = Depends(get_session)):
    token = request.cookies.get(REFRESH_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Brak refresh tokenu.")

    from jose import JWTError
    try:
        payload = verify_refresh_token(token)
    except JWTError:
        response.delete_cookie(REFRESH_COOKIE)
        raise HTTPException(status_code=401, detail="Token nieważny.")

    h = hash_token(token)
    row = session.execute(
        text("""SELECT rt.*, u.aktywny FROM refresh_tokens rt
               JOIN uzytkownicy u ON u.id = rt.user_id
              WHERE rt.token_hash=:h AND rt.odwolany=0 AND rt.wygasa > :now"""),
        {"h": h, "now": datetime.utcnow()},
    ).mappings().first()

    if not row:
        response.delete_cookie(REFRESH_COOKIE)
        raise HTTPException(status_code=401, detail="Token nieważny lub wygasły.")

    if not row["aktywny"]:
        raise HTTPException(status_code=403, detail="Konto zablokowane.")

    user = session.execute(
        text("SELECT * FROM uzytkownicy WHERE id=:id"),
        {"id": payload.get("userId")},
    ).mappings().first()
    if not user:
        response.delete_cookie(REFRESH_COOKIE)
        raise HTTPException(status_code=401, detail="Użytkownik nie istnieje.")
    user = dict(user)

    new_payload = {"userId": user["id"], "username": user["username"], "email": user.get("email"),
                   "rola": user["rola"], "tenantId": user.get("tenant_id")}
    new_access = create_access_token(new_payload)
    new_refresh = create_refresh_token(new_payload)
    new_hash = hash_token(new_refresh)

    expires = (datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)).replace(tzinfo=None)
    session.execute(text("UPDATE refresh_tokens SET odwolany=1 WHERE token_hash=:h"), {"h": h})
    session.execute(
        text("INSERT INTO refresh_tokens (user_id, token_hash, wygasa) VALUES (:uid, :h, :e)"),
        {"uid": user["id"], "h": new_hash, "e": expires},
    )
    session.commit()

    _set_refresh_cookie(response, new_refresh)
    return {"accessToken": new_access}


@router.post("/logout")
async def logout(request: Request, response: Response,
                 session: Session = Depends(get_session),
                 current_user: CurrentUser = Depends(get_current_user)):
    token = request.cookies.get(REFRESH_COOKIE)
    if token:
        h = hash_token(token)
        session.execute(text("UPDATE refresh_tokens SET odwolany=1 WHERE token_hash=:h"), {"h": h})
        session.commit()
    response.delete_cookie(REFRESH_COOKIE)
    write_audit(session, user_id=current_user.userId, username=current_user.username,
                rola=current_user.rola, akcja="LOGOUT", ip_adres=get_client_ip(request))
    return {"message": "Wylogowano."}


@router.get("/me")
async def me(session: Session = Depends(get_session), current_user: CurrentUser = Depends(get_current_user)):
    row = session.execute(
        text("""SELECT u.id, u.username, u.imie, u.nazwisko, u.email, u.rola, u.tenant_id,
                       p.id as pracownik_id, p.stanowisko, p.komorka_id, k.nazwa as komorka_nazwa
                  FROM uzytkownicy u
                  LEFT JOIN pracownicy p ON p.uzytkownik_id = u.id
                  LEFT JOIN komorki_org k ON k.id = p.komorka_id
                 WHERE u.id = :id"""),
        {"id": current_user.userId},
    ).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Użytkownik nie istnieje.")
    return dict(row)


@router.get("/ldap-domains")
async def ldap_domains(session: Session = Depends(get_session)):
    rows = session.execute(
        text("SELECT id, nazwa, domena FROM ldap_domeny WHERE aktywna=1 ORDER BY kolejnosc")
    ).mappings().all()
    return [dict(r) for r in rows]
