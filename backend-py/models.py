from __future__ import annotations
from datetime import datetime, date
from typing import Optional
from sqlmodel import SQLModel, Field


class Tenant(SQLModel, table=True):
    __tablename__ = "tenants"
    id: Optional[int] = Field(default=None, primary_key=True)
    nazwa: str
    skrot: str
    regon: Optional[str] = None
    nip: Optional[str] = None
    aktywny: bool = True
    data_utworzenia: datetime = Field(default_factory=datetime.utcnow)
    dni_do_przegladu: int = 365


class Uzytkownik(SQLModel, table=True):
    __tablename__ = "uzytkownicy"
    id: Optional[int] = Field(default=None, primary_key=True)
    tenant_id: Optional[int] = Field(default=None, foreign_key="tenants.id")
    username: str = Field(unique=True)
    imie: Optional[str] = None
    nazwisko: Optional[str] = None
    email: Optional[str] = None
    rola: str  # SUPERADMIN/IT_ADMIN/KADRY/KIEROWNIK/PRACOWNIK
    hash_hasla: Optional[str] = None
    aktywny: bool = True
    data_utworzenia: datetime = Field(default_factory=datetime.utcnow)
    ostatnie_logowanie: Optional[datetime] = None
    wymagaj_zmiany_hasla: bool = True
    nieudane_logowania: int = 0
    zablokowany_do: Optional[datetime] = None


class RefreshToken(SQLModel, table=True):
    __tablename__ = "refresh_tokens"
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="uzytkownicy.id")
    token_hash: str
    odwolany: bool = False
    data_utworzenia: datetime = Field(default_factory=datetime.utcnow)
    wygasa: datetime


class LdapDomena(SQLModel, table=True):
    __tablename__ = "ldap_domeny"
    id: Optional[int] = Field(default=None, primary_key=True)
    nazwa: str
    domena: str
    ldap_url: str
    base_dn: str
    bind_dn: Optional[str] = None
    bind_password_enc: Optional[str] = None
    user_filter: str = "(&(objectClass=user)(sAMAccountName=%s))"
    attr_email: str = "mail"
    attr_firstname: str = "givenName"
    attr_lastname: str = "sn"
    attr_username: str = "sAMAccountName"
    tls: bool = False
    tls_ca_cert: Optional[str] = None
    aktywna: bool = True
    kolejnosc: int = 0


class KonfiguracjaPlatformy(SQLModel, table=True):
    __tablename__ = "konfiguracja_platformy"
    klucz: str = Field(primary_key=True)
    wartosc: Optional[str] = None
    opis: Optional[str] = None


class KonfiguracjaNumeracji(SQLModel, table=True):
    __tablename__ = "konfiguracja_numeracji"
    id: int = Field(default=1, primary_key=True)
    format_szablonu: str = "{PREFIX}.{SEQ}.{ROK}"
    prefix: str = "ZUP"
    szerokosc_sekwencji: int = 4
    reset_co: str = "ROK"
    ostatni_numer: int = 0
    ostatni_reset: Optional[str] = None


class Powiadomienie(SQLModel, table=True):
    __tablename__ = "powiadomienia"
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="uzytkownicy.id")
    typ: str
    tresc: str
    link: Optional[str] = None
    przeczytane: bool = False
    data_utworzenia: datetime = Field(default_factory=datetime.utcnow)


class StrukturOrg(SQLModel, table=True):
    __tablename__ = "struktura_org"
    id: Optional[int] = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="tenants.id")
    nazwa: str
    typ_wezla: str
    nadrzedny_id: Optional[int] = Field(default=None, foreign_key="struktura_org.id")
    kolejnosc: int = 0
    aktywna: bool = True


class KomorkaOrg(SQLModel, table=True):
    __tablename__ = "komorki_org"
    id: Optional[int] = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="tenants.id")
    struktura_org_id: Optional[int] = Field(default=None, foreign_key="struktura_org.id")
    nazwa: str
    kod: Optional[str] = None
    aktywna: bool = True


class Pracownik(SQLModel, table=True):
    __tablename__ = "pracownicy"
    id: Optional[int] = Field(default=None, primary_key=True)
    uzytkownik_id: Optional[int] = Field(default=None, foreign_key="uzytkownicy.id")
    tenant_id: int = Field(foreign_key="tenants.id")
    komorka_id: Optional[int] = Field(default=None, foreign_key="komorki_org.id")
    stanowisko: Optional[str] = None
    data_zatrudnienia: Optional[date] = None
    data_zwolnienia: Optional[date] = None
    aktywny: bool = True
    przelozony_id: Optional[int] = Field(default=None, foreign_key="pracownicy.id")


