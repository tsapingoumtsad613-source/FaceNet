"""
pages_facenet.py : Pages FaceNet (façon Facebook), module 100 % additif.

• Aucune table existante n'est modifiée : 4 nouvelles tables, créées automatiquement
  (même méthode que vos autres ajouts : __table__.create(checkfirst=True)).
• Une Page publie via une Publication ordinaire (user_id = propriétaire) reliée à la
  Page par la table PagePubFN : le fil, le profil, la suppression, les likes et les
  commentaires existants continuent donc de fonctionner sans changement.
• Tout ce qui touche au fil est protégé par try/except : en cas de problème, le fil
  s'affiche comme avant.
"""
import os
import re
import uuid
import unicodedata
from datetime import datetime

from flask import (Blueprint, render_template, request, jsonify, session, redirect,
                   url_for, abort, current_app, g)
from flask_login import current_user
from sqlalchemy import or_

from extensions import db
from models import User, Publication, DemandeAmitie

pages_bp = Blueprint('pages', __name__, url_prefix='/pages')

EXT_IMAGES = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
EXT_MEDIAS = EXT_IMAGES | {'mp4', 'webm'}

CATEGORIES = [
    'Blog personnel', 'Création digitale', 'Musique/groupe', 'Artiste',
    'Personnalité publique', 'Art', 'Produit/service', 'Santé/beauté',
    'Shopping et vente au détail', 'Vêtements (Marque)', 'Restaurant', 'Éducation',
    'Média/actualités', 'Sport', 'Technologie', 'Organisation à but non lucratif',
    'Communauté', 'Application', 'Divertissement', 'Voyage et tourisme',
]

OBJECTIFS = {
    'creator': [('monetiser', 'Monétiser', 'Créer et monétiser du contenu original'),
                ('communaute', 'Créer une communauté', 'Créer du lien et échanger avec les followers et les fans'),
                ('affilie', 'Ventes affiliées', 'Promouvoir des produits tiers ou mes produits')],
    'entreprise': [('pub', 'Diffuser des publicités', 'Toucher de nouveaux clients et générer des conversions'),
                   ('clients', 'Entrer en contact avec les clients', 'Fidéliser et gagner des followers'),
                   ('offres', 'Promouvoir les offres', 'Présenter des produits et services')],
}


# ───────────────────────── Modèles ─────────────────────────
class PageFN(db.Model):
    __tablename__ = 'page_fn'
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    nom = db.Column(db.String(120), nullable=False)
    slug = db.Column(db.String(140), unique=True, nullable=False, index=True)
    categorie = db.Column(db.String(120), nullable=True)
    type_page = db.Column(db.String(20), default='entreprise', nullable=False)
    objectifs = db.Column(db.String(200), nullable=True)      # "pub,clients"
    bio = db.Column(db.Text, nullable=True)
    site_web = db.Column(db.String(255), nullable=True)
    email = db.Column(db.String(150), nullable=True)
    telephone = db.Column(db.String(40), nullable=True)
    adresse = db.Column(db.String(200), nullable=True)
    ville = db.Column(db.String(100), nullable=True)
    code_postal = db.Column(db.String(20), nullable=True)
    avatar = db.Column(db.String(200), nullable=True)
    couverture = db.Column(db.String(200), nullable=True)
    emails_promo = db.Column(db.Boolean, default=True, nullable=False)
    notif_profil = db.Column(db.Boolean, default=True, nullable=False)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)


