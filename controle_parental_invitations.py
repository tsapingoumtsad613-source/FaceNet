# ==========================================================================
#  CONTRÔLE PARENTAL PAR INVITATION  (module AJOUTÉ — rien d'existant n'est remplacé)
#
#  Parcours :
#    1. Le parent ouvre Paramètres > « Profil d'un enfant », voit la liste de SES AMIS et choisit
#       celui qu'il veut contrôler -> une invitation est envoyée (+ notification à l'enfant).
#    2. L'enfant doit D'ABORD accepter. Tant que ce n'est pas fait, rien n'est actif.
#    3. Une fois acceptée, le parent peut BLOQUER le compte de l'enfant à une date/heure précise
#       (jour, mois, année, heure, minute) jusqu'à une autre date, ou jusqu'à ce qu'il le lève.
#       -> On réutilise le verrou existant (table parental_lock de routes.py) : déconnexion
#          automatique à l'heure dite, connexion refusée même avec le bon mot de passe,
#          création de compte refusée sur le même appareil / la même IP / le même contact.
#    4. L'enfant bloqué voit « Demandez l'autorisation à votre parent ou tuteur avant d'accéder à
#       votre profil » et peut envoyer une demande : le parent reçoit une notification et peut
#       lever le blocage depuis ses paramètres.
#
#  Garde-fous : l'enfant doit être mineur (date de naissance connue), le parent ne peut pas être
#  mineur, l'invitation exige que les deux soient amis, seul le parent peut lever le blocage
#  (l'enfant ne peut pas le lever avec un mot de passe parental qu'il aurait créé lui-même).
# ==========================================================================
import re as _re
import hashlib as _hashlib
import time as _time
from datetime import datetime, timedelta, date

from flask import Blueprint, request, session, jsonify, render_template, redirect, url_for
from sqlalchemy import or_

from extensions import db
from models import User, Notification, DemandeAmitie

# Tout ce qui existe déjà dans routes.py est RÉUTILISÉ (import tardif des noms : aucune copie de logique).
import routes as _r

parental_invites_bp = Blueprint('parental_invites', __name__)

MSG_ENFANT_BLOQUE = "Demandez l'autorisation à votre parent ou tuteur avant d'accéder à votre profil."
LIEN_PARAMETRES = '/settings#parental-enfants'


# ──────────────────────────── Modèles ────────────────────────────
class ParentalInvite(db.Model):
    """Lien parent -> enfant. statut : en_attente | acceptee | refusee | annulee."""
    __tablename__ = 'parental_invite'
    id = db.Column(db.Integer, primary_key=True)
    guardian_id = db.Column(db.Integer, nullable=False, index=True)
    child_id = db.Column(db.Integer, nullable=False, index=True)
    statut = db.Column(db.String(12), nullable=False, default='en_attente', index=True)
    cree_le = db.Column(db.DateTime, default=datetime.utcnow)
    repondu_le = db.Column(db.DateTime, nullable=True)
    # Date de naissance figée à l'acceptation : modifier plus tard sa date de naissance ne met pas fin au contrôle.
    naissance = db.Column(db.Date, nullable=True)


class ParentalAuthRequest(db.Model):
    """Demande d'autorisation envoyée par un enfant bloqué à son parent."""
    __tablename__ = 'parental_auth_request'
    id = db.Column(db.Integer, primary_key=True)
    child_id = db.Column(db.Integer, nullable=False, index=True)
    guardian_id = db.Column(db.Integer, nullable=False, index=True)
    traitee = db.Column(db.Boolean, nullable=False, default=False)
    cree_le = db.Column(db.DateTime, default=datetime.utcnow)


class ParentalEmpreinte(db.Model):
    """Appareil d'un enfant sous contrôle (type, navigateur, réseau) : sert à refuser la création d'un autre compte."""
    __tablename__ = 'parental_empreinte'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    ua_hash = db.Column(db.String(40), nullable=False, index=True)
    fp = db.Column(db.String(64), nullable=True)
    ip_prefix = db.Column(db.String(48), nullable=True, index=True)
    appareil = db.Column(db.String(160), nullable=True)
    vu_le = db.Column(db.DateTime, default=datetime.utcnow)


_tables_ok = False


