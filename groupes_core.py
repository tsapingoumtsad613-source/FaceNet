"""
groupes_core.py — Noyau du module « Groupes FaceNet » : blueprint, droits d'accès, sécurité, sérialisation.

Cohérent avec ton application (comme marketplace_pro.py) :
  * l'utilisateur connecté se lit avec session['user_id'] ;
  * les blocages utilisent ton modèle BlockedUser ;
  * les images sont enregistrées dans static/uploads/groupes/.

Sécurité intégrée :
  * toute requête qui modifie quelque chose (POST) doit porter l'en-tête X-Requested-With: XMLHttpRequest
    (un site tiers ne peut pas l'envoyer → protection CSRF) ;
  * droits vérifiés CÔTÉ SERVEUR à chaque appel (membre / modérateur / admin) ;
  * groupes secrets invisibles (404) pour les non-membres, bannis exclus ;
  * images contrôlées (extension + signature binaire + 5 Mo max) ;
  * texte nettoyé et limité ; l'affichage se fait en textContent côté navigateur (pas de HTML injecté).
"""
import json
import os
import re
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone

from flask import Blueprint, current_app, g as flask_g, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import func, or_
from werkzeug.exceptions import HTTPException

from extensions import db
from groupes_models import (Grp, GrpCom, GrpEvenement, GrpInvitation, GrpJournal, GrpMembre, GrpNotif, GrpOption, GrpPost,
                            GrpReaction, GrpRsvp, GrpVote, REACTIONS)
from models import BlockedUser, User

groupes_pro_bp = Blueprint('groupes_pro', __name__, url_prefix='/g')

SAFE_METHODS = ('GET', 'HEAD', 'OPTIONS')
MAX_POST, MAX_COM = 5000, 1500
MAX_IMAGE_OCTETS = 5 * 1024 * 1024
MAX_IMAGES_PAR_POST = 4
EXT_IMAGES = {'jpg', 'jpeg', 'png', 'gif', 'webp'}
MAX_GROUPES_CREES = 15
PAGE = 15


# =============================================================================
# Erreurs
# =============================================================================
class Erreur(Exception):
    def __init__(self, message, code=400):
        super().__init__(message)
        self.message, self.code = message, code


@groupes_pro_bp.errorhandler(Erreur)
def _gerer_erreur(e):
    db.session.rollback()
    if request.path.startswith('/g/api/'):
        return _json(False, e.code, message=e.message)
    return render_template('grp_erreur.html', message=e.message), e.code


@groupes_pro_bp.errorhandler(Exception)
def _gerer_inattendu(e):
    if isinstance(e, HTTPException):
        return e
    db.session.rollback()
    current_app.logger.exception('Erreur groupes_pro')
    if request.path.startswith('/g/api/'):
        return _json(False, 500, message='Erreur interne du serveur.')
    raise e


def _json(ok=True, status=200, **donnees):
    donnees['success'] = ok
    if not ok:
        donnees.setdefault('error', donnees.get('message', ''))
    return jsonify(donnees), status


# =============================================================================
# Utilisateur courant + décorateur
# =============================================================================
def moi():
    if not hasattr(flask_g, '_grp_moi'):
        uid = session.get('user_id')
        flask_g._grp_moi = db.session.get(User, int(uid)) if uid else None
    return flask_g._grp_moi


def connecte(f):
    from functools import wraps

    @wraps(f)
    def enveloppe(*a, **k):
        if moi() is None:
            if request.path.startswith('/g/api/'):
                return _json(False, 401, message='Connexion requise.')
            return redirect(url_for('main.login'))
        if request.method not in SAFE_METHODS and request.headers.get('X-Requested-With') != 'XMLHttpRequest':
            return _json(False, 403, message='Requête refusée.')
        return f(*a, **k)
    return enveloppe


def site_admin(u):
    return bool(getattr(u, 'is_pdg', False))


