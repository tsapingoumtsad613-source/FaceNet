"""
pages_fn.py : backend du NOUVEAU design des Pages FaceNet (module 100 % additif).

Il fournit les routes « fnpage_* » et les adresses « /page/... » que demandent
page_profil.html, _page_macros.html et _page_js.html.

• Aucune table existante n'est modifiée. Une seule nouvelle table est créée automatiquement
  (page_suivi_page_fn : « une Page suit une autre Page »), comme le fait pages_facenet.py.
• Les publications d'une Page restent des Publication ordinaires reliées par PagePubFN
  (exactement comme avant) : le fil, le profil, les likes et les commentaires existants
  continuent de fonctionner. J'aime et commentaires RÉUTILISENT les routes existantes
  (api_toggle_like et api_add_comment) : mêmes règles, mêmes notifications.
• La suppression d'une publication de Page est « douce » (is_removed = True), comme ailleurs.
• Branchement : routes.py appelle init_pages_fn(main_bp) juste après main_bp.register_blueprint(pages_bp).
"""
import functools
from datetime import datetime
from types import SimpleNamespace

from flask import (render_template, request, jsonify, session, redirect, url_for,
                   flash, abort, current_app)
from sqlalchemy import func, or_
from werkzeug.exceptions import HTTPException

from extensions import db
from models import User, Publication
from pages_facenet import (PageFN, PageSuiviFN, PagePubFN, PageInvitationFN, CATEGORIES,
                           EXT_IMAGES, EXT_MEDIAS, _assurer_tables, _uid, _sauver_fichier,
                           _page_ou_404)

EXT_VIDEOS = {'mp4', 'webm', 'mov', 'm4v'}


# ───────────────────────── Nouvelle table (seule addition à la base) ─────────────────────────
class PageSuiviPageFN(db.Model):
    """Une Page (suiveuse) suit une autre Page (suivie) : sert au « Fil d'actualité de la Page »."""
    __tablename__ = 'page_suivi_page_fn'
    __table_args__ = (db.UniqueConstraint('page_id', 'suivie_id', name='uq_page_suivi_page_fn'),)
    id = db.Column(db.Integer, primary_key=True)
    page_id = db.Column(db.Integer, nullable=False, index=True)
    suivie_id = db.Column(db.Integer, nullable=False, index=True)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)


_TABLES_FN_OK = False


def _tables():
    global _TABLES_FN_OK
    ok = _assurer_tables()
    if ok and not _TABLES_FN_OK:
        try:
            PageSuiviPageFN.__table__.create(bind=db.engine, checkfirst=True)
            _TABLES_FN_OK = True
        except Exception as e:
            db.session.rollback()
            print(f"DEBUG pages_fn : création de la table impossible : {e}")
    return ok


def _route(connexion=True):
    """Prépare les tables ; si la route exige une connexion, renvoie JSON 401 (appel AJAX/POST)
    ou redirige vers la connexion (page normale)."""
    def deco(f):
        @functools.wraps(f)
        def w(*a, **k):
            _tables()
            if connexion and not _uid():
                if request.method != 'GET' or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                    return jsonify(success=False, message='Connectez-vous pour continuer.'), 401
                return redirect(url_for('main.login'))
            return f(*a, **k)
        return w
    return deco


# ───────────────────────── Objets d'affichage ─────────────────────────
class PageVue:
    """Enveloppe une PageFN et ajoute ce que le design attend (sans toucher au modèle) :
    verifiee, nb_abonnes, nb_publications, owner. Tout le reste est celui de la Page."""

    def __init__(self, page, owner, nb_abonnes, nb_publications):
        self._p = page
        self.owner = owner
        self.nb_abonnes = nb_abonnes
        self.nb_publications = nb_publications
        # Même critère que le badge du profil : propriétaire abonné « Tsapi Verified ».
        self.verifiee = bool(owner and getattr(owner, 'badge_expire', None))

    def __getattr__(self, nom):
        if nom == '_p':
            raise AttributeError(nom)
        return getattr(self._p, nom)