def _tables():
    global _tables_ok
    if _tables_ok:
        return
    try:
        for m in (ParentalInvite, ParentalAuthRequest, ParentalEmpreinte):
            m.__table__.create(bind=db.engine, checkfirst=True)
        _tables_ok = True
    except Exception as e:
        print(f"[parental-invitations] création des tables impossible : {e}")


# ──────────────────────────── Outils ────────────────────────────
def _age_depuis(n):
    if not n:
        return None
    auj = date.today()
    return auj.year - n.year - ((auj.month, auj.day) < (n.month, n.day))


def _age(user):
    return _age_depuis(getattr(user, 'birth_date', None))


def _carte(user):
    avatar = getattr(user, 'avatar', None) or 'default_avatar.png'
    return {'id': user.id,
            'nom': getattr(user, 'nom_complet', None) or user.username,
            'username': user.username,
            'avatar': '/static/uploads/' + avatar}


def _sont_amis(a, b):
    return DemandeAmitie.query.filter(
        DemandeAmitie.statut == 'acceptee',
        or_((DemandeAmitie.emetteur_id == a) & (DemandeAmitie.recepteur_id == b),
            (DemandeAmitie.emetteur_id == b) & (DemandeAmitie.recepteur_id == a))).first() is not None


def _raison_inegibilite_enfant(enfant):
    """None si le profil peut être placé sous contrôle, sinon la raison (texte affiché au parent)."""
    if _r._fn_is_admin(enfant):
        return "Ce profil ne peut pas être placé sous contrôle parental."
    age = _age(enfant)
    if age is None:
        if getattr(_r, 'PC_EXIGER_DATE_NAISSANCE', True):
            return "Date de naissance non renseignée : impossible de confirmer qu'il s'agit d'un mineur."
        return None
    if age >= 18:
        return "Profil majeur : le contrôle parental n'est pas applicable."
    return None


def _notifier(dest_id, acteur, type_, **contexte):
    """Passe par le service central notifications_service.notifier (types « parental_* » du CATALOGUE) :
    mêmes règles que toutes les autres notifications (texte, icône, lien, anti-doublon)."""
    try:
        from notifications_service import notifier
        if isinstance(acteur, int):
            acteur = db.session.get(User, acteur)
        notifier(dest_id, type_, acteur, cible=('user', getattr(acteur, 'id', 0) or 0), **contexte)
        db.session.commit()      # notifier() ne commit pas : c'est à l'appelant de le faire
    except Exception as e:
        db.session.rollback()
        print(f"[parental-invitations] notification impossible : {e}")


def _cloturer(user_id, type_, cle, valeur, statut):
    """Marque comme traitée (et lue) la notification d'invitation / de demande une fois l'action faite,
    pour que ses boutons disparaissent aussi dans la page Notifications."""
    try:
        for n in (Notification.query.filter_by(recipient_id=user_id, type=type_)
                  .order_by(Notification.created_at.desc()).limit(50).all()):
            ex = dict(n.extra_data or {})
            if ex.get(cle) == valeur and not ex.get('traitee'):
                ex['traitee'] = True
                ex['statut'] = statut
                n.extra_data = ex
                n.is_read = True
                n.read_at = datetime.utcnow()
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[parental-invitations] clôture de notification impossible : {e}")


# Petit cache (30 s) : « ce profil est-il sous la tutelle d'un parent ? » est demandé à chaque requête.
_cache_tutelle = {}


def _oublier_cache(*uids):
    for u in uids:
        _cache_tutelle.pop(u, None)
        _cache_tuteur.pop(u, None)


def enfant_sous_tutelle(uid, frais=False):
    """Renvoie l'id du parent si ce profil est sous contrôle (invitation acceptée et enfant encore mineur), sinon None."""
    if not uid:
        return None
    now = _time.time()
    if not frais:
        c = _cache_tutelle.get(uid)
        if c and c[0] > now:
            return c[1]
    res = None
    try:
        _tables()
        lien = ParentalInvite.query.filter_by(child_id=uid, statut='acceptee').first()
        if lien is not None:
            enfant = db.session.get(User, uid)
            age = _age_depuis(lien.naissance) if lien.naissance else (_age(enfant) if enfant else None)
            if age is not None and age >= 18:       # devenu majeur : le lien prend fin tout seul
                lien.statut = 'annulee'
                lien.repondu_le = datetime.utcnow()
                ligne = db.session.get(_r.ParentalLock, uid)
                if ligne is not None:
                    db.session.delete(ligne)
                db.session.commit()
            else:
                res = lien.guardian_id
    except Exception as e:
        db.session.rollback()
        print(f"[parental-invitations] lecture de la tutelle impossible : {e}")
        return None
    _cache_tutelle[uid] = (now + 30, res)
    return res


