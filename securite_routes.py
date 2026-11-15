"""Sécurité & mot de passe : changement de mot de passe, 2FA (TOTP), coordonnées.

Dépendances : pip install pyotp qrcode requests phonenumbers
Branchement (dans le fichier où le blueprint `main` est créé, après sa définition) :
    from securite_routes import init_securite
    init_securite(main)

La 2FA est appliquée automatiquement : dès qu'un utilisateur qui l'a activée est connecté,
toute page lui redemande le code (/login/2fa) tant qu'il ne l'a pas saisi. Aucune
modification de ta route de login n'est nécessaire.
"""
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta

import phonenumbers
import pyotp
import qrcode
import qrcode.image.svg
from flask import (current_app, jsonify, redirect, render_template, render_template_string,
                   request, session, url_for)
from flask_login import (current_user, login_required, logout_user,
                         user_logged_in, user_logged_out)
from werkzeug.routing import BuildError
from werkzeug.security import check_password_hash, generate_password_hash

from models import db, User  # <-- adapte cet import à ton projet
from envoi_code import envoyer
from pays_telephone import PAYS, PAYS_PAR_ISO

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


# ─────────────────────────── MODÈLES ───────────────────────────
class UserSecurity(db.Model):
    __tablename__ = "user_security"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey(User.id), unique=True, nullable=False)
    two_factor_enabled = db.Column(db.Boolean, default=False, nullable=False)
    totp_secret = db.Column(db.String(64))
    method = db.Column(db.String(10), default="app")  # app | sms | whatsapp
    contact_id = db.Column(db.Integer)  # numéro utilisé pour sms/whatsapp


class UserContact(db.Model):
    __tablename__ = "user_contact"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey(User.id), nullable=False, index=True)
    kind = db.Column(db.String(10), nullable=False)  # 'email' | 'phone'
    value = db.Column(db.String(255), nullable=False)
    verified = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    code_hash = db.Column(db.String(64))
    code_expires = db.Column(db.DateTime)
    code_sent_at = db.Column(db.DateTime)
    code_attempts = db.Column(db.Integer, default=0, nullable=False)
    __table_args__ = (db.UniqueConstraint("user_id", "value", name="uq_contact_user_value"),)


# ─────────────────────────── OUTILS ───────────────────────────
def _pwd_hash_attr(user):
    return "password_hash" if hasattr(user, "password_hash") else "password"


def _check_pwd(user, pwd):
    if hasattr(user, "check_password"):
        return user.check_password(pwd)
    return check_password_hash(getattr(user, _pwd_hash_attr(user)) or "", pwd)


def _set_pwd(user, pwd):
    if hasattr(user, "set_password"):
        user.set_password(pwd)
    else:
        setattr(user, _pwd_hash_attr(user), generate_password_hash(pwd))


def _security(user):
    s = UserSecurity.query.filter_by(user_id=user.id).first()
    if not s:
        s = UserSecurity(user_id=user.id)
        db.session.add(s)
        db.session.commit()
    return s


def _out(ok, message, status=None, **extra):
    return jsonify(ok=ok, message=message, **extra), status or (200 if ok else 400)


def _url(endpoint, fallback):
    try:
        return url_for(endpoint)
    except BuildError:
        return fallback


def _hash_code(code):
    return hashlib.sha256((code + current_app.config["SECRET_KEY"]).encode()).hexdigest()


_LIB = {"whatsapp": "par WhatsApp", "sms": "par SMS", "terminal": "(mode test : affiché dans le terminal)"}


def _masque(v):
    return v[:4] + "••••" + v[-2:]


def _envoyer_code(contact, canal="whatsapp"):
    """Code de vérification d'une coordonnée (WhatsApp -> SMS en secours, ou terminal en test)."""
    code = f"{secrets.randbelow(10**6):06d}"
    contact.code_hash = _hash_code(code)
    contact.code_expires = datetime.utcnow() + timedelta(minutes=10)
    contact.code_sent_at = datetime.utcnow()
    contact.code_attempts = 0
    db.session.commit()
    return envoyer(contact.value, code, canal, contact.kind)


def _envoyer_code_session(key, numero, canal):
    """Code temporaire gardé en session (activation de la 2FA, connexion)."""
    code = f"{secrets.randbelow(10**6):06d}"
    now = datetime.utcnow()
    session[key] = {"h": _hash_code(code), "exp": (now + timedelta(minutes=10)).timestamp()}
    return envoyer(numero, code, canal)


def _code_session_ok(key, code):
    d = session.get(key)
    return bool(d and d["exp"] > datetime.utcnow().timestamp() and hmac.compare_digest(_hash_code(code), d["h"]))