# =============================================================================
# Droits d'accès
# =============================================================================
class Acces:
    """Ce que l'utilisateur `u` a le droit de faire dans le groupe `gr` (calculé une seule fois)."""

    def __init__(self, gr, u):
        self.m = GrpMembre.query.filter_by(groupe_id=gr.id, user_id=u.id).first()
        self.actif = bool(self.m and self.m.statut == 'actif')
        self.banni = bool(self.m and self.m.statut == 'banni')
        self.site = site_admin(u)
        self.role = self.m.role if self.actif else None
        self.admin = self.site or self.role == 'admin'
        self.staff = self.admin or self.role == 'moderateur'
        self.voit = (not self.banni) and (gr.visibilite == 'public' or self.actif or self.site)
        self.invitation = GrpInvitation.query.filter_by(groupe_id=gr.id, invite_id=u.id, statut='en_attente').first()

    def muet(self):
        return bool(self.m and self.actif and self.m.est_muet())


def groupe_et_acces(gid):
    """Charge le groupe ; les groupes secrets sont 404 pour qui n'y a pas sa place."""
    u = moi()
    gr = db.session.get(Grp, gid)
    if not gr:
        raise Erreur('Groupe introuvable.', 404)
    a = Acces(gr, u)
    if gr.visibilite == 'secret' and not (a.actif or a.site or a.invitation):
        raise Erreur('Groupe introuvable.', 404)
    if a.banni:
        raise Erreur('Vous avez été banni de ce groupe.', 403)
    return gr, a


def exiger_voir(gr, a):
    if not a.voit:
        raise Erreur('Rejoignez ce groupe pour voir son contenu.', 403)


def exiger_membre(gr, a):
    if not a.actif:
        raise Erreur('Vous devez être membre de ce groupe.', 403)


def exiger_staff(gr, a):
    if not a.staff:
        raise Erreur('Réservé aux modérateurs et administrateurs.', 403)


def exiger_admin(gr, a):
    if not a.admin:
        raise Erreur('Réservé aux administrateurs du groupe.', 403)


def exiger_ecriture(gr, a):
    """Membre actif, non muet, groupe non archivé (le staff peut toujours écrire)."""
    exiger_membre(gr, a)
    if gr.archive and not a.staff:
        raise Erreur('Ce groupe est archivé : lecture seule.', 403)
    if a.muet():
        raise Erreur('Vous êtes temporairement réduit au silence dans ce groupe (jusqu’au %s UTC).'
                     % a.m.muet_jusqua.strftime('%d/%m/%Y %H:%M'), 403)


def blocage_entre(a_id, b_id):
    return BlockedUser.query.filter(or_(
        (BlockedUser.owner_id == a_id) & (BlockedUser.blocked_id == b_id),
        (BlockedUser.owner_id == b_id) & (BlockedUser.blocked_id == a_id))).first() is not None


# =============================================================================
# Texte et fichiers
# =============================================================================
_CTRL = re.compile(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]')
_URL = re.compile(r'(https?://|www\.)\S+', re.I)


def propre(txt, maxi):
    return _CTRL.sub('', (txt or '').replace('\r\n', '\n')).strip()[:maxi]


def norm(txt):
    t = unicodedata.normalize('NFD', (txt or '').lower())
    return ''.join(c for c in t if unicodedata.category(c) != 'Mn')


def mots_interdits(gr):
    return [m for m in (norm(x).strip() for x in re.split(r'[\n,;]', gr.mots_interdits or '')) if len(m) >= 2]


def contient_interdit(gr, texte):
    t = norm(texte)
    return next((m for m in mots_interdits(gr) if m in t), None)


def nb_liens(texte):
    return len(_URL.findall(texte or ''))


def parse_dt(s):
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s).replace('Z', '+00:00'))
    except ValueError:
        raise Erreur('Date invalide.')
    return d.astimezone(timezone.utc).replace(tzinfo=None) if d.tzinfo else d


def iso(dt):
    return dt.isoformat() + 'Z' if dt else ''


def _signature_image_ok(data):
    return (data[:3] == b'\xff\xd8\xff' or data[:8] == b'\x89PNG\r\n\x1a\n' or data[:6] in (b'GIF87a', b'GIF89a')
            or (data[:4] == b'RIFF' and data[8:12] == b'WEBP'))