def _lien_du_parent(guardian_id, child_id, statut='acceptee'):
    _tables()
    return ParentalInvite.query.filter_by(guardian_id=guardian_id, child_id=child_id, statut=statut).first()


_cache_tuteur = {}


def tuteur_de(uid):
    """Id du tuteur d'un profil, quelle que soit la façon dont le lien a été créé :
    invitation acceptée (ce module) OU association faite avec l'assistant « Contrôle parental » (ParentalCompte)."""
    if not uid:
        return None
    g = enfant_sous_tutelle(uid)
    if g:
        return g
    now = _time.time()
    c = _cache_tuteur.get(uid)
    if c and c[0] > now:
        return c[1]
    res = None
    try:
        _r._pc_tables()
        ligne = db.session.get(_r.ParentalCompte, uid)
        res = ligne.guardian_id if ligne is not None else None
    except Exception as e:
        db.session.rollback()
        print(f"[parental-invitations] lecture du compte parental impossible : {e}")
        return None
    _cache_tuteur[uid] = (now + 30, res)
    return res


def _est_tuteur(guardian_id, child_id):
    """Vérification directe (sans cache) : ce parent contrôle-t-il bien ce profil ?"""
    if _lien_du_parent(guardian_id, child_id) is not None:
        return True
    try:
        _r._pc_tables()
        ligne = db.session.get(_r.ParentalCompte, child_id)
        return ligne is not None and ligne.guardian_id == guardian_id
    except Exception:
        db.session.rollback()
        return False


# ── Détection de l'appareil : type / modèle, navigateur, réseau ──
def _ip_prefix(ip):
    ip = (ip or '').strip()
    if ':' in ip:
        return ':'.join(ip.split(':')[:4])
    return '.'.join(ip.split('.')[:3]) if ip.count('.') == 3 else ip


def _libelle_appareil(ua):
    ua = ua or ''
    if not ua:
        return 'Appareil inconnu'
    m = _re.search(r'Android [\d.]+; ([^;)]+)', ua)
    if m:
        modele = m.group(1).strip()
        systeme = 'Android ' + (_re.search(r'Android ([\d.]+)', ua).group(1).split('.')[0])
        base = (modele if modele and modele.lower() not in ('k', 'mobile') else 'Téléphone') + ' · ' + systeme
    elif 'iPhone' in ua or 'iPad' in ua:
        v = _re.search(r'OS (\d+)[_\d]*', ua)
        base = ('iPhone' if 'iPhone' in ua else 'iPad') + ' · iOS' + (' ' + v.group(1) if v else '')
    elif 'Windows' in ua:
        base = 'Ordinateur Windows'
    elif 'Macintosh' in ua:
        base = 'Mac'
    elif 'Linux' in ua:
        base = 'Ordinateur Linux'
    else:
        base = 'Appareil'
    for cle, nom in (('Edg', 'Edge'), ('OPR', 'Opera'), ('SamsungBrowser', 'Samsung Internet'), ('Firefox', 'Firefox'),
                     ('CriOS', 'Chrome'), ('Chrome', 'Chrome'), ('Safari', 'Safari')):
        if cle in ua:
            return f"{base} · {nom}"
    return base


def _signature_requete():
    ua = request.headers.get('User-Agent', '') or ''
    return ua, _hashlib.sha1(ua.encode('utf-8', 'ignore')).hexdigest(), _ip_prefix(_r._fn_ip()), (_r._pl_fp() or None)


_derniere_empreinte = {}


def enregistrer_empreinte(uid):
    """Mémorise (au plus toutes les 10 min) l'appareil courant d'un enfant sous contrôle."""
    ua, h, pref, fp = _signature_requete()
    cle = (uid, h, pref)
    now = _time.time()
    if _derniere_empreinte.get(cle, 0) > now - 600:
        return
    _derniere_empreinte[cle] = now
    _tables()
    ligne = ParentalEmpreinte.query.filter_by(user_id=uid, ua_hash=h, ip_prefix=pref).first()
    if ligne is None:
        db.session.add(ParentalEmpreinte(user_id=uid, ua_hash=h, fp=fp, ip_prefix=pref, appareil=_libelle_appareil(ua)[:160]))
    else:
        ligne.vu_le = datetime.utcnow()
        if fp:
            ligne.fp = fp
    db.session.commit()