# ─────────────────── AIDES POUR LA CONNEXION (2FA) ───────────────────
def needs_2fa(user):
    s = UserSecurity.query.filter_by(user_id=user.id).first()
    return bool(s and s.two_factor_enabled)


def _reset_2fa_flag(sender, user=None, **kwargs):
    """Chaque nouvelle connexion ou déconnexion oblige à ressaisir le code 2FA."""
    session.pop("2fa_ok_uid", None)
    session.pop("2fa_tries", None)
    session.pop("2fa_code", None)


user_logged_in.connect(_reset_2fa_flag)
user_logged_out.connect(_reset_2fa_flag)


LOGIN_2FA_HTML = """<!DOCTYPE html><html lang="fr"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Vérification | FaceNet</title>
<style>body{margin:0;background:#F0F2F5;font-family:'Segoe UI',Tahoma,sans-serif;display:grid;place-items:center;min-height:100vh}
.b{background:#fff;padding:28px;border-radius:10px;box-shadow:0 2px 12px rgba(0,0,0,.12);width:min(380px,92vw)}
h1{font-size:20px;margin:0 0 6px}p{color:#65676B;font-size:14px;margin:0 0 16px}
input{width:100%;box-sizing:border-box;padding:12px;font-size:22px;letter-spacing:8px;text-align:center;border:1px solid #dddfe2;border-radius:8px}
button{width:100%;margin-top:14px;padding:12px;border:0;border-radius:8px;background:#0866FF;color:#fff;font-weight:700;font-size:15px;cursor:pointer}
.e{color:#c4152f;font-size:13.5px;margin-top:10px}</style></head><body>
<form class="b" method="post"><h1>Vérification en deux étapes</h1>
<p>{{ info }}</p>
<input type="hidden" name="csrf_token" value="{{ csrf_token() if csrf_token is defined else '' }}">
<input name="code" inputmode="numeric" maxlength="6" placeholder="000000" autocomplete="one-time-code" autofocus>
{% if erreur %}<div class="e">{{ erreur }}</div>{% endif %}
<button type="submit">Continuer</button>
{% if methode != 'app' %}<button type="submit" name="action" value="resend" style="background:#e4e6eb;color:#1c1e21">Renvoyer le code</button>
{% if methode == 'whatsapp' %}<button type="submit" name="action" value="sms" style="background:#e4e6eb;color:#1c1e21">Le recevoir par SMS</button>{% endif %}{% endif %}
<p style="text-align:center;margin:14px 0 0"><a href="{{ logout_url }}" style="color:#65676B">Se déconnecter</a></p></form></body></html>"""