def sauver_image(fs):
    """Enregistre une image envoyée (contrôles stricts) et renvoie son chemin relatif à static/uploads/."""
    if not fs or not fs.filename:
        return None
    ext = fs.filename.rsplit('.', 1)[-1].lower() if '.' in fs.filename else ''
    if ext not in EXT_IMAGES:
        raise Erreur('Format d’image non autorisé (jpg, png, gif ou webp).')
    data = fs.read(MAX_IMAGE_OCTETS + 1)
    if len(data) > MAX_IMAGE_OCTETS:
        raise Erreur('Image trop lourde (5 Mo maximum).')
    if not _signature_image_ok(data):
        raise Erreur('Fichier image invalide.')
    dossier = os.path.join(current_app.static_folder, 'uploads', 'groupes')
    os.makedirs(dossier, exist_ok=True)
    nom = uuid.uuid4().hex + '.' + ('jpg' if ext == 'jpeg' else ext)
    with open(os.path.join(dossier, nom), 'wb') as f:
        f.write(data)
    return 'groupes/' + nom


def url_upload(rel, defaut=None):
    rel = rel or defaut
    return url_for('static', filename='uploads/' + rel) if rel else ''


# =============================================================================
# Notifications + journal d'audit
# =============================================================================
def notifier(user_ids, gr, texte, lien=''):
    for uid in set(user_ids):
        db.session.add(GrpNotif(user_id=uid, groupe_id=gr.id, texte=texte[:300], lien=lien or url_for('groupes_pro.page', gid=gr.id)))


def staff_ids(gr):
    return [m.user_id for m in GrpMembre.query.filter(GrpMembre.groupe_id == gr.id, GrpMembre.statut == 'actif',
                                                       GrpMembre.role.in_(('admin', 'moderateur'))).all()]


def journal(gr, acteur_id, action, cible='', detail=''):
    db.session.add(GrpJournal(groupe_id=gr.id, acteur_id=acteur_id, action=action, cible=str(cible)[:80], detail=str(detail)[:300]))


# =============================================================================
# Sérialisation
# =============================================================================
def users_par_id(ids):
    ids = {i for i in ids if i}
    return {u.id: u for u in User.query.filter(User.id.in_(ids)).all()} if ids else {}


def user_min(u, role=None):
    if u is None:
        return {'id': 0, 'nom': 'Utilisateur supprimé', 'avatar': url_upload('default_avatar.png'), 'profil': '#', 'role': role}
    return {'id': u.id, 'nom': getattr(u, 'nom_complet', None) or u.username, 'username': u.username,
            'avatar': url_upload(getattr(u, 'avatar', None), 'default_avatar.png'), 'profil': '/profil/%d' % u.id, 'role': role}


def groupe_json(gr, a, detail=False):
    d = {'id': gr.id, 'nom': gr.nom, 'description': gr.description or '', 'categorie': gr.categorie, 'visibilite': gr.visibilite,
         'avatar': url_upload(gr.avatar, 'default_groupe.png'), 'couverture': url_upload(gr.couverture),
         'nb_membres': gr.nb_membres, 'archive': gr.archive, 'cree_le': iso(gr.cree_le),
         'mon_role': a.role, 'est_membre': a.actif, 'peut_moderer': a.staff, 'peut_gerer': a.admin,
         'invitation_id': a.invitation.id if a.invitation else None,
         'demande_en_attente': bool(not a.actif and demande_en_attente(gr.id, moi().id)),
         'peut_voir': a.voit}
    if detail:
        from groupes_models import GrpQuestion, GrpRegle
        d.update({'validation_adhesion': gr.validation_adhesion, 'validation_publications': gr.validation_publications,
                  'qui_peut_publier': gr.qui_peut_publier, 'qui_peut_inviter': gr.qui_peut_inviter,
                  'publications_anonymes': gr.publications_anonymes, 'anti_flood_secondes': gr.anti_flood_secondes,
                  'peut_publier': a.actif and not gr.archive and not a.muet() and (gr.qui_peut_publier == 'tous' or a.staff),
                  'peut_inviter': a.actif and (gr.qui_peut_inviter == 'tous' or a.staff),
                  'questions': [{'id': q.id, 'texte': q.texte} for q in GrpQuestion.query.filter_by(groupe_id=gr.id).order_by(GrpQuestion.ordre, GrpQuestion.id)],
                  'regles': [{'titre': r.titre, 'detail': r.detail} for r in GrpRegle.query.filter_by(groupe_id=gr.id).order_by(GrpRegle.ordre, GrpRegle.id)]})
        staff = GrpMembre.query.filter(GrpMembre.groupe_id == gr.id, GrpMembre.statut == 'actif',
                                       GrpMembre.role.in_(('admin', 'moderateur'))).order_by(GrpMembre.role, GrpMembre.id).limit(12).all()
        us = users_par_id([m.user_id for m in staff])
        d['equipe'] = [user_min(us.get(m.user_id), m.role) for m in staff]
        if a.admin:
            d.update({'mots_interdits': gr.mots_interdits or ''})
    return d