def empreinte_correspond(actifs):
    """Appelé par _pl_appareil_verrouille() (routes.py) à l'inscription : True si l'appareil qui essaie de créer un compte
    ressemble à celui d'un enfant dont le blocage est en cours (même réseau + même empreinte, ou même modèle si l'empreinte manque).
    Plus tolérant que la règle d'origine sur l'IP (même réseau /24 au lieu de l'IP exacte : l'IP mobile change souvent)."""
    try:
        if not actifs:
            return False
        _tables()
        ua, h, pref, fp = _signature_requete()
        if not pref:
            return False
        for e in ParentalEmpreinte.query.filter(ParentalEmpreinte.user_id.in_(actifs), ParentalEmpreinte.ip_prefix == pref).all():
            if fp and e.fp:
                if fp == e.fp:
                    return True
            elif e.ua_hash == h:
                return True
        return False
    except Exception as ex:
        db.session.rollback()
        print(f"[parental-invitations] comparaison d'empreinte impossible : {ex}")
        return False


def _appareil_de(child_id):
    e = ParentalEmpreinte.query.filter_by(user_id=child_id).order_by(ParentalEmpreinte.vu_le.desc()).first()
    return {'libelle': e.appareil, 'vu_ms': _r._pl_ms(e.vu_le)} if e is not None else None


def _etat_verrou(child_id):
    ligne = _r._pl_ligne(child_id)
    if ligne is None or ligne.fin <= datetime.utcnow():
        return None
    return {'debut_ms': _r._pl_ms(ligne.debut), 'fin_ms': _r._pl_ms(ligne.fin),
            'en_cours': ligne.debut <= datetime.utcnow(),
            'indefini': (ligne.fin - datetime.utcnow()).days > (_r.PL_DUREE_MAX_JOURS - 400)}


# ──────────────────────────── API (côté paramètres) ────────────────────────────
@parental_invites_bp.route('/api/fn/parental/enfants/amis', methods=['GET'])
@_r._fn_api()
def pe_amis():
    uid = _r._fn_uid()
    _tables()
    moi = db.session.get(User, uid)
    if moi is None:
        return _r._fn_err('Connexion requise.', 401)
    age_moi = _age(moi)
    if age_moi is not None and age_moi < 18:
        return _r._fn_ok(amis=[], bloque="Seul un adulte peut contrôler le profil d'un enfant.")
    ids = set()
    for d in DemandeAmitie.query.filter(DemandeAmitie.statut == 'acceptee',
                                        or_(DemandeAmitie.emetteur_id == uid, DemandeAmitie.recepteur_id == uid)).all():
        ids.add(d.recepteur_id if d.emetteur_id == uid else d.emetteur_id)
    ids.discard(uid)
    if not ids:
        return _r._fn_ok(amis=[])
    liens = {l.child_id: l.statut for l in ParentalInvite.query.filter(
        ParentalInvite.guardian_id == uid, ParentalInvite.child_id.in_(ids),
        ParentalInvite.statut.in_(('en_attente', 'acceptee'))).all()}
    sortie = []
    for u in User.query.filter(User.id.in_(ids)).all():
        c = _carte(u)
        raison = _raison_inegibilite_enfant(u)
        if u.id in liens:
            raison = 'Invitation envoyée' if liens[u.id] == 'en_attente' else 'Déjà sous votre contrôle'
        c['eligible'] = raison is None
        c['raison'] = raison
        sortie.append(c)
    sortie.sort(key=lambda x: (not x['eligible'], x['nom'].lower()))
    return _r._fn_ok(amis=sortie)