# ─────────────────────────── ROUTES ───────────────────────────
def init_securite(bp):
    @login_required
    def update_password():
        if request.method == "GET":
            contacts = (UserContact.query.filter_by(user_id=current_user.id)
                        .order_by(UserContact.created_at).all())
            return render_template(
                "securite_mot_de_passe.html",
                two_factor_enabled=_security(current_user).two_factor_enabled,
                contacts=contacts,
                pays=PAYS,
                email_principal=getattr(current_user, "email", None),
                retour_url=_url("main.settings", "/settings"),
                url_verif_email=_url("main.verification_email", "#"),
                url_verif_tel=_url("main.verification_telephone", "#"),
            )
        d = request.get_json(silent=True) or {}
        actuel, nouveau, conf = d.get("actuel", ""), d.get("nouveau", ""), d.get("confirmation", "")
        if not _check_pwd(current_user, actuel):
            return _out(False, "Le mot de passe actuel est incorrect.")
        if len(nouveau) < 8:
            return _out(False, "Le nouveau mot de passe doit contenir au moins 8 caractères.")
        if nouveau != conf:
            return _out(False, "Les deux nouveaux mots de passe ne correspondent pas.")
        if nouveau == actuel:
            return _out(False, "Le nouveau mot de passe doit être différent de l'actuel.")
        _set_pwd(current_user, nouveau)
        db.session.commit()
        return _out(True, "Ton mot de passe a été mis à jour.")

    @login_required
    def tfa_preparer():
        methode = (request.get_json(silent=True) or {}).get("method", "app")
        if methode == "app":
            secret = pyotp.random_base32()
            session["tfa_pending"] = secret
            label = getattr(current_user, "email", None) or current_user.username
            uri = pyotp.TOTP(secret).provisioning_uri(name=str(label), issuer_name="FaceNet")
            svg = qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage).to_string().decode()
            return _out(True, "ok", qr_svg=svg[svg.find("<svg"):], secret=secret,
                        info="1. Scanne ce QR code avec ton application. 2. Saisis le code à 6 chiffres qu'elle affiche.")
        if methode in ("sms", "whatsapp"):
            c = UserContact.query.filter_by(user_id=current_user.id, kind="phone", verified=True).first()
            if not c:
                return _out(False, "Ajoute et vérifie d'abord un numéro de téléphone dans « Coordonnées du compte ».")
            canal = _envoyer_code_session("tfa_pending_code", c.value, methode)
            return _out(True, "ok", info=f"Code envoyé {_LIB[canal]} au {_masque(c.value)}. Saisis-le ci-dessous.")
        return _out(False, "Méthode inconnue.")

    @login_required
    def tfa_activer():
        d = request.get_json(silent=True) or {}
        methode, code = d.get("method", "app"), d.get("code", "")
        s = _security(current_user)
        if methode == "app":
            secret = session.get("tfa_pending")
            if not secret:
                return _out(False, "Session expirée : clique de nouveau sur Activer.")
            if not pyotp.TOTP(secret).verify(code, valid_window=1):
                return _out(False, "Code incorrect. Vérifie l'heure de ton téléphone et réessaie.")
            s.totp_secret, s.method, s.contact_id = secret, "app", None
        elif methode in ("sms", "whatsapp"):
            c = UserContact.query.filter_by(user_id=current_user.id, kind="phone", verified=True).first()
            if not c or not _code_session_ok("tfa_pending_code", code):
                return _out(False, "Code incorrect ou expiré.")
            s.method, s.contact_id, s.totp_secret = methode, c.id, None
        else:
            return _out(False, "Méthode inconnue.")
        s.two_factor_enabled = True
        db.session.commit()
        session.pop("tfa_pending", None)
        session.pop("tfa_pending_code", None)
        session["2fa_ok_uid"] = current_user.id  # il vient de prouver qu'il reçoit les codes
        return _out(True, "L'authentification à deux facteurs est activée.")

    @login_required
    def tfa_desactiver():
        pw = (request.get_json(silent=True) or {}).get("password", "")
        if not _check_pwd(current_user, pw):
            return _out(False, "Mot de passe incorrect.")
        s = _security(current_user)
        s.two_factor_enabled, s.totp_secret = False, None
        db.session.commit()
        return _out(True, "L'authentification à deux facteurs est désactivée.")

    @login_required
    def contact_ajouter():
        d = request.get_json(silent=True) or {}
        kind, value = d.get("kind"), (d.get("value") or "").strip()
        if kind == "email":
            value = value.lower()
            if not EMAIL_RE.match(value):
                return _out(False, "Adresse e-mail invalide.")
        elif kind == "phone":
            pays = PAYS_PAR_ISO.get(d.get("country"))
            if not pays:
                return _out(False, "Choisis le pays du numéro.")
            try:  # phonenumbers gère les règles de chaque pays (0 initial, longueurs...)
                num = phonenumbers.parse(value, pays["iso"])
            except phonenumbers.NumberParseException:
                num = None
            if not num or not phonenumbers.is_valid_number(num):
                return _out(False, "Numéro invalide pour ce pays. Saisis-le sans l'indicatif.")
            value = phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)
        else:
            return _out(False, "Type de coordonnée inconnu.")
        if value == (getattr(current_user, "email", "") or "").lower():
            return _out(False, "C'est déjà ton adresse e-mail principale.")
        if UserContact.query.filter_by(user_id=current_user.id, value=value).first():
            return _out(False, "Cette coordonnée est déjà ajoutée à ton compte.")
        if UserContact.query.filter_by(user_id=current_user.id).count() >= 10:
            return _out(False, "Tu as atteint la limite de 10 coordonnées.")
        c = UserContact(user_id=current_user.id, kind=kind, value=value)
        db.session.add(c)
        db.session.commit()
        canal = _envoyer_code(c, d.get("canal", "whatsapp"))
        return _out(True, f"Coordonnée ajoutée. Code envoyé {_LIB[canal]}.")

    @login_required
    def contact_verifier(cid):
        c = UserContact.query.filter_by(id=cid, user_id=current_user.id).first()
        code = ((request.get_json(silent=True) or {}).get("code") or "").strip()
        if not c:
            return _out(False, "Coordonnée introuvable.", 404)
        if c.verified:
            return _out(True, "Déjà vérifiée.")
        if not c.code_hash or not c.code_expires or c.code_expires < datetime.utcnow():
            return _out(False, "Ce code a expiré. Demande un nouveau code.")
        if c.code_attempts >= 5:
            return _out(False, "Trop de tentatives. Demande un nouveau code.", 429)
        c.code_attempts += 1
        if not hmac.compare_digest(_hash_code(code), c.code_hash):
            db.session.commit()
            return _out(False, "Code incorrect.")
        c.verified, c.code_hash = True, None
        db.session.commit()
        return _out(True, "Coordonnée vérifiée.")

    @login_required
    def contact_renvoyer(cid):
        c = UserContact.query.filter_by(id=cid, user_id=current_user.id).first()
        if not c or c.verified:
            return _out(False, "Coordonnée introuvable ou déjà vérifiée.", 404)
        if c.code_sent_at and datetime.utcnow() - c.code_sent_at < timedelta(seconds=30):
            return _out(False, "Patiente quelques secondes avant de redemander un code.", 429)
        canal = _envoyer_code(c, (request.get_json(silent=True) or {}).get("canal", "whatsapp"))
        return _out(True, f"Nouveau code envoyé {_LIB[canal]}.")

    @login_required
    def contact_supprimer(cid):
        c = UserContact.query.filter_by(id=cid, user_id=current_user.id).first()
        if not c:
            return _out(False, "Coordonnée introuvable.", 404)
        s = UserSecurity.query.filter_by(user_id=current_user.id).first()
        if s and s.two_factor_enabled and s.contact_id == c.id:
            return _out(False, "Ce numéro sert à ton authentification à deux facteurs. Désactive-la d'abord.")
        db.session.delete(c)
        db.session.commit()
        return _out(True, "Coordonnée supprimée.")

    @bp.before_app_request
    def exiger_2fa():
        ep = request.endpoint or ""
        if (not current_user.is_authenticated or ep == "static" or "logout" in ep
                or ep == "main.login_2fa"):
            return None
        if session.get("2fa_ok_uid") == current_user.id or not needs_2fa(current_user):
            return None
        if request.method == "GET":
            session["2fa_next"] = request.full_path.rstrip("?")
        return redirect(url_for("main.login_2fa"))

    def login_2fa():
        if not current_user.is_authenticated:
            return redirect(_url("main.login", "/login"))
        s = UserSecurity.query.filter_by(user_id=current_user.id).first()
        if not (s and s.two_factor_enabled) or session.get("2fa_ok_uid") == current_user.id:
            return redirect(url_for("main.feed"))
        methode = s.method or "app"
        c = db.session.get(UserContact, s.contact_id) if methode != "app" else None
        if methode != "app" and not c:
            logout_user()
            return redirect(_url("main.login", "/login"))
        erreur = None
        if request.method == "POST":
            action = request.form.get("action")
            if action in ("resend", "sms"):
                session["2fa_canal"] = _envoyer_code_session("2fa_code", c.value, "sms" if action == "sms" else methode)
            else:
                session["2fa_tries"] = session.get("2fa_tries", 0) + 1
                if session["2fa_tries"] > 5:  # trop d'essais : on déconnecte
                    logout_user()
                    return redirect(_url("main.login", "/login"))
                code = (request.form.get("code") or "").strip()
                ok = (pyotp.TOTP(s.totp_secret).verify(code, valid_window=1) if methode == "app"
                      else _code_session_ok("2fa_code", code))
                if ok:
                    session["2fa_ok_uid"] = current_user.id
                    for k in ("2fa_tries", "2fa_code"):
                        session.pop(k, None)
                    suite = session.pop("2fa_next", None)
                    return redirect(suite if suite and suite.startswith("/") and not suite.startswith("//")
                                    else url_for("main.feed"))
                erreur = "Code incorrect. Réessaie."
        elif methode != "app" and not session.get("2fa_code"):
            session["2fa_canal"] = _envoyer_code_session("2fa_code", c.value, methode)
        info = ("Saisis le code à 6 chiffres affiché par ton application d'authentification." if methode == "app"
                else f"Code envoyé {_LIB[session.get('2fa_canal', 'sms')]} au {_masque(c.value)}.")
        return render_template_string(LOGIN_2FA_HTML, erreur=erreur, info=info, methode=methode,
                                      logout_url=_url("main.logout", "/logout"))

    for rule, view, methods in [
        ("/securite", update_password, ["GET", "POST"]),
        ("/securite/2fa/preparer", tfa_preparer, ["POST"]),
        ("/securite/2fa/activer", tfa_activer, ["POST"]),
        ("/securite/2fa/desactiver", tfa_desactiver, ["POST"]),
        ("/securite/contact/ajouter", contact_ajouter, ["POST"]),
        ("/securite/contact/<int:cid>/supprimer", contact_supprimer, ["POST"]),
        ("/securite/contact/<int:cid>/verifier", contact_verifier, ["POST"]),
        ("/securite/contact/<int:cid>/renvoyer", contact_renvoyer, ["POST"]),
        ("/login/2fa", login_2fa, ["GET", "POST"]),
    ]:
        bp.add_url_rule(rule, endpoint=view.__name__, view_func=view, methods=methods)