class _Liste:
    """Liste affichable dont la longueur annoncée est le vrai total (|length du modèle)."""

    def __init__(self, elements, total):
        self._e = list(elements)
        self._t = int(total or 0)

    def __iter__(self):
        return iter(self._e)

    def __len__(self):
        return self._t


def _nb_pubs(page_id):
    try:
        return (db.session.query(func.count(Publication.id))
                .join(PagePubFN, PagePubFN.publication_id == Publication.id)
                .filter(PagePubFN.page_id == page_id,
                        or_(Publication.is_removed.is_(False), Publication.is_removed.is_(None)))
                .scalar()) or 0
    except Exception:
        db.session.rollback()
        return PagePubFN.query.filter_by(page_id=page_id).count()


def _vue_page(page, owner=None):
    owner = owner or db.session.get(User, page.owner_id)
    nb_ab = PageSuiviFN.query.filter_by(page_id=page.id).count()
    return PageVue(page, owner, nb_ab, _nb_pubs(page.id))


def _page_active(uid):
    pid = session.get('fnpage_active')
    if not pid or not uid:
        return None
    p = db.session.get(PageFN, pid)
    if p is None or p.owner_id != uid:
        session.pop('fnpage_active', None)
        return None
    return p


def _utilisateur(uid):
    return db.session.get(User, uid) if uid else None


def _charger_pubs(page_ids, limite):
    """Publications publiques (non supprimées) des Pages données, plus récentes d'abord.
    Retourne (liste de Publication, {publication_id: page_id})."""
    page_ids = list(page_ids)
    if not page_ids:
        return [], {}
    liens = (PagePubFN.query.filter(PagePubFN.page_id.in_(page_ids))
             .order_by(PagePubFN.publication_id.desc()).limit(limite * 2).all())
    par_pub = {l.publication_id: l.page_id for l in liens}
    if not par_pub:
        return [], {}
    pubs = (Publication.query.filter(Publication.id.in_(list(par_pub)))
            .order_by(Publication.id.desc()).all())
    pubs = [p for p in pubs
            if not getattr(p, 'is_removed', False)
            and (getattr(p, 'confidentialite', None) or 'public') == 'public'][:limite]
    return pubs, par_pub


def _vues_pubs(pubs, par_pub, pages_vue, uid):
    """Transforme des Publication en objets que la macro « carte » sait afficher.
    Retourne (liste, ensemble des ids aimés par l'utilisateur)."""
    from models import Like, Commentaire
    ids = [p.id for p in pubs]
    if not ids:
        return [], set()
    try:
        nb_likes = dict(db.session.query(Like.publication_id, func.count(Like.user_id))
                        .filter(Like.publication_id.in_(ids)).group_by(Like.publication_id).all())
        nb_coms = dict(db.session.query(Commentaire.publication_id, func.count(Commentaire.id))
                       .filter(Commentaire.publication_id.in_(ids)).group_by(Commentaire.publication_id).all())
        recents = (Commentaire.query.filter(Commentaire.publication_id.in_(ids))
                   .order_by(Commentaire.id.desc()).limit(600).all())
        mes_likes = ({l.publication_id for l in Like.query.filter(
            Like.user_id == uid, Like.publication_id.in_(ids)).all()} if uid else set())
    except Exception as e:
        db.session.rollback()
        print(f"DEBUG pages_fn : likes/commentaires indisponibles : {e}")
        nb_likes, nb_coms, recents, mes_likes = {}, {}, [], set()
    par_com = {}
    for c in recents:                       # 20 derniers commentaires de chaque publication
        lst = par_com.setdefault(c.publication_id, [])
        if len(lst) < 20:
            lst.append(c)
    for lst in par_com.values():
        lst.reverse()
    ids_auteurs = {c.user_id for lst in par_com.values() for c in lst}
    auteurs = {u.id: u for u in User.query.filter(User.id.in_(ids_auteurs)).all()} if ids_auteurs else {}
    vues = []
    for p in pubs:
        ext = (p.media_url or '').lower().rsplit('.', 1)[-1] if p.media_url else ''
        coms = [SimpleNamespace(author=auteurs.get(c.user_id), contenu=c.contenu)
                for c in par_com.get(p.id, [])]
        vues.append(SimpleNamespace(
            id=p.id, page=pages_vue[par_pub[p.id]], date_creation=p.date_creation,
            contenu=(p.contenu or '').strip(), media_url=p.media_url, est_video=ext in EXT_VIDEOS,
            likes=_Liste([], nb_likes.get(p.id, 0)),
            commentaires=_Liste(coms, nb_coms.get(p.id, 0))))
    return vues, mes_likes