def demande_en_attente(gid, uid):
    from groupes_models import GrpDemande
    return GrpDemande.query.filter_by(groupe_id=gid, user_id=uid, statut='en_attente').first() is not None


def _compte_reactions(cible_type, ids, uid):
    """{id: {'counts': {type: n}, 'total': n, 'mon': type|None}}"""
    sortie = {i: {'counts': {}, 'total': 0, 'mon': None} for i in ids}
    if not ids:
        return sortie
    for cid, typ, n in (db.session.query(GrpReaction.cible_id, GrpReaction.type, func.count())
                        .filter(GrpReaction.cible_type == cible_type, GrpReaction.cible_id.in_(ids))
                        .group_by(GrpReaction.cible_id, GrpReaction.type).all()):
        sortie[cid]['counts'][typ] = n
        sortie[cid]['total'] += n
    for r in GrpReaction.query.filter(GrpReaction.cible_type == cible_type, GrpReaction.cible_id.in_(ids), GrpReaction.user_id == uid):
        sortie[r.cible_id]['mon'] = r.type
    return sortie


def posts_json(posts):
    """Sérialise une liste de publications (éventuellement de plusieurs groupes) sans requêtes en boucle."""
    u = moi()
    if not posts:
        return []
    ids = [p.id for p in posts]
    groupes = {gr.id: gr for gr in Grp.query.filter(Grp.id.in_({p.groupe_id for p in posts})).all()}
    acces = {gid: Acces(gr, u) for gid, gr in groupes.items()}
    users = users_par_id({p.auteur_id for p in posts})
    roles = {(m.groupe_id, m.user_id): m.role for m in GrpMembre.query.filter(
        GrpMembre.groupe_id.in_(list(groupes)), GrpMembre.user_id.in_({p.auteur_id for p in posts}), GrpMembre.statut == 'actif')}
    reacts = _compte_reactions('post', ids, u.id)
    ncom = dict(db.session.query(GrpCom.post_id, func.count()).filter(GrpCom.post_id.in_(ids), GrpCom.supprime.is_(False)).group_by(GrpCom.post_id).all())
    sond_ids = [p.id for p in posts if p.type == 'sondage']
    options, votes, mes_votes = {}, {}, {}
    if sond_ids:
        for o in GrpOption.query.filter(GrpOption.post_id.in_(sond_ids)).order_by(GrpOption.ordre, GrpOption.id):
            options.setdefault(o.post_id, []).append(o)
        for oid, n in db.session.query(GrpVote.option_id, func.count()).filter(GrpVote.post_id.in_(sond_ids)).group_by(GrpVote.option_id):
            votes[oid] = n
        mes_votes = {v.post_id: v.option_id for v in GrpVote.query.filter(GrpVote.post_id.in_(sond_ids), GrpVote.user_id == u.id)}
    maintenant = datetime.utcnow()
    sortie = []
    for p in posts:
        gr, a = groupes[p.groupe_id], acces[p.groupe_id]
        cache = p.anonyme and not (a.staff or p.auteur_id == u.id)
        if cache:
            auteur = {'id': 0, 'nom': 'Membre anonyme', 'avatar': url_upload('default_avatar.png'), 'profil': '#', 'role': None, 'anonyme': True}
        else:
            auteur = user_min(users.get(p.auteur_id), roles.get((p.groupe_id, p.auteur_id)))
            auteur['anonyme'] = bool(p.anonyme)
        d = {'id': p.id, 'groupe': {'id': gr.id, 'nom': gr.nom, 'avatar': url_upload(gr.avatar, 'default_groupe.png')},
             'auteur': auteur, 'contenu': p.contenu, 'type': p.type, 'statut': p.statut, 'epingle': p.epingle,
             'commentaires_fermes': p.commentaires_fermes, 'medias': [url_upload(m) for m in p.medias],
             'cree_le': iso(p.cree_le), 'modifie_le': iso(p.modifie_le), 'reactions': reacts[p.id], 'nb_com': ncom.get(p.id, 0),
             'peut_modifier': p.auteur_id == u.id and p.statut in ('publie', 'en_attente') and not gr.archive,
             'peut_supprimer': p.auteur_id == u.id or a.staff, 'peut_moderer': a.staff,
             'peut_commenter': a.actif and not p.commentaires_fermes and not gr.archive and not a.muet()}
        if a.staff and p.motif_attente:
            d['motif_attente'] = p.motif_attente
        if p.type == 'sondage':
            opts = options.get(p.id, [])
            total = sum(votes.get(o.id, 0) for o in opts)
            d['sondage'] = {'options': [{'id': o.id, 'texte': o.texte, 'votes': votes.get(o.id, 0)} for o in opts], 'total': total,
                            'mon_vote': mes_votes.get(p.id), 'ferme': bool(p.sondage_fin and p.sondage_fin < maintenant), 'fin': iso(p.sondage_fin)}
        sortie.append(d)
    return sortie


