"""
marketplace_detail.py — Page « détail d'une annonce » du Marketplace Tsapi (style fiche Facebook, design Tsapi).

FICHIER 100 % ADDITIF : il ne modifie aucune de tes routes ni aucun de tes modèles.
Il ajoute :
  * 4 petites tables NEUVES (créées automatiquement par db.create_all) :
      AnnonceAlerte, AnnonceMasquee, AnnonceOffre, AnnonceSignalementDirect
  * le blueprint « marketplace_detail » avec la page et ses routes JSON.
Il réutilise tes éléments existants : Annonce, AnnonceImage, User, Abonnement (suivre le vendeur),
MarketplaceFavori + /marketplace/api/annonce/<id>/favori (favoris), Group / GroupMembers / GroupJoinRequest
(groupes), BlockedUser, escrow_service.conversation_pour / poster_message (messagerie vendeur).
"""
import re
import unicodedata
from collections import Counter
from datetime import datetime

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import and_, func, or_

from extensions import db
from models import (Abonnement, Annonce, BlockedUser, Group, GroupJoinRequest, GroupMembers,
                    MarketplaceFavori, Notification, User)

marketplace_detail_bp = Blueprint('marketplace_detail', __name__)

MOTIFS = ('fraude', 'article_interdit', 'annonce_trompeuse', 'doublon', 'mauvaise_categorie', 'autre')


# =============================================================================
# Nouvelles tables (rien à migrer : tables neuves)
# =============================================================================
class AnnonceAlerte(db.Model):
    """L'utilisateur veut être prévenu des changements (prix, vendu) d'une annonce."""
    __tablename__ = 'annonce_alerte'
    __table_args__ = (db.UniqueConstraint('user_id', 'annonce_id', name='uq_annonce_alerte'),)
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    annonce_id = db.Column(db.Integer, db.ForeignKey('annonces.id'), nullable=False, index=True)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)


class AnnonceMasquee(db.Model):
    """« Masquer l'annonce » : l'utilisateur ne veut plus la voir."""
    __tablename__ = 'annonce_masquee'
    __table_args__ = (db.UniqueConstraint('user_id', 'annonce_id', name='uq_annonce_masquee'),)
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    annonce_id = db.Column(db.Integer, db.ForeignKey('annonces.id'), nullable=False, index=True)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)


class AnnonceOffre(db.Model):
    __tablename__ = 'annonce_offre'
    id = db.Column(db.Integer, primary_key=True)
    annonce_id = db.Column(db.Integer, db.ForeignKey('annonces.id'), nullable=False, index=True)
    acheteur_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    montant = db.Column(db.Integer, nullable=False)
    message = db.Column(db.String(300))
    statut = db.Column(db.String(20), default='envoyee')
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)


class AnnonceSignalementDirect(db.Model):
    __tablename__ = 'annonce_signalement_direct'
    id = db.Column(db.Integer, primary_key=True)
    auteur_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    annonce_id = db.Column(db.Integer, db.ForeignKey('annonces.id'), nullable=False, index=True)
    motif = db.Column(db.String(40), nullable=False)
    description = db.Column(db.String(500))
    statut = db.Column(db.String(20), default='ouvert')
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)


# =============================================================================
# Aides
# =============================================================================
def _moi():
    uid = session.get('user_id')
    if not uid:                                   # repli : connexion Flask-Login sans session['user_id']
        try:
            from flask_login import current_user
            if current_user.is_authenticated:
                uid = current_user.id
        except Exception:
            pass
    return db.session.get(User, int(uid)) if uid else None


def _json(ok=True, status=200, **d):
    d['success'] = ok
    return jsonify(d), status


def _connecte(f):
    from functools import wraps

    @wraps(f)
    def w(*a, **k):
        if _moi() is None:
            return _json(False, 401, message='Connexion requise.')
        return f(*a, **k)
    return w


def _upload(nom, defaut):
    return url_for('static', filename='uploads/' + (nom or defaut))