# ───────────────────────── Pages (HTML) ─────────────────────────
def _rendre_profil(page):
    uid = _uid()
    pv = _vue_page(page)
    est_proprio = bool(uid and uid == page.owner_id)
    suis_abonne = bool(uid and PageSuiviFN.query.filter_by(page_id=page.id, user_id=uid).first())
    apercu = (User.query.join(PageSuiviFN, PageSuiviFN.user_id == User.id)
              .filter(PageSuiviFN.page_id == page.id)
              .order_by(PageSuiviFN.id.desc()).limit(10).all())
    pubs, par_pub = _charger_pubs([page.id], 100)
    publications, mes_likes = _vues_pubs(pubs, par_pub, {page.id: pv}, uid)
    invite = bool(uid and not est_proprio and not suis_abonne and
                  PageInvitationFN.query.filter_by(page_id=page.id, invite_id=uid).first())
    return render_template('page_profil.html', page=pv, publications=publications,
                           mes_likes=mes_likes, est_proprio=est_proprio, suis_abonne=suis_abonne,
                           abonnes_apercu=apercu, invite=invite, page_active=_page_active(uid),
                           user=_utilisateur(uid))


def profil_nouveau(ident):
    """Appelée par pages_facenet.profil() pour /pages/<slug> : même page que /page/<id>."""
    _tables()
    return _rendre_profil(_page_ou_404(ident))


@_route(False)
def fnpage_profil(page_id):
    page = db.session.get(PageFN, page_id) or abort(404)
    return _rendre_profil(page)


@_route(False)
def fnpage_abonnes(page_id):
    page = db.session.get(PageFN, page_id) or abort(404)
    uid = _uid()
    abonnes = (User.query.join(PageSuiviFN, PageSuiviFN.user_id == User.id)
               .filter(PageSuiviFN.page_id == page.id)
               .order_by(PageSuiviFN.id.desc()).limit(300).all())
    return render_template('page_abonnes.html', page=_vue_page(page), abonnes=abonnes,
                           est_proprio=bool(uid and uid == page.owner_id),
                           page_active=_page_active(uid), user=_utilisateur(uid))


@_route()
def fnpage_mes_pages():
    uid = _uid()
    mes = PageFN.query.filter_by(owner_id=uid).order_by(PageFN.id.desc()).all()
    ids_suivies = [l.page_id for l in PageSuiviFN.query.filter_by(user_id=uid).all()]
    suivies = (PageFN.query.filter(PageFN.id.in_(ids_suivies)).order_by(PageFN.id.desc()).limit(50).all()
               if ids_suivies else [])
    return render_template('page_mes_pages.html', mes_pages=[_vue_page(p) for p in mes],
                           pages_suivies=[_vue_page(p) for p in suivies],
                           page_active=_page_active(uid), user=_utilisateur(uid))


