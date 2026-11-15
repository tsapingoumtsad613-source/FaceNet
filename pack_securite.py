"""
pack_securite.py — Pack Sécurité Présidentielle (FaceNet)

Fichier NEUF : aucune route existante n'est modifiée.
Enregistrement dans app.py (à côté des autres blueprints) :

    from pack_securite import pack_securite_bp
    app.register_blueprint(pack_securite_bp)

Variable d'environnement (.env) : FACENET_PROTOCOL_KEY_HASHES=hash1,hash2
(hash SHA-256 des clés de protocole, jamais les clés en clair).
"""
import hashlib
import hmac
import math
import os
import secrets
from datetime import datetime, timedelta

import fapshi
from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from sqlalchemy.exc import IntegrityError

from extensions import db
from models import ProtectionPresidentielle, ProtocolKeyUsage

pack_securite_bp = Blueprint('pack_securite', __name__)

PRIX_PACK_FCFA = 1000
MAX_ECHECS_CODE = 5
BLOCAGE_MINUTES = 15
_STATUTS_ATTENTE_FAPSHI = ('CREATED', 'PENDING')
_tables_ok = False


# ───────────────────────── Outils ─────────────────────────
def _assurer_tables():
    global _tables_ok
    if _tables_ok:
        return
    try:
        ProtectionPresidentielle.__table__.create(bind=db.engine, checkfirst=True)
        ProtocolKeyUsage.__table__.create(bind=db.engine, checkfirst=True)
        _tables_ok = True
    except Exception as e:
        print(f"DEBUG: création tables pack sécurité impossible : {e}")


def _csrf_token():
    """Même jeton de session ('fn_csrf') que tes autres formulaires."""
    tok = session.get('fn_csrf')
    if not tok:
        tok = secrets.token_urlsafe(32)
        session['fn_csrf'] = tok
    return tok


def _csrf_ok():
    attendu = session.get('fn_csrf', '')
    recu = request.form.get('csrf_token', '')
    return bool(attendu) and bool(recu) and hmac.compare_digest(attendu, recu)


def _hash_code(code):
    return hashlib.sha256(code.encode('utf-8')).hexdigest()


def _hashes_valides():
    brut = os.environ.get('FACENET_PROTOCOL_KEY_HASHES', '')
    return [h.strip().lower() for h in brut.split(',') if h.strip()]


def _ligne(user_id, creer=False):
    _assurer_tables()
    ligne = db.session.get(ProtectionPresidentielle, user_id)
    if ligne is None and creer:
        ligne = ProtectionPresidentielle(user_id=user_id)
        db.session.add(ligne)
    return ligne


def _activer(user_id, mode, reference=None):
    """Active le pack (le commit est fait par l'appelant)."""
    ligne = _ligne(user_id, creer=True)
    ligne.is_president_secure = 1
    ligne.anti_screenshot = 1
    ligne.mode_activation = mode
    ligne.reference_paiement = reference
    ligne.activated_at = datetime.utcnow()
    ligne.code_echecs = 0
    ligne.code_bloque_jusqua = None


def info_securite(user_id):
    """Lecture seule, ne lève jamais d'exception (utilisée dans profile.html)."""
    cache = g.setdefault('_psp_cache', {})
    if user_id in cache:
        return cache[user_id]
    res = {'secure': False, 'anti': False}
    try:
        _assurer_tables()
        ligne = db.session.get(ProtectionPresidentielle, user_id)
        if ligne and ligne.is_president_secure:
            res = {'secure': True, 'anti': bool(ligne.anti_screenshot)}
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
    cache[user_id] = res
    return res


@pack_securite_bp.app_context_processor
def _injecter_dans_les_templates():
    return {'psp_info': info_securite}   # utilisable partout : psp_info(user.id).secure


# ───────────────────────── Routes ─────────────────────────
@pack_securite_bp.route('/parametres/pack-securite')
@login_required
def page():
    ligne = _ligne(current_user.id)
    return render_template(
        'pack_securite.html',
        prix=PRIX_PACK_FCFA,
        actif=bool(ligne and ligne.is_president_secure),
        anti=bool(ligne and ligne.anti_screenshot),
        psp_csrf=_csrf_token(),
    )


@pack_securite_bp.route('/parametres/pack-securite/payer', methods=['POST'])
@login_required
def payer():
    if not _csrf_ok():
        flash("Session de sécurité expirée, veuillez réessayer.", "danger")
        return redirect(url_for('pack_securite.page'))
    ligne = _ligne(current_user.id)
    if ligne and ligne.is_president_secure:
        flash("Le Pack Sécurité Présidentielle est déjà actif.", "info")
        return redirect(url_for('pack_securite.page'))
    try:
        email = current_user.email or f"user{current_user.id}@facenet.cm"
        reponse = fapshi.initiate_pay({
            "amount": PRIX_PACK_FCFA,
            "email": email,
            "userId": str(current_user.id),
            "externalId": f"psp_{current_user.id}_{secrets.token_hex(4)}",
            "redirectUrl": url_for('pack_securite.retour', _external=True),
            "message": "Pack Securite Presidentielle FaceNet",
        })
        if reponse.get('statusCode') != 200:
            print(f"❌ Fapshi pack sécurité : {reponse}")
            flash("Le service de paiement est momentanément indisponible.", "danger")
            return redirect(url_for('pack_securite.page'))
        session['psp_trans_id'] = reponse['transId']   # clé distincte de celle des forfaits
        return redirect(reponse['link'])
    except Exception as e:
        print(f"❌ Fapshi pack sécurité (exception) : {e}")
        flash("Le service de paiement est momentanément indisponible.", "danger")
        return redirect(url_for('pack_securite.page'))