def _sans_accent(t):
    return ''.join(c for c in unicodedata.normalize('NFD', t or '') if unicodedata.category(c) != 'Mn')


def _fmt_prix(p):
    return '{:,}'.format(int(p or 0)).replace(',', '\u202f') + ' FCFA'


def _il_y_a(dt):
    if not dt:
        return ''
    s = int((datetime.utcnow() - dt).total_seconds())
    if s < 60:
        return "à l'instant"
    if s < 3600:
        return 'il y a %d min' % (s // 60)
    if s < 86400:
        return 'il y a %d h' % (s // 3600)
    j = s // 86400
    if j < 30:
        return 'il y a %d jour%s' % (j, 's' if j > 1 else '')
    return 'le ' + dt.strftime('%d/%m/%Y')


def _statut(a):
    return getattr(a, 'statut', None) or 'disponible'


def _bloque(a_id, b_id):
    return BlockedUser.query.filter(or_(
        and_(BlockedUser.owner_id == a_id, BlockedUser.blocked_id == b_id),
        and_(BlockedUser.owner_id == b_id, BlockedUser.blocked_id == a_id))).first() is not None


def ids_annonces_masquees(user_id):
    """À utiliser dans main.marketplace() pour ne plus afficher les annonces masquées."""
    if not user_id:
        return []
    return [m.annonce_id for m in AnnonceMasquee.query.filter_by(user_id=user_id).all()]


def notifier_alertes(annonce, texte, acteur_id=None):
    """Prévient tous les utilisateurs qui ont activé l'alerte (cloche) sur cette annonce.
    À appeler APRÈS le commit d'un changement de prix / de statut. N'échoue jamais."""
    try:
        acteur = acteur_id or annonce.user_id
        lien = url_for('marketplace_detail.page', annonce_id=annonce.id)
        for al in AnnonceAlerte.query.filter_by(annonce_id=annonce.id).all():
            if al.user_id == acteur:
                continue
            db.session.add(Notification(
                recipient_id=al.user_id, actor_id=acteur, verb='marketplace_alerte', type='marketplace_alerte',
                target_type='annonce', target_id=annonce.id, message=texte, extra_data={'lien': lien}))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print('DEBUG: notifier_alertes impossible : %s' % e)


def _carte(a):
    return {'id': a.id, 'titre': a.titre, 'prix_txt': _fmt_prix(a.prix), 'lieu': a.localisation or '',
            'image': _upload(a.image, 'default_annonce.png'),
            'url': url_for('marketplace_detail.page', annonce_id=a.id),
            'statut': _statut(a)}


# -----------------------------------------------------------------------------
# Recherches similaires (intelligentes, selon la marchandise)
# -----------------------------------------------------------------------------
_STOP = set('le la les un une des de du d l et ou en au aux a à pour par sur sous avec sans dans version neuf occasion '
            'bon etat état tres très vend vente urgent prix cfa fcfa wifi the of for and'.split())

_PAR_CATEGORIE = {
    'electronique': ['téléphone', 'smartphone', 'ordinateur portable', 'écouteurs', 'chargeur', 'télévision'],
    'vehicules': ['voiture', 'moto', 'pièces auto', 'pneus', 'camion'],
    'immobilier': ['studio à louer', 'chambre', 'appartement', 'terrain', 'maison'],
    'mode': ['chaussures', 'robe', 'sac à main', 'montre', 'friperie'],
    'maison': ['canapé', 'lit', 'réfrigérateur', 'cuisinière', 'ventilateur'],
    'loisirs': ['ballon', 'guitare', 'console de jeux', 'vélo', 'livres'],
    'famille': ['poussette', 'jouets', 'vêtements enfant', 'lit bébé'],
}


def suggestions_similaires(a, limite=8):
    """Ex. « iPhone 11 version wifi » -> iphone 12, iphone 13, iphone 10, iphone, ..."""
    titre = (a.titre or '').strip()
    out = []

    # 1) numéro de modèle voisin : « iPhone 11 » -> iPhone 12 / 13 / 10 (le « 11version » collé est géré)
    m = re.search(r'([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\-]*)\s*(\d{1,4})(?!\d)', titre)
    if m:
        marque, n = m.group(1), int(m.group(2))
        if 0 < n < 2000:
            for k in (n + 1, n + 2, n - 1, n + 3):
                if k > 0:
                    out.append('%s %d' % (marque.lower(), k))
            out.append('%s %d pro' % (marque.lower(), n))
            out.append(marque.lower())

    # 2) mots-clés significatifs du titre
    mots = [w for w in re.findall(r"[A-Za-zÀ-ÿ0-9]+", titre.lower()) if w not in _STOP and len(w) > 2]
    out.extend(mots[:3])
    if len(mots) >= 2:
        out.append(' '.join(mots[:2]))

    # 3) sujets populaires de la même catégorie, d'après les annonces réellement publiées
    freq = Counter()
    for (t,) in db.session.query(Annonce.titre).filter(Annonce.categorie == a.categorie, Annonce.id != a.id).limit(200):
        for w in re.findall(r"[A-Za-zÀ-ÿ0-9]+", (t or '').lower()):
            if w not in _STOP and len(w) > 2 and not w.isdigit():
                freq[w] += 1
    out.extend([w for w, _ in freq.most_common(4)])

    # 4) filet de sécurité par catégorie
    out.extend(_PAR_CATEGORIE.get(_sans_accent((a.categorie or '')).lower(), []))

    vus, res = set(), []
    for s in out:
        cle = _sans_accent(s).lower().strip()
        if cle and cle not in vus and cle != _sans_accent(titre).lower():
            vus.add(cle)
            res.append(s.strip())
    return res[:limite]


def _rechercher(q, exclure_id=None, limite=24, moi_id=None):
    jetons = [t for t in re.findall(r"[A-Za-zÀ-ÿ0-9]+", (q or '').lower()) if t]
    if not jetons:
        return []
    req = Annonce.query
    for t in jetons[:6]:
        variantes = {t, _sans_accent(t)}
        conds = []
        for v in variantes:
            motif = '%' + v + '%'
            conds += [func.lower(Annonce.titre).like(motif), func.lower(Annonce.description).like(motif),
                      func.lower(Annonce.categorie).like(motif)]
        req = req.filter(or_(*conds))
    if exclure_id:
        req = req.filter(Annonce.id != exclure_id)
    cachees = ids_annonces_masquees(moi_id)
    if cachees:
        req = req.filter(~Annonce.id.in_(cachees))
    return req.order_by(Annonce.date_creation.desc()).limit(limite).all()


# -----------------------------------------------------------------------------
# Groupes d'achat et de vente associés
# -----------------------------------------------------------------------------
_MOTS_COMMERCE = ('vente', 'achat', 'vendre', 'acheter', 'market', 'marche', 'marché', 'boutique', 'occasion',
                  'friperie', 'shop', 'commerce', 'buy', 'sell', 'business')


def groupes_associes(a, moi, limite=6):
    cles = set(w for w in re.findall(r"[A-Za-zÀ-ÿ0-9]+", ((a.titre or '') + ' ' + (a.categorie or '')).lower())
               if w not in _STOP and len(w) > 2)
    cles |= {_sans_accent(c) for c in cles}
    loc = (a.localisation or '').lower()
    candidats = []
    for g in Group.query.order_by(Group.date_creation.desc()).limit(300).all():
        texte = _sans_accent(((g.name or '') + ' ' + (g.description or '')).lower())
        score = 0
        score += 3 * sum(1 for c in cles if c and c in texte)
        score += 2 * sum(1 for c in _MOTS_COMMERCE if _sans_accent(c) in texte)
        if loc and _sans_accent(loc.split(',')[0].strip()) in texte:
            score += 2
        if score:
            candidats.append((score, g))
    if len(candidats) < limite:                       # complète avec les groupes les plus peuplés
        deja = {g.id for _, g in candidats}
        for g in Group.query.filter_by(is_private=False).limit(100).all():
            if g.id not in deja:
                candidats.append((0, g))
    candidats.sort(key=lambda x: (x[0], len(x[1].members)), reverse=True)

    res = []
    for _, g in candidats[:limite]:
        membre = en_attente = False
        if moi:
            membre = GroupMembers.query.filter_by(group_id=g.id, user_id=moi.id).first() is not None
            en_attente = GroupJoinRequest.query.filter_by(group_id=g.id, user_id=moi.id, statut='en_attente').first() is not None
        res.append({'id': g.id, 'nom': g.name, 'membres': len(g.members), 'prive': bool(g.is_private),
                    'cover': url_for('static', filename='uploads/' + g.cover_url) if g.cover_url else '',
                    'membre': membre, 'en_attente': en_attente,
                    'url': url_for('groupe.groupe_accueil', group_id=g.id) if 'groupe.groupe_accueil' in _endpoints() else '#'})
    return res


def _endpoints():
    from flask import current_app
    return {r.endpoint for r in current_app.url_map.iter_rules()}


# =============================================================================
# Page
# =============================================================================
@marketplace_detail_bp.route('/marketplace/annonce/<int:annonce_id>')
def page(annonce_id):
    a = db.session.get(Annonce, annonce_id)
    if not a:
        return redirect(url_for('main.marketplace'))
    moi = _moi()
    vendeur = db.session.get(User, a.user_id)
    est_proprio = bool(moi and moi.id == a.user_id)
    info = getattr(a, 'info', None)

    photos = [_upload(p.filename, 'default_annonce.png') for p in a.photos] or [_upload(None, 'default_annonce.png')]
    deja_favori = bool(moi and MarketplaceFavori.query.filter_by(user_id=moi.id, annonce_id=a.id).first())
    alerte_active = bool(moi and AnnonceAlerte.query.filter_by(user_id=moi.id, annonce_id=a.id).first())
    suit_vendeur = bool(moi and not est_proprio and Abonnement.query.filter_by(follower_id=moi.id, suivi_id=a.user_id).first())
    nb_annonces_vendeur = Annonce.query.filter_by(user_id=a.user_id).count()
    autres = [_carte(x) for x in Annonce.query.filter(Annonce.user_id == a.user_id, Annonce.id != a.id)
              .order_by(Annonce.date_creation.desc()).limit(8).all()]

    return render_template(
        'annonce_detail.html', a=a, photos=photos, vendeur=vendeur, est_proprio=est_proprio,
        vendeur_avatar=_upload(getattr(vendeur, 'avatar', None), 'default_avatar.png'),
        vendeur_nom=(vendeur.nom_complet or vendeur.username) if vendeur else 'Utilisateur',
        vendeur_verifie=bool(getattr(vendeur, 'is_verify', False)),
        vendeur_depuis=(getattr(vendeur, 'created_at', None) or getattr(vendeur, 'date_creation', None)),
        prix_txt=_fmt_prix(a.prix), publie=_il_y_a(a.date_creation), statut=_statut(a),
        nb_vues=(getattr(info, 'nb_vues', 0) or 0), deja_favori=deja_favori, alerte_active=alerte_active,
        suit_vendeur=suit_vendeur, nb_annonces_vendeur=nb_annonces_vendeur, autres=autres,
        similaires=suggestions_similaires(a), groupes=groupes_associes(a, moi), connecte=moi is not None,
        masquee=bool(moi and AnnonceMasquee.query.filter_by(user_id=moi.id, annonce_id=a.id).first()))


# =============================================================================
# API JSON
# =============================================================================
@marketplace_detail_bp.route('/marketplace/api/recherche')
def api_recherche():
    """Recherche automatique dans les annonces publiées (clic sur une « recherche similaire »)."""
    q = (request.args.get('q') or '').strip()[:80]
    exclure = request.args.get('exclure', type=int)
    moi = _moi()
    res = _rechercher(q, exclure_id=exclure, moi_id=moi.id if moi else None)
    return _json(q=q, total=len(res), annonces=[_carte(x) for x in res],
                 url_liste=url_for('main.marketplace'))


@marketplace_detail_bp.route('/marketplace/api/annonce/<int:annonce_id>/alerte', methods=['POST'])
@_connecte
def api_alerte(annonce_id):
    moi = _moi()
    a = db.session.get(Annonce, annonce_id)
    if not a:
        return _json(False, 404, message='Annonce introuvable.')
    if a.user_id == moi.id:
        return _json(False, 400, message='Vous ne pouvez pas créer une alerte sur votre propre annonce.')
    ex = AnnonceAlerte.query.filter_by(user_id=moi.id, annonce_id=annonce_id).first()
    if ex:
        db.session.delete(ex)
        actif = False
    else:
        db.session.add(AnnonceAlerte(user_id=moi.id, annonce_id=annonce_id))
        actif = True
    db.session.commit()
    return _json(actif=actif, message='Alerte activée.' if actif else 'Alerte retirée.')


@marketplace_detail_bp.route('/marketplace/api/annonce/<int:annonce_id>/masquer', methods=['POST'])
@_connecte
def api_masquer(annonce_id):
    moi = _moi()
    if not db.session.get(Annonce, annonce_id):
        return _json(False, 404, message='Annonce introuvable.')
    voulu = (request.get_json(silent=True) or {}).get('etat', True)
    ex = AnnonceMasquee.query.filter_by(user_id=moi.id, annonce_id=annonce_id).first()
    if voulu and not ex:
        db.session.add(AnnonceMasquee(user_id=moi.id, annonce_id=annonce_id))
    elif not voulu and ex:
        db.session.delete(ex)
    db.session.commit()
    return _json(masquee=bool(voulu), retour=url_for('main.marketplace'))


def _ouvrir_conversation(moi, a):
    import escrow_service as escrow
    return escrow.conversation_pour(a, moi.id)


def _verifs_contact(moi, a):
    if not a:
        return 'Annonce introuvable.', 404
    if a.user_id == moi.id:
        return 'Vous ne pouvez pas vous écrire à vous-même.', 400
    if _bloque(moi.id, a.user_id):
        return 'Vous ne pouvez plus échanger avec ce vendeur.', 403
    return None, 200


@marketplace_detail_bp.route('/marketplace/api/annonce/<int:annonce_id>/contacter', methods=['POST'])
@_connecte
def api_contacter(annonce_id):
    """Bloc « Contacter le vendeur » : crée (ou rouvre) la conversation et envoie le message."""
    import escrow_service as escrow
    moi = _moi()
    a = db.session.get(Annonce, annonce_id)
    err, code = _verifs_contact(moi, a)
    if err:
        return _json(False, code, message=err)
    texte = ((request.get_json(silent=True) or {}).get('message') or '').strip()[:2000]
    if not texte:
        return _json(False, 400, message='Écrivez un message.')
    try:
        conv = _ouvrir_conversation(moi, a)
        conv.masquee_acheteur = False
        escrow.poster_message(conv, moi.id, texte)
        db.session.commit()
    except Exception as e:                                     # ne jamais casser la page
        db.session.rollback()
        return _json(False, 500, message="Impossible d'envoyer le message : " + str(e))
    return _json(message='Message envoyé.', url=url_for('marketplace_pro.messages', conversation_id=conv.id))


@marketplace_detail_bp.route('/marketplace/api/annonce/<int:annonce_id>/offre', methods=['POST'])
@_connecte
def api_offre(annonce_id):
    import escrow_service as escrow
    moi = _moi()
    a = db.session.get(Annonce, annonce_id)
    err, code = _verifs_contact(moi, a)
    if err:
        return _json(False, code, message=err)
    if _statut(a) == 'vendu':
        return _json(False, 400, message='Cet article est déjà vendu.')
    d = request.get_json(silent=True) or {}
    try:
        montant = int(d.get('montant'))
    except (TypeError, ValueError):
        return _json(False, 400, message='Montant invalide.')
    if montant < 100 or montant > 1_000_000_000:
        return _json(False, 400, message='Montant invalide (minimum 100 FCFA).')
    note = (d.get('message') or '').strip()[:300]
    offre = AnnonceOffre(annonce_id=a.id, acheteur_id=moi.id, montant=montant, message=note)
    db.session.add(offre)
    url = None
    try:
        conv = _ouvrir_conversation(moi, a)
        conv.masquee_acheteur = False
        txt = '💰 Offre : %s pour « %s »' % (_fmt_prix(montant), a.titre) + ((' — ' + note) if note else '')
        escrow.poster_message(conv, moi.id, txt)
        url = url_for('marketplace_pro.messages', conversation_id=conv.id)
    except Exception:
        pass                                                   # l'offre reste enregistrée même si le chat échoue
    db.session.commit()
    return _json(message='Offre envoyée au vendeur.', url=url)


@marketplace_detail_bp.route('/marketplace/api/annonce/<int:annonce_id>/signaler', methods=['POST'])
@_connecte
def api_signaler_annonce(annonce_id):
    moi = _moi()
    if not db.session.get(Annonce, annonce_id):
        return _json(False, 404, message='Annonce introuvable.')
    d = request.get_json(silent=True) or {}
    if d.get('motif') not in MOTIFS:
        return _json(False, 400, message='Motif invalide.')
    if not AnnonceSignalementDirect.query.filter_by(auteur_id=moi.id, annonce_id=annonce_id, motif=d['motif'], statut='ouvert').first():
        db.session.add(AnnonceSignalementDirect(auteur_id=moi.id, annonce_id=annonce_id, motif=d['motif'],
                                                description=(d.get('description') or '').strip()[:500]))
        db.session.commit()
    return _json(message='Merci, votre signalement a été transmis à notre équipe.')


@marketplace_detail_bp.route('/marketplace/api/vendeur/<int:uid>/suivre', methods=['POST'])
@_connecte
def api_suivre_vendeur(uid):
    moi = _moi()
    if uid == moi.id or not db.session.get(User, uid):
        return _json(False, 400, message='Action impossible.')
    ex = Abonnement.query.filter_by(follower_id=moi.id, suivi_id=uid).first()
    if ex:
        db.session.delete(ex)
        suit = False
    else:
        db.session.add(Abonnement(follower_id=moi.id, suivi_id=uid))
        suit = True
    db.session.commit()
    return _json(suit=suit)


@marketplace_detail_bp.route('/marketplace/api/groupes/<int:gid>/rejoindre', methods=['POST'])
@_connecte
def api_rejoindre_groupe(gid):
    """Rejoint un groupe public, ou envoie une demande pour un groupe privé."""
    moi = _moi()
    g = db.session.get(Group, gid)
    if not g:
        return _json(False, 404, message='Groupe introuvable.')
    if GroupMembers.query.filter_by(group_id=gid, user_id=moi.id).first():
        return _json(message='Vous êtes déjà membre.', etat='membre')
    if g.is_private:
        if not GroupJoinRequest.query.filter_by(group_id=gid, user_id=moi.id, statut='en_attente').first():
            db.session.add(GroupJoinRequest(group_id=gid, user_id=moi.id, statut='en_attente'))
            db.session.commit()
        return _json(message='Demande envoyée, en attente de validation.', etat='en_attente')
    db.session.add(GroupMembers(group_id=gid, user_id=moi.id, role='membre'))
    db.session.commit()
    return _json(message='Bienvenue dans le groupe !', etat='membre')
