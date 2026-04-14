from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from schemas import BaseSchema
from sqlalchemy import text
from sqlalchemy.orm import Session

from auth import encrypt_ldap_password
from database import get_session
from dependencies import CurrentUser, require_roles
from services.ldap_service import test_domain

router = APIRouter()
IT = ("IT_ADMIN", "SUPERADMIN")


class LdapDomenaIn(BaseSchema):
    nazwa: str
    domena: str
    ldap_url: str
    base_dn: str
    bind_dn: Optional[str] = None
    bind_password: Optional[str] = None
    user_filter: Optional[str] = "(&(objectClass=user)(sAMAccountName=%s))"
    attr_email: Optional[str] = "mail"
    attr_firstname: Optional[str] = "givenName"
    attr_lastname: Optional[str] = "sn"
    attr_username: Optional[str] = "sAMAccountName"
    tls: Optional[bool] = False
    tls_ca_cert: Optional[str] = None
    aktywna: Optional[bool] = True
    kolejnosc: Optional[int] = 0


@router.get("")
async def list_domeny(session: Session = Depends(get_session),
                       current_user: CurrentUser = Depends(require_roles(*IT))):
    rows = session.execute(
        text("SELECT id,nazwa,domena,ldap_url,base_dn,bind_dn,user_filter,attr_email,attr_firstname,attr_lastname,attr_username,tls,aktywna,kolejnosc FROM ldap_domeny ORDER BY kolejnosc")
    ).mappings().all()
    return [dict(r) for r in rows]


@router.post("", status_code=201)
async def create_domena(body: LdapDomenaIn, session: Session = Depends(get_session),
                         current_user: CurrentUser = Depends(require_roles(*IT))):
    enc = encrypt_ldap_password(body.bind_password) if body.bind_password else None
    row = session.execute(
        text("""INSERT INTO ldap_domeny (nazwa,domena,ldap_url,base_dn,bind_dn,bind_password_enc,
                user_filter,attr_email,attr_firstname,attr_lastname,attr_username,tls,tls_ca_cert,kolejnosc)
                VALUES (:n,:d,:u,:b,:bd,:bp,:uf,:ae,:af,:al,:au,:t,:tc,:k) RETURNING id,nazwa,domena,aktywna"""),
        {"n": body.nazwa, "d": body.domena, "u": body.ldap_url, "b": body.base_dn,
         "bd": body.bind_dn, "bp": enc,
         "uf": body.user_filter or "(&(objectClass=user)(sAMAccountName=%s))",
         "ae": body.attr_email or "mail", "af": body.attr_firstname or "givenName",
         "al": body.attr_lastname or "sn", "au": body.attr_username or "sAMAccountName",
         "t": body.tls or False, "tc": body.tls_ca_cert, "k": body.kolejnosc or 0},
    ).mappings().first()
    session.commit()
    return dict(row)


@router.put("/{domena_id}")
async def update_domena(domena_id: int, body: LdapDomenaIn, session: Session = Depends(get_session),
                         current_user: CurrentUser = Depends(require_roles(*IT))):
    old = session.execute(text("SELECT * FROM ldap_domeny WHERE id=:id"), {"id": domena_id}).mappings().first()
    if not old:
        raise HTTPException(status_code=404, detail="Domena nie istnieje.")
    old = dict(old)
    enc = encrypt_ldap_password(body.bind_password) if body.bind_password else old.get("bind_password_enc")
    row = session.execute(
        text("""UPDATE ldap_domeny SET nazwa=:n, domena=:d, ldap_url=:u, base_dn=:b, bind_dn=:bd,
                bind_password_enc=:bp, user_filter=:uf, attr_email=:ae, attr_firstname=:af,
                attr_lastname=:al, attr_username=:au, tls=:t, tls_ca_cert=:tc, aktywna=:a, kolejnosc=:k
                WHERE id=:id RETURNING id,nazwa,domena,aktywna"""),
        {"n": body.nazwa, "d": body.domena, "u": body.ldap_url, "b": body.base_dn,
         "bd": body.bind_dn, "bp": enc, "uf": body.user_filter, "ae": body.attr_email,
         "af": body.attr_firstname, "al": body.attr_lastname, "au": body.attr_username,
         "t": body.tls, "tc": body.tls_ca_cert, "a": body.aktywna, "k": body.kolejnosc, "id": domena_id},
    ).mappings().first()
    session.commit()
    return dict(row)


@router.delete("/{domena_id}")
async def delete_domena(domena_id: int, session: Session = Depends(get_session),
                         current_user: CurrentUser = Depends(require_roles("SUPERADMIN"))):
    session.execute(text("DELETE FROM ldap_domeny WHERE id=:id"), {"id": domena_id})
    session.commit()
    return {"message": "Domena usunięta."}


@router.post("/{domena_id}/test")
async def test_domena(domena_id: int, session: Session = Depends(get_session),
                       current_user: CurrentUser = Depends(require_roles(*IT))):
    try:
        await test_domain(domena_id, session)
        return {"success": True, "message": "Połączenie LDAP działa poprawnie."}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e) or "Błąd połączenia LDAP.")