@_route()
def fnpage_fil(page_id):
    uid = _uid()
    page = db.session.get(PageFN, page_id) or abort(404)
    if page.owner_id != uid:
        abort(403)
    suivies = [l.suivie_id for l in PageSuiviPageFN.query.filter_by(page_id=page.id).all()]
    ids = [page.id] + suivies
    pages_vue = {p.id: _vue_page(p) for p in PageFN.query.filter(PageFN.id.in_(ids)).all()}
    pubs, par_pub = _charger_pubs(list(pages_vue), 60)
    publications, mes_likes = _vues_pubs(pubs, par_pub, pages_vue, uid)
    suggestions = (PageFN.query.filter(~PageFN.id.in_(ids)).order_by(PageFN.id.desc()).limit(8).all())
    return render_template('page_fil.html', page=pages_vue[page.id], publications=publications,
                           mes_likes=mes_likes, suggestions=[_vue_page(p) for p in suggestions],
                           page_active=_page_active(uid), user=_utilisateur(uid))


@_route()
def fnpage_modifier(page_id):
    uid = _uid()
    page = db.session.get(PageFN, page_id) or abort(404)
    if page.owner_id != uid:
        abort(403)
    cible = url_for('main.fnpage_profil', page_id=page.id)
    if request.method == 'POST':
        try:
            for champ, taille in (('bio', None), ('site_web', 255), ('email', 150), ('telephone', 40),
                                  ('adresse', 200), ('ville', 100), ('code_postal', 20), ('categorie', 120)):
                if champ in request.form:
                    val = request.form.get(champ, '').strip()
                    setattr(page, champ, (val[:taille] if taille else val) or None)
            for quoi in ('avatar', 'couverture'):
                envoye = request.files.get(quoi)
                nom = _sauver_fichier(envoye, EXT_IMAGES)
                if nom:
                    setattr(page, quoi, nom)
                elif envoye is not None and envoye.filename:
                    db.session.rollback()
                    flash("Image non prise en charge (formats : png, jpg, jpeg, gif, webp).", 'error')
                    return redirect(url_for('main.fnpage_modifier', page_id=page.id))
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Modification de Page impossible : {e}")
            flash("Impossible d'enregistrer les modifications pour le moment.", 'error')
            return redirect(url_for('main.fnpage_modifier', page_id=page.id))
        flash('Page mise à jour ✔', 'success')
        return redirect(cible)
    return render_template('page_modifier.html', page=_vue_page(page), categories=CATEGORIES,
                           page_active=_page_active(uid), user=_utilisateur(uid))


@_route()
def fnpage_parametres(page_id):
    uid = _uid()
    page = db.session.get(PageFN, page_id) or abort(404)
    if page.owner_id != uid:
        abort(403)
    if request.method == 'POST':
        try:
            page.emails_promo = request.form.get('emails_promo') == '1'
            page.notif_profil = request.form.get('notif_profil') == '1'
            db.session.commit()
            flash('Paramètres enregistrés ✔', 'success')
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Paramètres de Page impossibles : {e}")
            flash("Impossible d'enregistrer les paramètres pour le moment.", 'error')
        return redirect(url_for('main.fnpage_parametres', page_id=page.id))
    return render_template('page_parametres.html', page=_vue_page(page),
                           page_active=_page_active(uid), user=_utilisateur(uid))


@_route()
def fnpage_basculer(page_id):
    uid = _uid()
    page = db.session.get(PageFN, page_id) or abort(404)
    if page.owner_id != uid:
        abort(403)
    session['fnpage_active'] = page.id
    flash(f"Vous utilisez maintenant la Page « {page.nom} ».", 'success')
    return redirect(url_for('main.fnpage_profil', page_id=page.id))


@_route()
def fnpage_quitter():
    session.pop('fnpage_active', None)
    return redirect(url_for('main.feed'))