@parental_invites_bp.route('/api/fn/parental/enfants/etat', methods=['GET'])
@_r._fn_api()
def pe_etat():
    uid = _r._fn_uid()
    _tables()
    out = {'enfants': [], 'demandes': [], 'invitations': [], 'tuteur': None}
    for l in ParentalInvite.query.filter(ParentalInvite.guardian_id == uid,
                                         ParentalInvite.statut.in_(('en_attente', 'acceptee'))).all():
        e = db.session.get(User, l.child_id)
        if e is None:
            continue
        out['enfants'].append({'child': _carte(e), 'statut': l.statut, 'via': 'invitation',
                               'verrou': _etat_verrou(e.id) if l.statut == 'acceptee' else None,
                               'appareil': _appareil_de(e.id) if l.statut == 'acceptee' else None})
    try:       # enfants déjà associés avec l'assistant « Contrôle parental » : mêmes outils de blocage
        _r._pc_tables()
        deja = {x['child']['id'] for x in out['enfants']}
        for pc in _r.ParentalCompte.query.filter_by(guardian_id=uid).all():
            e = db.session.get(User, pc.child_id)
            if e is not None and e.id not in deja:
                out['enfants'].append({'child': _carte(e), 'statut': 'acceptee', 'via': 'assistant',
                                       'verrou': _etat_verrou(e.id), 'appareil': _appareil_de(e.id)})
    except Exception as ex:
        db.session.rollback()
        print(f"[parental-invitations] enfants de l'assistant non listés : {ex}")
    for q in ParentalAuthRequest.query.filter_by(guardian_id=uid, traitee=False).order_by(ParentalAuthRequest.cree_le.desc()).limit(30).all():
        e = db.session.get(User, q.child_id)
        if e is not None and _est_tuteur(uid, e.id):
            out['demandes'].append({'id': q.id, 'child': _carte(e), 'cree_ms': _r._pl_ms(q.cree_le)})
    for l in ParentalInvite.query.filter_by(child_id=uid, statut='en_attente').all():
        g = db.session.get(User, l.guardian_id)
        if g is not None:
            out['invitations'].append({'id': l.id, 'guardian': _carte(g), 'cree_ms': _r._pl_ms(l.cree_le)})
    gid = tuteur_de(uid)
    if gid:
        g = db.session.get(User, gid)
        if g is not None:
            out['tuteur'] = {'guardian': _carte(g), 'verrou': _etat_verrou(uid)}
    return _r._fn_ok(**out)


@parental_invites_bp.route('/api/fn/parental/enfants/inviter', methods=['POST'])
@_r._fn_api()
def pe_inviter():
    uid = _r._fn_uid()
    data = request.get_json(silent=True) or {}
    if not _r._fn_rate_ok(f'pe_inviter:{uid}', 10, 3600):
        return _r._fn_err('Trop d\'invitations envoyées. Réessayez plus tard.', 429)
    _tables()
    try:
        child_id = int(data.get('child_id'))
    except (TypeError, ValueError):
        return _r._fn_err('Choisissez un ami.', 400)
    moi = db.session.get(User, uid)
    enfant = db.session.get(User, child_id)
    if moi is None or enfant is None or child_id == uid:
        return _r._fn_err('Profil introuvable.', 404)
    age_moi = _age(moi)
    if age_moi is not None and age_moi < 18:
        return _r._fn_err("Seul un adulte peut contrôler le profil d'un enfant.", 403)
    if not _sont_amis(uid, child_id):
        return _r._fn_err('Vous ne pouvez inviter que vos amis.', 403)
    raison = _raison_inegibilite_enfant(enfant)
    if raison:
        return _r._fn_err(raison, 403)
    if ParentalInvite.query.filter_by(child_id=child_id, statut='acceptee').first() is not None:
        return _r._fn_err('Ce profil est déjà sous le contrôle d\'un parent.', 409)
    existante = ParentalInvite.query.filter_by(guardian_id=uid, child_id=child_id, statut='en_attente').first()
    if existante is not None:
        return _r._fn_err('Une invitation est déjà en attente de réponse.', 409)
    inv = ParentalInvite(guardian_id=uid, child_id=child_id)
    db.session.add(inv)
    db.session.commit()
    _notifier(child_id, moi, 'parental_invite', invitation_id=inv.id)
    _r._fn_audit(uid, 'parental_invitation', f"Invitation envoyée au profil #{child_id}")
    return _r._fn_ok(invitation_id=inv.id)


