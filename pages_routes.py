"""Routes des Pages FaceNet (création, profil, fil d'actualité, modification).

Branchement : à la toute fin de routes.py, ajouter ces deux lignes
    from pages_routes import enregistrer_pages
    enregistrer_pages(main_bp)
Toutes les routes sont nouvelles (préfixes /pages/... et /page/...) et leurs
fonctions portent le préfixe « fnpage_ » : aucun conflit avec l'existant.
"""
import os
import time

from flask import (render_template, request, redirect, url_for, flash, jsonify, abort)
from flask_login import login_required, current_user
from sqlalchemy import or_, func, desc
from werkzeug.utils import secure_filename

from extensions import db
from models import User, DemandeAmitie
from pages_models import (Page, PageAbonne, PageInvitation, PageSuit, PagePublication,
                          PageLike, PageCommentaire, TABLES_PAGES)

EXT_IMAGES = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
EXT_VIDEOS = {'mp4', 'mov', 'webm'}
MAX_PAGES_PAR_UTILISATEUR = 20
TAILLE_FIL = 50

OBJECTIFS = {
    'creator': [
        ('creer_contenu', 'Créer et partager du contenu', 'Publiez régulièrement des photos, vidéos et actualités.'),
        ('communaute', 'Développer ma communauté', 'Gagnez des abonnés et échangez avec eux.'),
        ('monetiser', 'Monétiser mon contenu', 'Générez des revenus grâce à votre audience.'),
        ('marques', 'Collaborer avec des marques', 'Travaillez avec des entreprises et des partenaires.'),
    ],
    'entreprise': [
        ('vendre', 'Promouvoir mes produits ou services', 'Montrez ce que vous proposez à vos clients.'),
        ('clients', 'Trouver de nouveaux clients', 'Touchez des personnes susceptibles d\'être intéressées.'),
        ('contacter', 'Être contacté par mes clients', 'Facilitez les appels, e-mails et messages.'),
        ('infos', 'Partager des informations sur mon entreprise', 'Horaires, adresse, actualités et offres.'),
    ],
}

_TABLES_OK = False


def _extension(nom):
    return nom.rsplit('.', 1)[-1].lower() if nom and '.' in nom else ''


def _sauver_fichier(fichier, prefixe, extensions):
    """Enregistre un fichier dans static/uploads (comme edit_profile) et renvoie son nom, ou None."""
    if not fichier or not fichier.filename:
        return None
    if _extension(fichier.filename) not in extensions:
        return None
    nom = '%d_%s_%s' % (int(time.time() * 1000), prefixe, secure_filename(fichier.filename))
    dossier = os.path.join('static', 'uploads')
    os.makedirs(dossier, exist_ok=True)
    fichier.save(os.path.join(dossier, nom))
    return nom


def _amis_de(user_id):
    """Utilisateurs amis (demandes d'amitié acceptées), comme dans le fil principal."""
    demandes = DemandeAmitie.query.filter(DemandeAmitie.statut == 'acceptee').filter(
        or_(DemandeAmitie.emetteur_id == user_id, DemandeAmitie.recepteur_id == user_id)).all()
    ids = {d.recepteur_id if d.emetteur_id == user_id else d.emetteur_id for d in demandes}
    ids.discard(user_id)
    if not ids:
        return []
    return User.query.filter(User.id.in_(ids)).order_by(User.nom_complet).all()


def _page_ou_404(page_id):
    page = db.session.get(Page, page_id)
    if not page:
        abort(404)
    return page


def _proprietaire_ou_403(page):
    if page.owner_id != current_user.id:
        abort(403)


def _nettoyer(valeur, limite):
    return (valeur or '').strip()[:limite] or None


def _contexte_publications(publications):
    """Infos par publication : mes likes (ids) pour afficher le cœur plein."""
    ids = [p.id for p in publications]
    mes_likes = set()
    if ids and current_user.is_authenticated:
        mes_likes = {l.publication_id for l in PageLike.query.filter(
            PageLike.publication_id.in_(ids), PageLike.user_id == current_user.id).all()}
    return mes_likes