def appliquer_reaction(gr, cible_type, cible_id, typ):
    """Pose / change / retire la réaction de l'utilisateur ; renvoie les compteurs à jour."""
    u = moi()
    r = GrpReaction.query.filter_by(cible_type=cible_type, cible_id=cible_id, user_id=u.id).first()
    if typ is None or (r and r.type == typ):
        if r:
            db.session.delete(r)
    else:
        if typ not in REACTIONS:
            raise Erreur('Réaction inconnue.')
        if r:
            r.type = typ
        else:
            db.session.add(GrpReaction(groupe_id=gr.id, cible_type=cible_type, cible_id=cible_id, user_id=u.id, type=typ))
    db.session.commit()
    return _compte_reactions(cible_type, [cible_id], u.id)[cible_id]


def purger_posts(post_ids):
    """Supprime des publications ET tout ce qui en dépend (commentaires, réactions, sondage, signalements)."""
    from groupes_models import GrpSignalement
    if not post_ids:
        return
    com_ids = [c.id for c in GrpCom.query.filter(GrpCom.post_id.in_(post_ids)).all()]
    if com_ids:
        GrpReaction.query.filter(GrpReaction.cible_type == 'com', GrpReaction.cible_id.in_(com_ids)).delete(synchronize_session=False)
        GrpSignalement.query.filter(GrpSignalement.cible_type == 'com', GrpSignalement.cible_id.in_(com_ids)).delete(synchronize_session=False)
    GrpReaction.query.filter(GrpReaction.cible_type == 'post', GrpReaction.cible_id.in_(post_ids)).delete(synchronize_session=False)
    GrpSignalement.query.filter(GrpSignalement.cible_type == 'post', GrpSignalement.cible_id.in_(post_ids)).delete(synchronize_session=False)
    GrpVote.query.filter(GrpVote.post_id.in_(post_ids)).delete(synchronize_session=False)
    GrpOption.query.filter(GrpOption.post_id.in_(post_ids)).delete(synchronize_session=False)
    GrpCom.query.filter(GrpCom.post_id.in_(post_ids)).delete(synchronize_session=False)
    GrpPost.query.filter(GrpPost.id.in_(post_ids)).delete(synchronize_session=False)


def lire_json():
    return request.get_json(silent=True) or {}