@parental_invites_bp.route('/api/fn/parental/enfants/repondre', methods=['POST'])
@_r._fn_api()
def pe_repondre():
    """L'enfant accepte ou refuse. Rien n'est actif tant qu'il n'a pas accepté."""
    uid = _r._fn_uid()
    data = request.get_json(silent=True) or {}
    _tables()
    try:
        inv = db.session.get(ParentalInvite, int(data.get('invitation_id')))
    except (TypeError, ValueError):
        inv = None
    if inv is None or inv.child_id != uid or inv.statut != 'en_attente':
        return _r._fn_err('Invitation introuvable ou déjà traitée.', 404)
    moi = db.session.get(User, uid)
    parent = db.session.get(User, inv.guardian_id)
    if data.get('accepter'):
        raison = _raison_inegibilite_enfant(moi)
        if raison:
            return _r._fn_err(raison, 403)
        if ParentalInvite.query.filter_by(child_id=uid, statut='acceptee').first() is not None:
            return _r._fn_err('Votre profil est déjà sous le contrôle d\'un parent.', 409)
        inv.statut = 'acceptee'
        inv.naissance = getattr(moi, 'birth_date', None)
    else:
        inv.statut = 'refusee'
    inv.repondu_le = datetime.utcnow()
    db.session.commit()
    _oublier_cache(uid)
    if inv.statut == 'acceptee':
        try:
            _r._pl_enregistrer_appareil(uid)     # mémorise tout de suite l'appareil de l'enfant (anti-contournement)
        except Exception:
            db.session.rollback()
    _cloturer(uid, 'parental_invite', 'invitation_id', inv.id, inv.statut)
    if parent is not None:
        _notifier(parent.id, moi, 'parental_reponse', reponse='accepté' if inv.statut == 'acceptee' else 'refusé')
    _r._fn_audit(uid, 'parental_invitation_reponse', inv.statut)
    return _r._fn_ok(statut=inv.statut)


def _parse_verrou(data):
    now = datetime.utcnow()
    fin = None
    if data.get('indefini'):
        fin = now + timedelta(days=_r.PL_DUREE_MAX_JOURS - 1)
    else:
        fin = _r._pl_parse_iso(data.get('fin'))
    debut = _r._pl_parse_iso(data.get('debut')) if data.get('debut') else None
    if fin is None:
        return None, None, "Choisissez la date et l'heure de déblocage (ou « jusqu'à ce que je le lève »)."
    if debut is None or debut < now:
        debut = now
    if fin <= debut + timedelta(minutes=1):
        return None, None, 'Le déblocage doit être postérieur au début du blocage.'
    if fin > now + timedelta(days=_r.PL_DUREE_MAX_JOURS):
        return None, None, 'La durée maximale du blocage est de 10 ans.'
    return debut, fin, None


@parental_invites_bp.route('/api/fn/parental/enfants/verrou', methods=['POST'])
@_r._fn_api()
def pe_verrou():
    uid = _r._fn_uid()
    data = request.get_json(silent=True) or {}
    _tables()
    try:
        child_id = int(data.get('child_id'))
    except (TypeError, ValueError):
        return _r._fn_err('Profil introuvable.', 404)
    if not _est_tuteur(uid, child_id):
        return _r._fn_err("Vous ne contrôlez pas ce profil (l'enfant doit d'abord accepter votre invitation).", 403)
    enfant = db.session.get(User, child_id)
    action = data.get('action')
    if action == 'clear':
        ligne = _r._pl_ligne(child_id)
        if ligne is not None:
            db.session.delete(ligne)
            db.session.commit()
        _r._fn_audit(child_id, 'parental_verrou_leve', f"Blocage levé par le parent #{uid}")
        _notifier(child_id, uid, 'parental_deblocage')
        return _r._fn_ok(verrou=None)
    if action != 'set':
        return _r._fn_err('Action inconnue.', 400)
    raison = _raison_inegibilite_enfant(enfant)
    if raison:
        return _r._fn_err(raison, 403)
    debut, fin, erreur = _parse_verrou(data)
    if erreur:
        return _r._fn_err(erreur, 400)
    ligne = _r._pl_ligne(child_id)
    if ligne is None:
        db.session.add(_r.ParentalLock(user_id=child_id, debut=debut, fin=fin))
    else:
        ligne.debut, ligne.fin = debut, fin
    db.session.commit()
    _r._fn_audit(child_id, 'parental_verrou_pose',
                 f"Par le parent #{uid} : du {debut:%d/%m/%Y %H:%M} au {fin:%d/%m/%Y %H:%M} (UTC)")
    if debut > datetime.utcnow() + timedelta(seconds=30):
        _notifier(child_id, uid, 'parental_blocage')
    return _r._fn_ok(verrou=_etat_verrou(child_id))