def enregistrer_pages(main_bp):

    @main_bp.before_app_request
    def _assurer_tables_pages():
        """Crée une seule fois les nouvelles tables (même principe que _ensure_*_schema)."""
        global _TABLES_OK
        if _TABLES_OK:
            return
        _TABLES_OK = True
        try:
            for modele in TABLES_PAGES:
                modele.__table__.create(bind=db.engine, checkfirst=True)
        except Exception as e:
            print("DEBUG: création des tables Pages non effectuée : %s" % e)

    # ───────────────────────── Création ─────────────────────────
    @main_bp.route('/pages/creer', methods=['GET', 'POST'])
    @login_required
    def fnpage_creer():
        if request.method == 'GET':
            return render_template('page_creer.html', categories=[],
                                   amis=_amis_de(current_user.id), objectifs=OBJECTIFS)

        nom = (request.form.get('nom') or '').strip()
        categorie = (request.form.get('categorie') or '').strip()
        type_page = request.form.get('type_page') or 'entreprise'
        if len(nom) < 2:
            return jsonify(success=False, message="Le nom de la Page doit contenir au moins 2 caractères.")
        if not categorie:
            return jsonify(success=False, message="Choisissez une catégorie.")
        if type_page not in ('entreprise', 'creator'):
            type_page = 'entreprise'
        if Page.query.filter_by(owner_id=current_user.id).count() >= MAX_PAGES_PAR_UTILISATEUR:
            return jsonify(success=False, message="Vous avez atteint le nombre maximal de Pages.")

        try:
            avatar = _sauver_fichier(request.files.get('avatar'), 'page_avatar', EXT_IMAGES)
            couverture = _sauver_fichier(request.files.get('couverture'), 'page_cover', EXT_IMAGES)
            page = Page(
                owner_id=current_user.id, nom=nom[:120], categorie=categorie[:150],
                type_page=type_page,
                objectifs=_nettoyer(request.form.get('objectifs'), 500),
                bio=_nettoyer(request.form.get('bio'), 2000),
                site_web=_nettoyer(request.form.get('site_web'), 255),
                email=_nettoyer(request.form.get('email'), 120),
                telephone=_nettoyer(request.form.get('telephone'), 40),
                adresse=_nettoyer(request.form.get('adresse'), 200),
                ville=_nettoyer(request.form.get('ville'), 100),
                code_postal=_nettoyer(request.form.get('code_postal'), 20),
                avatar=avatar, couverture=couverture,
                emails_promo=request.form.get('emails_promo') == '1',
                notif_profil=request.form.get('notif_profil') == '1',
            )
            db.session.add(page)
            db.session.flush()

            # Amis invités : uniquement de vrais amis de l'utilisateur
            ids_demandes = {int(x) for x in (request.form.get('amis') or '').split(',') if x.strip().isdigit()}
            if ids_demandes:
                ids_amis = {a.id for a in _amis_de(current_user.id)}
                for uid in ids_demandes & ids_amis:
                    db.session.add(PageInvitation(page_id=page.id, user_id=uid))
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print("DEBUG: création de Page impossible : %s" % e)
            return jsonify(success=False, message="Impossible de créer la Page pour le moment.")
        return jsonify(success=True, url=url_for('main.fnpage_profil', page_id=page.id))

    # ───────────────────────── Mes Pages ─────────────────────────
    @main_bp.route('/pages/mes')
    @login_required
    def fnpage_mes_pages():
        mes_pages = Page.query.filter_by(owner_id=current_user.id).order_by(desc(Page.date_creation)).all()
        suivies = (Page.query.join(PageAbonne, PageAbonne.page_id == Page.id)
                   .filter(PageAbonne.user_id == current_user.id).order_by(Page.nom).all())
        return render_template('pages_mes.html', mes_pages=mes_pages, pages_suivies=suivies)

    # ───────────────────────── Profil de la Page ─────────────────────────
    @main_bp.route('/page/<int:page_id>')
    @login_required
    def fnpage_profil(page_id):
        page = _page_ou_404(page_id)
        est_proprio = page.owner_id == current_user.id
        publications = (PagePublication.query.filter_by(page_id=page.id)
                        .order_by(desc(PagePublication.date_creation)).limit(TAILLE_FIL).all())
        suis_abonne = PageAbonne.query.filter_by(page_id=page.id, user_id=current_user.id).first() is not None
        invite = (not est_proprio and not suis_abonne and
                  PageInvitation.query.filter_by(page_id=page.id, user_id=current_user.id).first() is not None)
        return render_template('page_profil.html', page=page, publications=publications,
                               est_proprio=est_proprio, suis_abonne=suis_abonne, invite=invite,
                               mes_likes=_contexte_publications(publications))

    # ───────────────────────── Fil d'actualité de la Page ─────────────────────────
    @main_bp.route('/page/<int:page_id>/fil')
    @login_required
    def fnpage_fil(page_id):
        page = _page_ou_404(page_id)
        _proprietaire_ou_403(page)
        suivies_ids = [s.suivie_id for s in PageSuit.query.filter_by(page_id=page.id).all()]
        publications = (PagePublication.query
                        .filter(PagePublication.page_id.in_([page.id] + suivies_ids))
                        .order_by(desc(PagePublication.date_creation)).limit(TAILLE_FIL).all())
        requete = Page.query.filter(Page.id != page.id)
        if suivies_ids:
            requete = requete.filter(~Page.id.in_(suivies_ids))
        suggestions = requete.order_by(func.random()).limit(8).all()
        return render_template('page_fil.html', page=page, publications=publications,
                               suggestions=suggestions, nb_suivies=len(suivies_ids),
                               mes_likes=_contexte_publications(publications))

    @main_bp.route('/page/<int:page_id>/suivre-page/<int:autre_id>', methods=['POST'])
    @login_required
    def fnpage_suivre_page(page_id, autre_id):
        page = _page_ou_404(page_id)
        _proprietaire_ou_403(page)
        autre = _page_ou_404(autre_id)
        if autre.id == page.id:
            return jsonify(success=False, message="Une Page ne peut pas se suivre elle-même.")
        lien = PageSuit.query.filter_by(page_id=page.id, suivie_id=autre.id).first()
        if lien:
            db.session.delete(lien)
            suivie = False
        else:
            db.session.add(PageSuit(page_id=page.id, suivie_id=autre.id))
            suivie = True
        db.session.commit()
        return jsonify(success=True, suivie=suivie)

    # ───────────────────────── Modifier la Page ─────────────────────────
    @main_bp.route('/page/<int:page_id>/modifier', methods=['GET', 'POST'])
    @login_required
    def fnpage_modifier(page_id):
        page = _page_ou_404(page_id)
        _proprietaire_ou_403(page)
        if request.method == 'POST':
            nom = (request.form.get('nom') or '').strip()
            categorie = (request.form.get('categorie') or '').strip()
            if len(nom) < 2 or not categorie:
                flash("Le nom (2 caractères minimum) et la catégorie sont obligatoires.", 'error')
                return redirect(url_for('main.fnpage_modifier', page_id=page.id))
            try:
                page.nom = nom[:120]
                page.categorie = categorie[:150]
                if request.form.get('type_page') in ('entreprise', 'creator'):
                    page.type_page = request.form.get('type_page')
                page.bio = _nettoyer(request.form.get('bio'), 2000)
                page.site_web = _nettoyer(request.form.get('site_web'), 255)
                page.email = _nettoyer(request.form.get('email'), 120)
                page.telephone = _nettoyer(request.form.get('telephone'), 40)
                page.adresse = _nettoyer(request.form.get('adresse'), 200)
                page.ville = _nettoyer(request.form.get('ville'), 100)
                page.code_postal = _nettoyer(request.form.get('code_postal'), 20)
                avatar = _sauver_fichier(request.files.get('profile_pic'), 'page_avatar', EXT_IMAGES)
                if avatar:
                    page.avatar = avatar
                couverture = _sauver_fichier(request.files.get('cover_pic'), 'page_cover', EXT_IMAGES)
                if couverture:
                    page.couverture = couverture
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                print("DEBUG: modification de Page impossible : %s" % e)
                flash("Impossible d'enregistrer les modifications.", 'error')
                return redirect(url_for('main.fnpage_modifier', page_id=page.id))
            flash('Page mise à jour avec succès !', 'success')
            return redirect(url_for('main.fnpage_profil', page_id=page.id))
        return render_template('page_modifier.html', page=page)

    @main_bp.route('/page/<int:page_id>/supprimer', methods=['POST'])
    @login_required
    def fnpage_supprimer(page_id):
        page = _page_ou_404(page_id)
        _proprietaire_ou_403(page)
        PageSuit.query.filter(or_(PageSuit.page_id == page.id, PageSuit.suivie_id == page.id)).delete(synchronize_session=False)
        PageInvitation.query.filter_by(page_id=page.id).delete(synchronize_session=False)
        db.session.delete(page)
        db.session.commit()
        flash('Page supprimée.', 'success')
        return redirect(url_for('main.fnpage_mes_pages'))

    # ───────────────────────── Abonnement (j'aime la Page) ─────────────────────────
    @main_bp.route('/page/<int:page_id>/suivre', methods=['POST'])
    @login_required
    def fnpage_suivre(page_id):
        page = _page_ou_404(page_id)
        if page.owner_id == current_user.id:
            return jsonify(success=False, message="Vous gérez déjà cette Page.")
        lien = PageAbonne.query.filter_by(page_id=page.id, user_id=current_user.id).first()
        if lien:
            db.session.delete(lien)
            abonne = False
        else:
            db.session.add(PageAbonne(page_id=page.id, user_id=current_user.id))
            PageInvitation.query.filter_by(page_id=page.id, user_id=current_user.id).delete(synchronize_session=False)
            abonne = True
        db.session.commit()
        return jsonify(success=True, abonne=abonne, nb_abonnes=page.nb_abonnes)

    # ───────────────────────── Publications ─────────────────────────
    @main_bp.route('/page/<int:page_id>/publier', methods=['POST'])
    @login_required
    def fnpage_publier(page_id):
        page = _page_ou_404(page_id)
        _proprietaire_ou_403(page)
        contenu = (request.form.get('contenu') or '').strip()[:5000]
        media = _sauver_fichier(request.files.get('media'), 'page_pub', EXT_IMAGES | EXT_VIDEOS)
        if not contenu and not media:
            flash("Écrivez quelque chose ou ajoutez une photo ou une vidéo.", 'error')
        else:
            db.session.add(PagePublication(page_id=page.id, contenu=contenu or None, media_url=media))
            db.session.commit()
        retour = request.form.get('retour')
        if retour == 'fil':
            return redirect(url_for('main.fnpage_fil', page_id=page.id))
        return redirect(url_for('main.fnpage_profil', page_id=page.id))

    @main_bp.route('/page/publication/<int:pub_id>/supprimer', methods=['POST'])
    @login_required
    def fnpage_supprimer_pub(pub_id):
        pub = db.session.get(PagePublication, pub_id)
        if not pub:
            return jsonify(success=False, message="Publication introuvable."), 404
        if pub.page.owner_id != current_user.id:
            return jsonify(success=False, message="Action non autorisée."), 403
        db.session.delete(pub)
        db.session.commit()
        return jsonify(success=True)

    @main_bp.route('/page/publication/<int:pub_id>/like', methods=['POST'])
    @login_required
    def fnpage_like(pub_id):
        pub = db.session.get(PagePublication, pub_id)
        if not pub:
            return jsonify(success=False, message="Publication introuvable."), 404
        like = PageLike.query.filter_by(publication_id=pub.id, user_id=current_user.id).first()
        if like:
            db.session.delete(like)
            aime = False
        else:
            db.session.add(PageLike(publication_id=pub.id, user_id=current_user.id))
            aime = True
        db.session.commit()
        return jsonify(success=True, aime=aime,
                       nb_likes=PageLike.query.filter_by(publication_id=pub.id).count())

    @main_bp.route('/page/publication/<int:pub_id>/commenter', methods=['POST'])
    @login_required
    def fnpage_commenter(pub_id):
        pub = db.session.get(PagePublication, pub_id)
        if not pub:
            return jsonify(success=False, message="Publication introuvable."), 404
        contenu = ((request.get_json(silent=True) or {}).get('contenu') or request.form.get('contenu') or '').strip()[:1000]
        if not contenu:
            return jsonify(success=False, message="Le commentaire est vide.")
        com = PageCommentaire(publication_id=pub.id, user_id=current_user.id, contenu=contenu)
        db.session.add(com)
        db.session.commit()
        return jsonify(success=True, nb_commentaires=len(pub.commentaires), commentaire={
            'auteur': current_user.nom_complet or current_user.username,
            'avatar': url_for('static', filename='uploads/' + (current_user.avatar or 'default_avatar.png')),
            'contenu': com.contenu,
        })