# ───────────────────────── Actions (formulaires et JSON) ─────────────────────────
@_route()
def fnpage_publier(page_id):
    uid = _uid()
    page = db.session.get(PageFN, page_id) or abort(404)
    if page.owner_id != uid:
        abort(403)
    cible = url_for('main.fnpage_profil', page_id=page.id)
    contenu = (request.form.get('contenu') or '').strip()[:5000]
    envoye = request.files.get('media')
    media = _sauver_fichier(envoye, EXT_MEDIAS)
    if envoye is not None and envoye.filename and not media:
        flash("Fichier non pris en charge (images : png, jpg, jpeg, gif, webp ; vidéos : mp4, webm).", 'error')
        return redirect(cible)
    if not contenu and not media:
        flash("Écrivez quelque chose ou ajoutez une photo / vidéo.", 'error')
        return redirect(cible)
    try:
        pub = Publication(contenu=contenu or ' ', user_id=uid, media_url=media, confidentialite='public')
        db.session.add(pub)
        db.session.flush()
        db.session.add(PagePubFN(publication_id=pub.id, page_id=page.id))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Publication de Page impossible : {e}")
        flash("Publication impossible pour le moment.", 'error')
        return redirect(cible)
    flash('Publication ajoutée ✔', 'success')
    return redirect(cible + '#pg-pubs')


@_route()
def fnpage_suivre(page_id):
    uid = _uid()
    page = db.session.get(PageFN, page_id)
    if page is None:
        return jsonify(success=False, message='Page introuvable.'), 404
    if page.owner_id == uid:
        return jsonify(success=False, message='Vous gérez déjà cette Page.'), 400
    try:
        ligne = PageSuiviFN.query.filter_by(page_id=page.id, user_id=uid).first()
        if ligne:
            db.session.delete(ligne)
            abonne = False
        else:
            db.session.add(PageSuiviFN(page_id=page.id, user_id=uid))
            abonne = True
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Abonnement à une Page impossible : {e}")
        return jsonify(success=False, message='Action impossible pour le moment.'), 500
    return jsonify(success=True, abonne=abonne,
                   nb_abonnes=PageSuiviFN.query.filter_by(page_id=page.id).count())


@_route()
def fnpage_suivre_page(page_id, autre_id):
    uid = _uid()
    page = db.session.get(PageFN, page_id)
    autre = db.session.get(PageFN, autre_id)
    if page is None or autre is None:
        return jsonify(success=False, message='Page introuvable.'), 404
    if page.owner_id != uid:
        return jsonify(success=False, message='Action non autorisée.'), 403
    if page.id == autre.id:
        return jsonify(success=False, message='Une Page ne peut pas se suivre elle-même.'), 400
    try:
        ligne = PageSuiviPageFN.query.filter_by(page_id=page.id, suivie_id=autre.id).first()
        if ligne:
            db.session.delete(ligne)
            suivie = False
        else:
            db.session.add(PageSuiviPageFN(page_id=page.id, suivie_id=autre.id))
            suivie = True
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Suivi de Page à Page impossible : {e}")
        return jsonify(success=False, message='Action impossible pour le moment.'), 500
    return jsonify(success=True, suivie=suivie)


def _deleguer(endpoint, *args):
    """Appelle une route EXISTANTE de l'application (mêmes règles, mêmes notifications)
    et retourne (données JSON, code HTTP)."""
    vf = current_app.view_functions.get(endpoint)
    if vf is None:
        return {}, 500
    try:
        rep = vf(*args)
    except HTTPException as e:
        return {}, (e.code or 500)
    code = None
    if isinstance(rep, tuple):
        if len(rep) > 1 and isinstance(rep[1], int):
            code = rep[1]
        rep = rep[0]
    if code is None:
        code = getattr(rep, 'status_code', 200)
    data = rep.get_json(silent=True) if hasattr(rep, 'get_json') else None
    return (data if isinstance(data, dict) else {}), code


@_route()
def fnpage_like(pub_id):
    data, code = _deleguer('main.api_toggle_like', pub_id)
    if code >= 300 or not data.get('success'):
        return jsonify(success=False, message=data.get('error') or 'Action impossible.'), (code if code >= 400 else 400)
    return jsonify(success=True, aime=bool(data.get('liked')), nb_likes=data.get('total_likes', 0))