@parental_invites_bp.route('/api/fn/parental/enfants/retirer', methods=['POST'])
@_r._fn_api()
def pe_retirer():
    """Le parent annule une invitation ou met fin au contrôle (le blocage éventuel est levé)."""
    uid = _r._fn_uid()
    data = request.get_json(silent=True) or {}
    _tables()
    try:
        child_id = int(data.get('child_id'))
    except (TypeError, ValueError):
        return _r._fn_err('Profil introuvable.', 404)
    lien = ParentalInvite.query.filter(ParentalInvite.guardian_id == uid, ParentalInvite.child_id == child_id,
                                       ParentalInvite.statut.in_(('en_attente', 'acceptee'))).first()
    if lien is None:
        return _r._fn_err('Aucun contrôle en cours pour ce profil.', 404)
    etait_actif = lien.statut == 'acceptee'
    lien.statut = 'annulee'
    lien.repondu_le = datetime.utcnow()
    if etait_actif:
        ligne = _r._pl_ligne(child_id)
        if ligne is not None:
            db.session.delete(ligne)
        for q in ParentalAuthRequest.query.filter_by(child_id=child_id, traitee=False).all():
            q.traitee = True
    db.session.commit()
    _oublier_cache(child_id)
    if etait_actif:
        _notifier(child_id, uid, 'parental_fin')
    _r._fn_audit(uid, 'parental_lien_retire', f"Profil #{child_id}")
    return _r._fn_ok()


@parental_invites_bp.route('/api/fn/parental/enfants/demande', methods=['POST'])
@_r._fn_api()
def pe_traiter_demande():
    """Le parent répond à une demande d'autorisation : autoriser (lève le blocage) ou ignorer."""
    uid = _r._fn_uid()
    data = request.get_json(silent=True) or {}
    _tables()
    try:
        q = db.session.get(ParentalAuthRequest, int(data.get('id')))
    except (TypeError, ValueError):
        q = None
    if q is None or q.guardian_id != uid or q.traitee:
        return _r._fn_err('Demande introuvable ou déjà traitée.', 404)
    if not _est_tuteur(uid, q.child_id):
        return _r._fn_err('Ce profil n\'est plus sous votre contrôle.', 403)
    q.traitee = True
    if data.get('autoriser'):
        ligne = _r._pl_ligne(q.child_id)
        if ligne is not None:
            db.session.delete(ligne)
        _r._fn_audit(q.child_id, 'parental_verrou_leve', f"Autorisation accordée par le parent #{uid}")
    db.session.commit()
    _cloturer(uid, 'parental_demande', 'auth_id', q.id, 'autorise' if data.get('autoriser') else 'ignore')
    if data.get('autoriser'):
        _notifier(q.child_id, uid, 'parental_deblocage')
    return _r._fn_ok()


# ──────────────────────────── Côté enfant bloqué (sans session ouverte) ────────────────────────────
def rendre_page_enfant_bloque(user, ligne):
    """Appelé par profil_verrouille() : page dédiée si le blocage vient d'un parent, sinon None (page d'origine)."""
    if tuteur_de(user.id) is None:
        return None
    avatar = getattr(user, 'avatar', None) or 'default_avatar.png'
    try:       # enfant associé par l'assistant : le tuteur peut aussi déverrouiller sur place avec son mot de passe parental
        sec = db.session.get(_r.FnSecurity, user.id)
        mdp_tuteur = enfant_sous_tutelle(user.id) is None and bool(sec and sec.parental_enabled)
    except Exception:
        db.session.rollback()
        mdp_tuteur = False
    return render_template('parental_enfant_bloque.html',
                           nom=getattr(user, 'nom_complet', None) or user.username,
                           avatar_url=url_for('static', filename='uploads/' + avatar),
                           debut_ms=_r._pl_ms(ligne.debut), fin_ms=_r._pl_ms(ligne.fin),
                           serveur_ms=_r._pl_ms(datetime.utcnow()),
                           indefini=(ligne.fin - datetime.utcnow()).days > (_r.PL_DUREE_MAX_JOURS - 400),
                           message=MSG_ENFANT_BLOQUE, mdp_tuteur=mdp_tuteur, csrf_token=str(_r._fn_csrf_token()))