@pack_securite_bp.route('/parametres/pack-securite/retour')
@login_required
def retour():
    """Retour de Fapshi : activation uniquement si le paiement est confirmé côté serveur."""
    trans_id = session.get('psp_trans_id')
    if not trans_id:
        flash("Aucune transaction en cours.", "info")
        return redirect(url_for('pack_securite.page'))
    try:
        transaction = fapshi.payment_status(trans_id)
    except Exception as e:
        print(f"❌ Vérification Fapshi pack sécurité : {e}")
        transaction = {}
    if transaction.get('statusCode') != 200:
        flash("Vérification du paiement en cours… rechargez cette page dans un instant.", "info")
        return redirect(url_for('pack_securite.page'))

    statut = transaction.get('status')
    if statut in _STATUTS_ATTENTE_FAPSHI:
        flash("Paiement en attente de confirmation. Rechargez cette page dans un instant.", "info")
        return redirect(url_for('pack_securite.page'))
    if statut != 'SUCCESSFUL':
        session.pop('psp_trans_id', None)
        flash(f"Le paiement n'a pas abouti (statut : {statut}).", "warning")
        return redirect(url_for('pack_securite.page'))

    # Contrôles anti-fraude : montant, propriétaire de la transaction, transaction jamais réutilisée
    try:
        montant = int(float(transaction.get('amount')))
    except (TypeError, ValueError):
        montant = None
    externe = str(transaction.get('externalId') or '')
    deja_utilisee = ProtectionPresidentielle.query.filter(
        ProtectionPresidentielle.reference_paiement == trans_id,
        ProtectionPresidentielle.user_id != current_user.id).first()
    if (montant is not None and montant < PRIX_PACK_FCFA) \
            or (externe and not externe.startswith(f"psp_{current_user.id}_")) or deja_utilisee:
        session.pop('psp_trans_id', None)
        flash("Cette transaction ne correspond pas au Pack Sécurité Présidentielle.", "danger")
        return redirect(url_for('pack_securite.page'))

    _activer(current_user.id, 'paiement', trans_id)
    db.session.commit()
    session.pop('psp_trans_id', None)
    flash("Pack Sécurité Présidentielle activé. Votre profil est maintenant protégé.", "success")
    return redirect(url_for('pack_securite.page'))


@pack_securite_bp.route('/parametres/pack-securite/code', methods=['POST'])
@login_required
def activer_par_code():
    if not _csrf_ok():
        flash("Session de sécurité expirée, veuillez réessayer.", "danger")
        return redirect(url_for('pack_securite.page'))

    ligne = _ligne(current_user.id, creer=True)
    if ligne.is_president_secure:
        flash("Le Pack Sécurité Présidentielle est déjà actif.", "info")
        return redirect(url_for('pack_securite.page'))

    maintenant = datetime.utcnow()
    if ligne.code_bloque_jusqua and ligne.code_bloque_jusqua > maintenant:
        reste = math.ceil((ligne.code_bloque_jusqua - maintenant).total_seconds() / 60)
        flash(f"Trop de tentatives. Réessayez dans {reste} min.", "danger")
        return redirect(url_for('pack_securite.page'))

    code = (request.form.get('code_protocole') or '').strip().upper()
    h = _hash_code(code) if 0 < len(code) <= 64 else ''
    valide = False
    for ref in _hashes_valides():            # pas de sortie anticipée : durée constante
        if h and hmac.compare_digest(ref, h):
            valide = True
    if valide and ProtocolKeyUsage.query.filter_by(key_hash=h).first():
        valide = False                       # clé déjà utilisée

    if not valide:
        ligne.code_echecs = (ligne.code_echecs or 0) + 1
        if ligne.code_echecs >= MAX_ECHECS_CODE:
            ligne.code_bloque_jusqua = maintenant + timedelta(minutes=BLOCAGE_MINUTES)
            ligne.code_echecs = 0
        db.session.commit()
        flash("Code de protocole invalide.", "danger")   # message volontairement générique
        return redirect(url_for('pack_securite.page'))

    try:
        db.session.add(ProtocolKeyUsage(key_hash=h, user_id=current_user.id))
        _activer(current_user.id, 'protocole')
        db.session.commit()
    except IntegrityError:                   # clé grillée entre-temps par un autre compte
        db.session.rollback()
        flash("Code de protocole invalide.", "danger")
        return redirect(url_for('pack_securite.page'))

    flash("Mode Sécurité Présidentielle activé.", "success")
    return redirect(url_for('pack_securite.page'))


@pack_securite_bp.route('/parametres/pack-securite/anti-capture', methods=['POST'])
@login_required
def basculer_anti_capture():
    if not _csrf_ok():
        flash("Session de sécurité expirée, veuillez réessayer.", "danger")
        return redirect(url_for('pack_securite.page'))
    ligne = _ligne(current_user.id)
    if not (ligne and ligne.is_president_secure):
        flash("Activez d'abord le Pack Sécurité Présidentielle.", "warning")
        return redirect(url_for('pack_securite.page'))
    ligne.anti_screenshot = 1 if request.form.get('actif') == '1' else 0
    db.session.commit()
    return redirect(url_for('pack_securite.page'))