@_route()
def fnpage_commenter(pub_id):
    data, code = _deleguer('main.api_add_comment', pub_id)
    if code >= 300 or not data.get('success'):
        return jsonify(success=False, message=data.get('error') or 'Commentaire impossible.'), (code if code >= 400 else 400)
    avatar = data.get('avatar') or 'default_avatar.png'
    return jsonify(success=True,
                   commentaire={'avatar': url_for('static', filename='uploads/' + avatar),
                                'auteur': data.get('author') or '', 'contenu': data.get('contenu') or ''},
                   nb_commentaires=data.get('comments_count', 0))


@_route()
def fnpage_partager(pub_id):
    pub = db.session.get(Publication, pub_id)
    if pub is None or getattr(pub, 'is_removed', False):
        return jsonify(success=False, message='Publication introuvable.'), 404
    lien = db.session.get(PagePubFN, pub_id)
    base = request.host_url.rstrip('/')
    adresse = base + (url_for('main.fnpage_profil', page_id=lien.page_id) if lien else '/')
    return jsonify(success=True, nb_partages=(getattr(pub, 'share_count', 0) or 0), url=adresse)


@_route()
def fnpage_supprimer_pub(pub_id):
    uid = _uid()
    lien = db.session.get(PagePubFN, pub_id)
    page = db.session.get(PageFN, lien.page_id) if lien else None
    if page is None or page.owner_id != uid:
        return jsonify(success=False, message='Action non autorisée.'), 403
    pub = db.session.get(Publication, pub_id)
    if pub is None:
        return jsonify(success=False, message='Publication introuvable.'), 404
    try:
        pub.is_removed = True
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Suppression de publication de Page impossible : {e}")
        return jsonify(success=False, message='Suppression impossible pour le moment.'), 500
    return jsonify(success=True)


# ───────────────────────── Branchement ─────────────────────────
_ROUTES = (
    ('/page/<int:page_id>', 'fnpage_profil', fnpage_profil, ['GET']),
    ('/page/<int:page_id>/abonnes', 'fnpage_abonnes', fnpage_abonnes, ['GET']),
    ('/page/<int:page_id>/fil', 'fnpage_fil', fnpage_fil, ['GET']),
    ('/page/<int:page_id>/modifier', 'fnpage_modifier', fnpage_modifier, ['GET', 'POST']),
    ('/page/<int:page_id>/parametres', 'fnpage_parametres', fnpage_parametres, ['GET', 'POST']),
    ('/page/<int:page_id>/basculer', 'fnpage_basculer', fnpage_basculer, ['GET']),
    ('/page/quitter', 'fnpage_quitter', fnpage_quitter, ['GET']),
    ('/page/mes-pages', 'fnpage_mes_pages', fnpage_mes_pages, ['GET']),
    ('/page/<int:page_id>/publier', 'fnpage_publier', fnpage_publier, ['POST']),
    ('/page/<int:page_id>/suivre', 'fnpage_suivre', fnpage_suivre, ['POST']),
    ('/page/<int:page_id>/suivre-page/<int:autre_id>', 'fnpage_suivre_page', fnpage_suivre_page, ['POST']),
    ('/page/publication/<int:pub_id>/like', 'fnpage_like', fnpage_like, ['POST']),
    ('/page/publication/<int:pub_id>/commenter', 'fnpage_commenter', fnpage_commenter, ['POST']),
    ('/page/publication/<int:pub_id>/partager', 'fnpage_partager', fnpage_partager, ['POST']),
    ('/page/publication/<int:pub_id>/supprimer', 'fnpage_supprimer_pub', fnpage_supprimer_pub, ['POST']),
)


def init_pages_fn(main_bp):
    """Enregistre les routes sur le blueprint « main » (endpoints main.fnpage_*)."""
    for regle, endpoint, vue, methodes in _ROUTES:
        main_bp.add_url_rule(regle, endpoint=endpoint, view_func=vue, methods=methodes)