def _enfant_depuis_session():
    uid = session.get('pl_uid')
    if not uid or _time.time() - (session.get('pl_ts') or 0) > 3600:
        return None
    return db.session.get(User, uid)


@parental_invites_bp.route('/profil-verrouille/demande-autorisation', methods=['POST'])
def pe_demande_autorisation():
    enfant = _enfant_depuis_session()
    if enfant is None:
        return jsonify(success=False, error='Session expirée. Reconnectez-vous.', redirect=url_for('main.login')), 401
    if not _r._fn_csrf_ok():
        return jsonify(success=False, error='Jeton de sécurité invalide. Rechargez la page.'), 403
    gid = tuteur_de(enfant.id)
    if gid is None:
        return jsonify(success=False, error="Aucun parent n'est associé à ce profil."), 404
    if not (_r._fn_rate_ok(f'pe_dem:{enfant.id}', 3, 3600) and _r._fn_rate_ok(f'pe_dem_ip:{_r._fn_ip()}', 10, 3600)):
        return jsonify(success=False, error='Demande déjà envoyée. Patientez avant de réessayer.'), 429
    _tables()
    deja = ParentalAuthRequest.query.filter_by(child_id=enfant.id, traitee=False).first()
    if deja is None:
        demande = ParentalAuthRequest(child_id=enfant.id, guardian_id=gid)
        db.session.add(demande)
        db.session.commit()
        _notifier(gid, enfant, 'parental_demande', auth_id=demande.id)
    return jsonify(success=True, message='Votre demande a été envoyée à votre parent.')


@parental_invites_bp.route('/profil-verrouille/etat', methods=['GET'])
def pe_etat_blocage():
    """Interrogé par la page de blocage : dit si le blocage est levé (pour proposer la reconnexion)."""
    enfant = _enfant_depuis_session()
    if enfant is None:
        return jsonify(locked=False, redirect=url_for('main.login'))
    return jsonify(locked=_r._pl_actif(enfant.id) is not None)


# ──────────────────────────── Appareil de l'enfant (avant même le blocage) ────────────────────────────
@parental_invites_bp.after_app_request
def _suivi_appareil_enfant(response):
    """Dès que l'invitation est acceptée, on mémorise l'appareil (cookie + empreinte + IP) de l'enfant, comme
    le fait déjà routes.py pour un profil verrouillé. Ainsi la création d'un autre compte est refusée dès le blocage."""
    try:
        uid = _r._fn_uid()
        if not uid or request.path.startswith('/static/') or request.endpoint in (None, 'static'):
            return response
        if tuteur_de(uid) is None:
            return response
        enregistrer_empreinte(uid)                # type d'appareil + navigateur + réseau (anti-contournement à l'inscription)
        if db.session.get(_r.ParentalLock, uid) is not None:
            return response                      # routes.py s'en occupe déjà (cookie + empreinte + IP)
        dev = _r._pl_enregistrer_appareil(uid)
        if request.cookies.get('fn_dev') != dev:
            response.set_cookie('fn_dev', dev, max_age=5 * 365 * 86400, httponly=True,
                                samesite='Lax', secure=request.is_secure)
        if (response.status_code == 200 and response.mimetype == 'text/html' and not response.direct_passthrough
                and request.method == 'GET' and not request.path.startswith('/api/')
                and request.headers.get('Sec-Fetch-Dest') not in ('iframe', 'frame')):
            html = response.get_data(as_text=True)
            i = html.rfind('</body>')
            if i != -1 and 'id="pl-watch"' not in html:
                tag = '<script src="/fn/parental-watch.js?mode=watch&v=1" id="pl-watch" defer></script>'
                response.set_data(html[:i] + tag + html[i:])
    except Exception as e:
        try:
            db.session.rollback()
        except Exception:
            pass
        print(f"[parental-invitations] suivi de l'appareil : {e}")
    return response


def brancher(app):
    """À appeler dans app.py avant db.create_all() : enregistre le blueprint."""
    app.register_blueprint(parental_invites_bp)