class SystemIT(SQLModel, table=True):
    __tablename__ = "systemy_it"
    id: Optional[int] = Field(default=None, primary_key=True)
    tenant_id: Optional[int] = Field(default=None, foreign_key="tenants.id")
    nazwa: str
    opis: Optional[str] = None
    wlasciciel: Optional[str] = None
    poziom_krytycznosci: str = "NORMALNY"
    aktywny: bool = True
    data_dodania: datetime = Field(default_factory=datetime.utcnow)
    dodany_przez: Optional[int] = Field(default=None, foreign_key="uzytkownicy.id")


class ModulSystemu(SQLModel, table=True):
    __tablename__ = "modul_systemu"
    id: Optional[int] = Field(default=None, primary_key=True)
    system_id: int = Field(foreign_key="systemy_it.id")
    nazwa: str
    opis: Optional[str] = None
    aktywny: bool = True


class ZakresUprawnien(SQLModel, table=True):
    __tablename__ = "zakres_uprawnien"
    id: Optional[int] = Field(default=None, primary_key=True)
    system_id: int = Field(foreign_key="systemy_it.id")
    modul_id: Optional[int] = Field(default=None, foreign_key="modul_systemu.id")
    nazwa: str
    opis: Optional[str] = None
    uprzywilejowany: bool = False


class WorkflowSzablon(SQLModel, table=True):
    __tablename__ = "workflow_szablony"
    id: Optional[int] = Field(default=None, primary_key=True)
    tenant_id: Optional[int] = Field(default=None, foreign_key="tenants.id")
    nazwa: str
    opis: Optional[str] = None
    aktywny: bool = True
    data_utworzenia: datetime = Field(default_factory=datetime.utcnow)
    utworzony_przez: Optional[int] = Field(default=None, foreign_key="uzytkownicy.id")


class WorkflowPoziom(SQLModel, table=True):
    __tablename__ = "workflow_poziomy"
    id: Optional[int] = Field(default=None, primary_key=True)
    szablon_id: int = Field(foreign_key="workflow_szablony.id")
    kolejnosc: int
    nazwa: str
    zatwierdzajacy_id: Optional[int] = Field(default=None, foreign_key="pracownicy.id")
    opcjonalny: bool = False
    opis_warunku_pominiecia: Optional[str] = None
    przypomnienie_dni: Optional[int] = None
    eskalacja_dni: Optional[int] = None


class WorkflowPrzypisanie(SQLModel, table=True):
    __tablename__ = "workflow_przypisania"
    id: Optional[int] = Field(default=None, primary_key=True)
    szablon_id: int = Field(foreign_key="workflow_szablony.id")
    typ: str
    komorka_id: Optional[int] = Field(default=None, foreign_key="komorki_org.id")
    tenant_id: Optional[int] = Field(default=None, foreign_key="tenants.id")


class Wniosek(SQLModel, table=True):
    __tablename__ = "wnioski"
    id: Optional[int] = Field(default=None, primary_key=True)
    numer: Optional[str] = None
    tenant_id: int = Field(foreign_key="tenants.id")
    pracownik_id: int = Field(foreign_key="pracownicy.id")
    inicjujacy_id: int = Field(foreign_key="pracownicy.id")
    szablon_id: Optional[int] = Field(default=None, foreign_key="workflow_szablony.id")
    status: str = "SZKIC"
    aktualny_etap_kolejnosc: Optional[int] = None
    uwagi_inicjujacego: Optional[str] = None
    uwagi_it: Optional[str] = None
    odrzucil_id: Optional[int] = None
    data_odrzucenia: Optional[datetime] = None
    powod_odrzucenia: Optional[str] = None
    pdf_sciezka: Optional[str] = None
    pdf_wygenerowany_przez: Optional[int] = None
    pdf_data_generowania: Optional[datetime] = None
    zrealizowal_it_id: Optional[int] = None
    data_realizacji: Optional[datetime] = None
    uwagi_realizacji: Optional[str] = None
    data_utworzenia: datetime = Field(default_factory=datetime.utcnow)
    data_ostatniej_zmiany: datetime = Field(default_factory=datetime.utcnow)


