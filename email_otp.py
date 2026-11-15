"""
email_otp.py  —  MODULE AJOUTÉ (ne modifie aucune route existante)

 - envoi d'e-mails contenant un code à 6 chiffres (Flask-Mail)
 - réinitialisation du mot de passe par code e-mail :
        /reset-password            -> l'utilisateur saisit son e-mail
        /reset-password/confirm    -> il saisit le code + son nouveau mot de passe
        /reset-password/resend     -> renvoi du code

Le code est stocké dans les colonnes DÉJÀ existantes User.reset_code /
User.reset_code_expires (+ User.reset_attempts, seule colonne ajoutée).
"""
import hmac
import secrets
from datetime import datetime, timedelta

from flask import (Blueprint, render_template, request, redirect,
                   url_for, session, flash, current_app)
from flask_mail import Mail, Message
from sqlalchemy import func
from werkzeug.security import generate_password_hash

from extensions import db
from models import User

mail = Mail()
otp_bp = Blueprint('otp', __name__)

OTP_VALIDITE_MIN = 10      # durée de vie du code
OTP_MAX_ESSAIS = 5         # essais faux autorisés par code
OTP_DELAI_RENVOI_S = 60    # délai minimal entre deux envois
MDP_LONGUEUR_MIN = 8

MSG_ENVOI = "Si un compte existe avec cette adresse, un code à 6 chiffres vient d'y être envoyé."


# ──────────────────────────  Envoi d'e-mail  ──────────────────────────
def mail_est_configure():
    c = current_app.config
    return bool(c.get('MAIL_USERNAME') and c.get('MAIL_PASSWORD'))


def envoyer_code_email(destinataire, code, objet, intro):
    """Envoie le code. Retourne True si l'e-mail est parti, False sinon."""
    try:
        msg = Message(objet, recipients=[destinataire])
        msg.body = (
            f"{intro}\n\n"
            f"Votre code : {code}\n\n"
            f"Ce code expire dans {OTP_VALIDITE_MIN} minutes. "
            f"Ne le communiquez à personne.\n"
            f"Si vous n'êtes pas à l'origine de cette demande, ignorez ce message."
        )
        msg.html = (
            f"<div style='font-family:Arial,sans-serif;max-width:420px;margin:auto'>"
            f"<p>{intro}</p>"
            f"<p style='font-size:32px;letter-spacing:8px;font-weight:bold;"
            f"background:#f1f3f5;padding:14px;text-align:center;border-radius:8px'>{code}</p>"
            f"<p style='color:#555'>Ce code expire dans {OTP_VALIDITE_MIN} minutes. "
            f"Ne le communiquez à personne.</p>"
            f"<p style='color:#999;font-size:12px'>Si vous n'êtes pas à l'origine de cette "
            f"demande, ignorez ce message.</p></div>"
        )
        mail.send(msg)
        return True
    except Exception as e:
        current_app.logger.error("[OTP] Échec d'envoi de l'e-mail : %s", e)
        return False


# ──────────────────────────  Logique du code  ─────────────────────────
def _generer_code():
    return f"{secrets.randbelow(1_000_000):06d}"


def _envoyer_code_reset(user):
    """Crée un code, l'enregistre en base et l'envoie (avec anti-spam)."""
    maintenant = datetime.utcnow()
    if user.reset_code_expires:
        envoye_a = user.reset_code_expires - timedelta(minutes=OTP_VALIDITE_MIN)
        if (maintenant - envoye_a).total_seconds() < OTP_DELAI_RENVOI_S:
            return  # un code vient d'être envoyé : on n'en renvoie pas tout de suite

    code = _generer_code()
    user.reset_code = code
    user.reset_code_expires = maintenant + timedelta(minutes=OTP_VALIDITE_MIN)
    user.reset_attempts = 0
    db.session.commit()

    if mail_est_configure():
        envoyer_code_email(user.email, code,
                           "Votre code de réinitialisation FaceNet",
                           "Vous avez demandé à réinitialiser votre mot de passe FaceNet.")
    else:
        current_app.logger.error("[OTP] MAIL_USERNAME / MAIL_PASSWORD non définis : e-mail non envoyé.")
        if current_app.debug:
            print(f"[OTP - mode debug, e-mail non configuré] code pour {user.email} : {code}")


def _code_valide(user, code):
    """Vérifie le code EXACT, non expiré, avec limite d'essais."""
    if not user or not user.reset_code or not user.reset_code_expires:
        return False
    if datetime.utcnow() > user.reset_code_expires:
        return False
    if (user.reset_attempts or 0) >= OTP_MAX_ESSAIS:
        return False
    if hmac.compare_digest(str(user.reset_code), code):
        return True
    user.reset_attempts = (user.reset_attempts or 0) + 1
    db.session.commit()
    return False


def _utilisateur_par_email(email):
    return User.query.filter(func.lower(User.email) == email).first()


# ──────────────────────────  Routes  ──────────────────────────────────
@otp_bp.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        if '@' not in email or len(email) > 120:
            flash("Entrez une adresse e-mail valide.", 'error')
            return render_template('reset_password_request.html')
        user = _utilisateur_par_email(email)
        if user:
            _envoyer_code_reset(user)
        # Même réponse que le compte existe ou non (pas de fuite d'information)
        session['reset_email'] = email
        flash(MSG_ENVOI, 'info')
        return redirect(url_for('otp.reset_password_confirm'))
    return render_template('reset_password_request.html')


@otp_bp.route('/reset-password/resend', methods=['POST'])
def reset_password_resend():
    email = session.get('reset_email')
    if not email:
        return redirect(url_for('otp.reset_password'))
    user = _utilisateur_par_email(email)
    if user:
        _envoyer_code_reset(user)
    flash(MSG_ENVOI, 'info')
    return redirect(url_for('otp.reset_password_confirm'))


@otp_bp.route('/reset-password/confirm', methods=['GET', 'POST'])
def reset_password_confirm():
    email = session.get('reset_email')
    if not email:
        return redirect(url_for('otp.reset_password'))

    if request.method == 'POST':
        code = (request.form.get('code') or '').strip()
        mdp = request.form.get('password') or ''
        mdp2 = request.form.get('confirm_password') or ''

        if not (code.isdigit() and len(code) == 6):
            flash("Le code doit contenir exactement 6 chiffres.", 'error')
        elif len(mdp) < MDP_LONGUEUR_MIN:
            flash(f"Le mot de passe doit contenir au moins {MDP_LONGUEUR_MIN} caractères.", 'error')
        elif mdp != mdp2:
            flash("Les deux mots de passe ne correspondent pas.", 'error')
        else:
            user = _utilisateur_par_email(email)
            if _code_valide(user, code):
                user.password = generate_password_hash(mdp)   # même hachage que /login
                user.reset_code = None
                user.reset_code_expires = None
                user.reset_attempts = 0
                db.session.commit()
                session.pop('reset_email', None)
                flash("Mot de passe modifié. Vous pouvez vous connecter.", 'success')
                return redirect(url_for('main.login'))
            flash("Code invalide ou expiré.", 'error')

    return render_template('reset_password_confirm.html', email=email)