class PageSuiviFN(db.Model):
    __tablename__ = 'page_suivi_fn'
    __table_args__ = (db.UniqueConstraint('page_id', 'user_id', name='uq_page_suivi_fn'),)
    id = db.Column(db.Integer, primary_key=True)
    page_id = db.Column(db.Integer, db.ForeignKey('page_fn.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)


class PagePubFN(db.Model):
    """Relie une Publication existante à la Page qui l'a publiée."""
    __tablename__ = 'page_pub_fn'
    publication_id = db.Column(db.Integer, primary_key=True)
    page_id = db.Column(db.Integer, nullable=False, index=True)


class PageInvitationFN(db.Model):
    __tablename__ = 'page_invitation_fn'
    __table_args__ = (db.UniqueConstraint('page_id', 'invite_id', name='uq_page_invitation_fn'),)
    id = db.Column(db.Integer, primary_key=True)
    page_id = db.Column(db.Integer, nullable=False, index=True)
    invite_id = db.Column(db.Integer, nullable=False, index=True)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)


_TABLES_OK = False


def _assurer_tables():
    global _TABLES_OK
    if _TABLES_OK:
        return True
    try:
        for m in (PageFN, PageSuiviFN, PagePubFN, PageInvitationFN):
            m.__table__.create(bind=db.engine, checkfirst=True)
        _TABLES_OK = True
    except Exception as e:
        db.session.rollback()
        print(f"DEBUG pages_facenet : création des tables impossible : {e}")
    return _TABLES_OK


# ───────────────────────── Utilitaires ─────────────────────────
def _uid():
    try:
        if current_user.is_authenticated:
            return current_user.id
    except Exception:
        pass
    return session.get('user_id')


def _exiger_connexion():
    uid = _uid()
    if not uid:
        abort(401)
    return uid


def _slug_unique(nom):
    base = unicodedata.normalize('NFKD', nom).encode('ascii', 'ignore').decode()
    base = re.sub(r'[^a-zA-Z0-9]+', '-', base).strip('-').lower() or 'page'
    slug, n = base, 1
    while PageFN.query.filter_by(slug=slug).first():
        n += 1
        slug = f"{base}-{n}"
    return slug


def _sauver_fichier(fichier, extensions):
    """Enregistre dans static/uploads (comme avatars et publications). Retourne le nom ou None."""
    if not fichier or not fichier.filename or '.' not in fichier.filename:
        return None
    ext = fichier.filename.rsplit('.', 1)[1].lower()
    if ext not in extensions:
        return None
    dossier = current_app.config.get('UPLOAD_FOLDER') or os.path.join(current_app.root_path, 'static', 'uploads')
    os.makedirs(dossier, exist_ok=True)
    nom = f"page_{uuid.uuid4().hex}.{ext}"
    fichier.save(os.path.join(dossier, nom))
    return nom


def _amis_de(user_id):
    demandes = DemandeAmitie.query.filter(
        DemandeAmitie.statut == 'acceptee',
        or_(DemandeAmitie.emetteur_id == user_id, DemandeAmitie.recepteur_id == user_id)).all()
    ids = {d.recepteur_id if d.emetteur_id == user_id else d.emetteur_id for d in demandes}
    return User.query.filter(User.id.in_(ids)).order_by(User.nom_complet.asc()).all() if ids else []


def _page_ou_404(ident):
    page = PageFN.query.filter_by(slug=ident).first()
    if page is None and str(ident).isdigit():
        page = db.session.get(PageFN, int(ident))
    if page is None:
        abort(404)
    return page


def _nb_followers(page_id):
    return PageSuiviFN.query.filter_by(page_id=page_id).count()


# ───────────────────────── Routes ─────────────────────────
@pages_bp.before_request
def _avant():
    _assurer_tables()


@pages_bp.route('/creer', methods=['GET'])
def creer():
    uid = _uid()
    if not uid:
        return redirect(url_for('main.login'))
    amis = _amis_de(uid)
    return render_template('page_creer.html', categories=CATEGORIES, objectifs=OBJECTIFS,
                           amis=amis, user=db.session.get(User, uid))


@pages_bp.route('/creer', methods=['POST'])
def creer_post():
    uid = _exiger_connexion()
    f = request.form
    nom = (f.get('nom') or '').strip()[:120]
    if len(nom) < 2:
        return jsonify(success=False, message="Le nom de la Page est obligatoire."), 400
    if PageFN.query.filter(db.func.lower(PageFN.nom) == nom.lower()).first():
        return jsonify(success=False, message="Une Page porte déjà ce nom. Choisissez-en un autre."), 400
    type_page = f.get('type_page') if f.get('type_page') in ('entreprise', 'creator') else 'entreprise'
    objectifs = ','.join(o for o in (f.get('objectifs') or '').split(',')
                         if o in {k for lst in OBJECTIFS.values() for k, _, _ in lst})
    try:
        page = PageFN(
            owner_id=uid, nom=nom, slug=_slug_unique(nom),
            categorie=(f.get('categorie') or '').strip()[:120] or None,
            type_page=type_page, objectifs=objectifs or None,
            bio=(f.get('bio') or '').strip() or None,
            site_web=(f.get('site_web') or '').strip()[:255] or None,
            email=(f.get('email') or '').strip()[:150] or None,
            telephone=(f.get('telephone') or '').strip()[:40] or None,
            adresse=(f.get('adresse') or '').strip()[:200] or None,
            ville=(f.get('ville') or '').strip()[:100] or None,
            code_postal=(f.get('code_postal') or '').strip()[:20] or None,
            avatar=_sauver_fichier(request.files.get('avatar'), EXT_IMAGES),
            couverture=_sauver_fichier(request.files.get('couverture'), EXT_IMAGES),
            emails_promo=f.get('emails_promo', '1') == '1',
            notif_profil=f.get('notif_profil', '1') == '1',
        )
        db.session.add(page)
        db.session.flush()
        amis_valides = {u.id for u in _amis_de(uid)}
        for raw in (f.get('amis') or '').split(','):
            if raw.strip().isdigit() and int(raw) in amis_valides:
                db.session.add(PageInvitationFN(page_id=page.id, invite_id=int(raw)))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Création de Page impossible : {e}")
        return jsonify(success=False, message="Impossible de créer la Page pour le moment."), 500
    return jsonify(success=True, url=f"/pages/{page.slug}")


@pages_bp.route('/mes-pages')
def mes_pages():
    uid = _uid()
    if not uid:
        return redirect(url_for('main.login'))
    pages = PageFN.query.filter_by(owner_id=uid).order_by(PageFN.id.desc()).all()
    return jsonify(pages=[{'id': p.id, 'nom': p.nom, 'url': f"/pages/{p.slug}", 'avatar': p.avatar}
                          for p in pages])


@pages_bp.route('/<ident>')
def profil(ident):
    # Nouveau design des Pages (module additif pages_fn.py). S'il est absent, l'ancien affichage reste.
    try:
        from pages_fn import profil_nouveau
    except ImportError as e:
        print(f"DEBUG pages_fn indisponible : {e}")
        profil_nouveau = None
    if profil_nouveau is not None:
        return profil_nouveau(ident)
    page = _page_ou_404(ident)
    uid = _uid()
    est_admin = bool(uid and uid == page.owner_id)
    ids = [r.publication_id for r in PagePubFN.query.filter_by(page_id=page.id).all()]
    publications = (Publication.query.filter(Publication.id.in_(ids), Publication.is_removed.is_(False))
                    .order_by(Publication.id.desc()).limit(100).all()) if ids else []
    suit = bool(uid and PageSuiviFN.query.filter_by(page_id=page.id, user_id=uid).first())
    return render_template('page_profil.html', page=page, publications=publications,
                           est_admin=est_admin, suit=suit, nb_followers=_nb_followers(page.id),
                           proprietaire=db.session.get(User, page.owner_id),
                           user=db.session.get(User, uid) if uid else None)


@pages_bp.route('/<int:page_id>/suivre', methods=['POST'])
def suivre(page_id):
    uid = _exiger_connexion()
    page = db.session.get(PageFN, page_id) or abort(404)
    ligne = PageSuiviFN.query.filter_by(page_id=page.id, user_id=uid).first()
    try:
        if ligne:
            db.session.delete(ligne)
            suit = False
        else:
            db.session.add(PageSuiviFN(page_id=page.id, user_id=uid))
            suit = True
        db.session.commit()
    except Exception:
        db.session.rollback()
        return jsonify(success=False), 500
    return jsonify(success=True, suit=suit, followers=_nb_followers(page.id))


@pages_bp.route('/<int:page_id>/publier', methods=['POST'])
def publier(page_id):
    uid = _exiger_connexion()
    page = db.session.get(PageFN, page_id) or abort(404)
    if page.owner_id != uid:
        abort(403)
    contenu = (request.form.get('contenu') or '').strip()
    media = _sauver_fichier(request.files.get('media'), EXT_MEDIAS)
    if not contenu and not media:
        return jsonify(success=False, message="Écrivez quelque chose ou ajoutez un média."), 400
    try:
        pub = Publication(contenu=contenu or ' ', user_id=uid, media_url=media, confidentialite='public')
        db.session.add(pub)
        db.session.flush()
        db.session.add(PagePubFN(publication_id=pub.id, page_id=page.id))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Publication de Page impossible : {e}")
        return jsonify(success=False, message="Publication impossible."), 500
    return jsonify(success=True, pub_id=pub.id)


@pages_bp.route('/<int:page_id>/photo', methods=['POST'])
def changer_photo(page_id):
    uid = _exiger_connexion()
    page = db.session.get(PageFN, page_id) or abort(404)
    if page.owner_id != uid:
        abort(403)
    quoi = request.form.get('type')
    nom = _sauver_fichier(request.files.get('fichier'), EXT_IMAGES)
    if quoi not in ('avatar', 'couverture') or not nom:
        return jsonify(success=False, message="Image invalide."), 400
    setattr(page, quoi, nom)
    db.session.commit()
    return jsonify(success=True, fichier=nom)


@pages_bp.route('/<int:page_id>/modifier', methods=['POST'])
def modifier(page_id):
    uid = _exiger_connexion()
    page = db.session.get(PageFN, page_id) or abort(404)
    if page.owner_id != uid:
        abort(403)
    for champ, taille in (('bio', None), ('site_web', 255), ('email', 150), ('telephone', 40),
                          ('adresse', 200), ('ville', 100), ('code_postal', 20), ('categorie', 120)):
        if champ in request.form:
            val = request.form.get(champ, '').strip()
            setattr(page, champ, (val[:taille] if taille else val) or None)
    db.session.commit()
    return jsonify(success=True)


# ───────────────────────── Intégration au fil ─────────────────────────
@pages_bp.app_template_global('page_de_pub')
def page_de_pub(pub):
    """Utilisée par _feed_card_macro.html : retourne {'nom','url','avatar'} si la publication
    a été publiée par une Page, sinon None. Ne lève JAMAIS d'exception (le fil ne doit pas casser)."""
    try:
        if not _assurer_tables():
            return None
        cache = getattr(g, '_pages_fn_cache', None)
        if cache is None:
            lignes = PagePubFN.query.order_by(PagePubFN.publication_id.desc()).limit(500).all()
            pages = {p.id: p for p in PageFN.query.filter(
                PageFN.id.in_({l.page_id for l in lignes})).all()} if lignes else {}
            cache = g._pages_fn_cache = {
                'pubs': {l.publication_id: l.page_id for l in lignes},
                'pages': pages, 'plein': len(lignes) >= 500}
        pid = cache['pubs'].get(pub.id)
        if pid is None and cache['plein']:
            ligne = db.session.get(PagePubFN, pub.id)
            pid = ligne.page_id if ligne else None
        if pid is None:
            return None
        page = cache['pages'].get(pid) or db.session.get(PageFN, pid)
        if page is None:
            return None
        return {'nom': page.nom, 'url': f"/pages/{page.slug}",
                'avatar': page.avatar or 'default_avatar.png'}
    except Exception:
        db.session.rollback()
        return None


# ───────────────────────── Bande « Reels » du fil ─────────────────────────
def _compact(n):
    """1200 -> '1,2 K' ; 4000000 -> '4 M' (même style que Facebook)."""
    n = int(n or 0)
    if n >= 1000000:
        v, u = n / 1000000.0, ' M'
    elif n >= 1000:
        v, u = n / 1000.0, ' K'
    else:
        return str(n)
    t = f"{v:.1f}".rstrip('0').rstrip('.').replace('.', ',')
    return t + u


@pages_bp.app_template_global('reels_pour_fil')
def reels_pour_fil(limite=6):
    """Reels récents (publics) pour la bande « Reels » du fil. Ne lève JAMAIS d'exception :
    en cas de problème, retourne [] et le fil s'affiche exactement comme avant."""
    try:
        from sqlalchemy import func
        from flask import url_for
        from models import Reel, PublicationVideoView
        candidats = Reel.query.order_by(Reel.created_at.desc()).limit(limite * 4).all()
        retenus = []
        for r in candidats:
            pub = getattr(r, 'publication', None)
            if pub is None or getattr(pub, 'is_removed', False):
                continue
            if (getattr(pub, 'confidentialite', None) or 'public') != 'public':
                continue
            if not r.fichier_video:
                continue
            retenus.append(r)
            if len(retenus) >= limite:
                break
        if not retenus:
            return []
        ids = [r.publication_id for r in retenus]
        try:
            vues = dict(db.session.query(PublicationVideoView.publication_id,
                                         func.count(PublicationVideoView.id))
                        .filter(PublicationVideoView.publication_id.in_(ids))
                        .group_by(PublicationVideoView.publication_id).all())
        except Exception:
            db.session.rollback()
            vues = {}
        return [{
            'id': r.id,
            'video': url_for('static', filename='uploads/reels/' + r.fichier_video),
            'vues': _compact(vues.get(r.publication_id, 0)),
            'auteur': (getattr(r.auteur, 'nom_complet', None) or getattr(r.auteur, 'username', '') or ''),
        } for r in retenus]
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        return []