class PozycjaWniosku(SQLModel, table=True):
    __tablename__ = "pozycje_wniosku"
    id: Optional[int] = Field(default=None, primary_key=True)
    wniosek_id: int = Field(foreign_key="wnioski.id")
    system_id: int = Field(foreign_key="systemy_it.id")
    modul_id: Optional[int] = Field(default=None, foreign_key="modul_systemu.id")
    zakres_id: int = Field(foreign_key="zakres_uprawnien.id")
    uzasadnienie: Optional[str] = None
    dodana_przez: Optional[int] = None
    zmodyfikowana_przez: Optional[int] = None
    data_modyfikacji: Optional[datetime] = None


class WniosekEtap(SQLModel, table=True):
    __tablename__ = "wnioski_etapy"
    id: Optional[int] = Field(default=None, primary_key=True)
    wniosek_id: int = Field(foreign_key="wnioski.id")
    kolejnosc: int
    nazwa: str
    zatwierdzajacy_id: Optional[int] = Field(default=None, foreign_key="pracownicy.id")
    opcjonalny: bool = False
    opis_warunku_pominiecia: Optional[str] = None
    przypomnienie_dni: Optional[int] = None
    eskalacja_dni: Optional[int] = None
    status: str = "OCZEKUJACY"
    pominiety: bool = False
    powod_pominiecia: Optional[str] = None
    data_przypisania: Optional[datetime] = None
    data_akcji: Optional[datetime] = None
    data_przypomnienia: Optional[datetime] = None
    data_eskalacji: Optional[datetime] = None
    eskalacja_do: Optional[int] = None
    komentarz: Optional[str] = None


class Uprawnienie(SQLModel, table=True):
    __tablename__ = "uprawnienia"
    id: Optional[int] = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="tenants.id")
    pracownik_id: int = Field(foreign_key="pracownicy.id")
    system_id: int = Field(foreign_key="systemy_it.id")
    modul_id: Optional[int] = Field(default=None, foreign_key="modul_systemu.id")
    zakres_id: int = Field(foreign_key="zakres_uprawnien.id")
    wniosek_id: Optional[int] = Field(default=None, foreign_key="wnioski.id")
    aktywne: bool = True
    nadane_bezposrednio: bool = False
    data_od: datetime = Field(default_factory=datetime.utcnow)
    data_do: Optional[datetime] = None
    nadane_przez: int = Field(foreign_key="uzytkownicy.id")
    data_cofniecia: Optional[datetime] = None
    cofniete_przez: Optional[int] = None
    powod_cofniecia: Optional[str] = None
    wymaga_przegladu: bool = False
    data_ostatniego_przegladu: Optional[datetime] = None
    wynik_przegladu: Optional[str] = None


class Przeglad(SQLModel, table=True):
    __tablename__ = "przeglady"
    id: Optional[int] = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="tenants.id")
    typ: str
    status: str = "W_TOKU"
    inicjujacy_id: int = Field(foreign_key="uzytkownicy.id")
    data_rozpoczecia: datetime = Field(default_factory=datetime.utcnow)
    data_zakonczenia: Optional[datetime] = None
    uwagi: Optional[str] = None


class PozycjaPrzegladu(SQLModel, table=True):
    __tablename__ = "pozycje_przegladu"
    id: Optional[int] = Field(default=None, primary_key=True)
    przeglad_id: int = Field(foreign_key="przeglady.id")
    uprawnienie_id: int = Field(foreign_key="uprawnienia.id")
    pracownik_id: int = Field(foreign_key="pracownicy.id")
    decyzja: Optional[str] = None
    uzasadnienie: Optional[str] = None
    data_decyzji: Optional[datetime] = None
    decydent_id: Optional[int] = None


class RejestIncydentu(SQLModel, table=True):
    __tablename__ = "rejestr_incydentow"
    id: Optional[int] = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="tenants.id")
    tytul: str
    opis: str
    typ: str
    poziom: str = "NISKI"
    status: str = "OTWARTY"
    zglaszajacy_id: Optional[int] = Field(default=None, foreign_key="uzytkownicy.id")
    data_zgloszenia: datetime = Field(default_factory=datetime.utcnow)
    data_zamkniecia: Optional[datetime] = None
    dzialania_naprawcze: Optional[str] = None
    dotyczy_nis2: bool = False


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_log"
    id: Optional[int] = Field(default=None, primary_key=True)
    tenant_id: Optional[int] = None
    user_id: Optional[int] = None
    username: Optional[str] = None
    rola: Optional[str] = None
    akcja: str
    tabela_docelowa: Optional[str] = None
    rekord_id: Optional[int] = None
    stare_dane: Optional[str] = None
    nowe_dane: Optional[str] = None
    ip_adres: Optional[str] = None
    user_agent: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
