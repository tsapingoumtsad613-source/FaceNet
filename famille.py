"""
famille.py : Cercle familial FaceNet
====================================
Fonctionnalités
  • Un utilisateur invite un de ses AMIS VALIDÉS dans son cercle familial et indique librement
    le lien de parenté (frère, demi-sœur, belle-mère, grand-oncle, cousin, conjoint... aucune liste imposée).
  • L'invité reçoit une notification avec les boutons Accepter / Refuser.
  • Seuls les membres qui ont ACCEPTÉ voient les publications et Reels dont la confidentialité est « famille ».
  • Gestion dans /settings/famille : voir, modifier le lien, retirer un membre, quitter un cercle.
  • Le propriétaire du cercle peut donner un NOM à sa famille (ex. « Famille Dupont »), le modifier ou le retirer
    à tout moment ; ce nom est montré aux invités et aux membres.

Sécurité (« Famille uniquement »)
  • Un contenu « famille » n'est visible que par son auteur et par les membres acceptés de SON cercle
    (et seulement tant qu'ils sont toujours amis : retirer un ami ou le bloquer coupe l'accès).
  • En cas d'erreur de base de données, la règle « échoue fermée » : le contenu reste caché.
  • peut_voir_famille() est appelée par _peut_voir_publication() (routes.py), la règle unique déjà utilisée
    par le fil, le profil, les commentaires, les Reels, les partages, etc.
  • clause_publications_visibles() est la même règle écrite en SQL, pour les listes paginées.

Installation
  1. models.py n'est PAS modifié : la colonne Publication.confidentialite (texte) accepte déjà « famille ».
  2. Les nouvelles tables « lien_familial » et « nom_famille » sont créées automatiquement par db.create_all() au démarrage
     (aucune migration manuelle ; avec Flask-Migrate, « flask db migrate » la détectera aussi).
  3. app.py : famille.brancher_sur_main(main_bp) avant app.register_blueprint(main_bp).
"""
import re
from datetime import datetime

from flask import abort, flash, g, jsonify, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import and_, or_

from models import db, User, Notification, DemandeAmitie, Publication

NIVEAU_FAMILLE = 'famille'

# False : seul l'auteur décide qui voit SES contenus « famille » (le plus strict).
# True  : le lien est réciproque (si A ajoute B et que B accepte, ils voient chacun les contenus famille de l'autre).
FAMILLE_RECIPROQUE = False

LONGUEUR_MAX_LIEN = 60
LONGUEUR_MAX_NOM = 60          # nom de la famille (ex. « Famille Dupont »)
MAX_MEMBRES = 200

# Simples SUGGESTIONS d'écriture (liste déroulante) : l'utilisateur peut taper n'importe quel autre lien.
LIENS_SUGGERES = [
    'Père', 'Mère', 'Beau-père', 'Belle-mère', 'Fils', 'Fille', 'Beau-fils', 'Belle-fille',
    'Frère', 'Sœur', 'Demi-frère', 'Demi-sœur', 'Mari', 'Épouse', 'Conjoint(e)',
    'Grand-père', 'Grand-mère', 'Arrière-grand-père', 'Arrière-grand-mère',
    'Petit-fils', 'Petite-fille', 'Oncle', 'Tante', 'Grand-oncle', 'Grand-tante',
    'Neveu', 'Nièce', 'Cousin', 'Cousine', 'Grand-cousin', 'Grande-cousine',
    'Beau-frère', 'Belle-sœur', 'Gendre', 'Belle-fille (bru)', 'Parrain', 'Marraine', 'Filleul(e)',
]

TYPE_INVITATION = 'family_invite'
TYPE_ACCEPTATION = 'family_accept'
CIBLE_NOTIF = 'lien_familial'


# ─── Modèle ───────────────────────────────────────────────────────────────
class LienFamilial(db.Model):
    """proprietaire_id invite membre_id dans SON cercle familial avec le lien « lien »
    (ex. lien = « Frère » : membre_id est le frère de proprietaire_id)."""
    __tablename__ = 'lien_familial'

    id = db.Column(db.Integer, primary_key=True)
    proprietaire_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    membre_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    lien = db.Column(db.String(LONGUEUR_MAX_LIEN), nullable=False)
    statut = db.Column(db.String(20), nullable=False, default='en_attente', index=True)  # en_attente | accepte | refuse
    date_creation = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    date_reponse = db.Column(db.DateTime, nullable=True)

    __table_args__ = (db.UniqueConstraint('proprietaire_id', 'membre_id', name='uq_lien_familial'),)

    proprietaire = db.relationship('User', foreign_keys=[proprietaire_id])
    membre = db.relationship('User', foreign_keys=[membre_id])


class NomFamille(db.Model):
    """Nom que le propriétaire donne à SON cercle familial (ex. « Famille Dupont »). Un seul nom par propriétaire."""
    __tablename__ = 'nom_famille'

    id = db.Column(db.Integer, primary_key=True)
    proprietaire_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, unique=True, index=True)
    nom = db.Column(db.String(LONGUEUR_MAX_NOM), nullable=False)
    date_creation = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    date_modification = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


# ─── Amis et cercle (avec cache par requête) ──────────────────────────────
def _cache():
    """Dictionnaire valable pour la requête en cours (None hors contexte Flask)."""
    try:
        if not hasattr(g, '_famille_cache'):
            g._famille_cache = {}
        return g._famille_cache
    except RuntimeError:
        return None


def _vider_cache():
    try:
        g._famille_cache = {}
    except RuntimeError:
        pass


def amis_ids(user_id):
    """Ids des amis ACCEPTÉS (même source que _amis_ids de routes.py : DemandeAmitie acceptée)."""
    if not user_id:
        return set()
    lignes = (db.session.query(DemandeAmitie.emetteur_id, DemandeAmitie.recepteur_id)
              .filter(DemandeAmitie.statut == 'acceptee',
                      or_(DemandeAmitie.emetteur_id == user_id, DemandeAmitie.recepteur_id == user_id)).all())
    ids = set()
    for emetteur, recepteur in lignes:
        ids.add(recepteur if emetteur == user_id else emetteur)
    ids.discard(user_id)
    return ids


def membres_famille_ids(auteur_id):
    """Ids autorisés à voir les contenus « famille » de auteur_id (hors l'auteur lui-même).
    Échoue fermé : en cas d'erreur, personne."""
    if not auteur_id:
        return set()
    cache, cle = _cache(), ('membres', auteur_id)
    if cache is not None and cle in cache:
        return cache[cle]
    try:
        ids = {r[0] for r in db.session.query(LienFamilial.membre_id).filter(
            LienFamilial.proprietaire_id == auteur_id, LienFamilial.statut == 'accepte').all()}
        if FAMILLE_RECIPROQUE:
            ids |= {r[0] for r in db.session.query(LienFamilial.proprietaire_id).filter(
                LienFamilial.membre_id == auteur_id, LienFamilial.statut == 'accepte').all()}
        if ids:
            ids &= amis_ids(auteur_id)      # plus amis => plus d'accès
    except Exception:
        db.session.rollback()
        ids = set()
    if cache is not None:
        cache[cle] = ids
    return ids


def auteurs_dont_je_suis_membre(viewer_id):
    """Ids des auteurs dont viewer_id fait partie du cercle familial (même règle, vue de l'autre côté)."""
    if not viewer_id:
        return set()
    cache, cle = _cache(), ('auteurs', viewer_id)
    if cache is not None and cle in cache:
        return cache[cle]
    try:
        ids = {r[0] for r in db.session.query(LienFamilial.proprietaire_id).filter(
            LienFamilial.membre_id == viewer_id, LienFamilial.statut == 'accepte').all()}
        if FAMILLE_RECIPROQUE:
            ids |= {r[0] for r in db.session.query(LienFamilial.membre_id).filter(
                LienFamilial.proprietaire_id == viewer_id, LienFamilial.statut == 'accepte').all()}
        if ids:
            ids &= amis_ids(viewer_id)
    except Exception:
        db.session.rollback()
        ids = set()
    if cache is not None:
        cache[cle] = ids
    return ids


def peut_voir_famille(auteur_id, viewer_id):
    """True si viewer_id peut voir un contenu « famille » de auteur_id."""
    if not viewer_id or not auteur_id:
        return False
    if viewer_id == auteur_id:
        return True
    return viewer_id in membres_famille_ids(auteur_id)


def clause_publications_visibles(viewer_id):
    """Même règle que _peut_voir_publication (routes.py), écrite en SQL pour les requêtes paginées :
    public, ses propres publications, celles des amis (niveau « amis ») et celles des cercles familiaux
    dont on est membre (niveau « famille »). Le niveau « prive » n'est visible que par son auteur."""
    niveau = Publication.confidentialite
    publique = or_(niveau.is_(None), niveau == 'public')
    if not viewer_id:
        return publique
    amis = amis_ids(viewer_id)
    familles = auteurs_dont_je_suis_membre(viewer_id)
    conditions = [publique, Publication.user_id == viewer_id]
    if amis:
        conditions.append(and_(niveau == 'amis', Publication.user_id.in_(list(amis))))
    if familles:
        conditions.append(and_(niveau == NIVEAU_FAMILLE, Publication.user_id.in_(list(familles))))
    return or_(*conditions)


# ─── Utilitaires ──────────────────────────────────────────────────────────
def _nom(user):
    return (getattr(user, 'nom_complet', None) or getattr(user, 'username', None) or 'Un utilisateur')


def nettoyer_lien(brut):
    """Texte libre : espaces normalisés, caractères de contrôle retirés. Retourne '' si vide."""
    texte = re.sub(r'[\x00-\x1f\x7f]', ' ', str(brut or ''))
    texte = re.sub(r'\s+', ' ', texte).strip()
    return texte[:LONGUEUR_MAX_LIEN].strip()


def nettoyer_nom(brut):
    """Nom de famille : espaces normalisés, caractères de contrôle retirés. Retourne '' si vide."""
    texte = re.sub(r'[\x00-\x1f\x7f]', ' ', str(brut or ''))
    texte = re.sub(r'\s+', ' ', texte).strip()
    return texte[:LONGUEUR_MAX_NOM].strip()


def nom_famille_de(proprietaire_id):
    """Nom de la famille de proprietaire_id ('' s'il n'en a pas, ou en cas d'erreur : la page ne plante jamais)."""
    if not proprietaire_id:
        return ''
    try:
        ligne = NomFamille.query.filter_by(proprietaire_id=proprietaire_id).first()
        return ligne.nom if ligne else ''
    except Exception:
        db.session.rollback()
        return ''


def noms_familles_de(proprietaires_ids):
    """{proprietaire_id: nom} pour plusieurs propriétaires à la fois (dictionnaire vide en cas d'erreur)."""
    ids = [i for i in set(proprietaires_ids) if i]
    if not ids:
        return {}
    try:
        return {l.proprietaire_id: l.nom for l in NomFamille.query.filter(NomFamille.proprietaire_id.in_(ids)).all()}
    except Exception:
        db.session.rollback()
        return {}


def _veut_json():
    return (request.is_json
            or request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            or request.accept_mimetypes.best == 'application/json')


def _reponse(succes, message, code=None, **extra):
    """JSON pour les appels fetch ; sinon message flash + retour à la page précédente."""
    if _veut_json():
        corps = {'success': bool(succes), 'message': message}
        if not succes:
            corps['error'] = message
        corps.update(extra)
        return jsonify(corps), (code or (200 if succes else 400))
    flash(message, 'success' if succes else 'warning')
    return redirect(request.referrer or url_for('main.famille_page'))


def _notifier(destinataire_id, acteur_id, type_, message, lien):
    db.session.add(Notification(
        recipient_id=destinataire_id, actor_id=acteur_id, verb=type_, type=type_,
        target_type=CIBLE_NOTIF, target_id=lien.id, message=message,
        extra_data={'famille_id': lien.id, 'lien': lien.lien}))


def _notifs_du_lien(lien_id, type_=None):
    q = Notification.query.filter(Notification.target_type == CIBLE_NOTIF, Notification.target_id == lien_id)
    if type_:
        q = q.filter(Notification.type == type_)
    return q.all()


def _cloturer_invitation(lien, statut):
    """Marque la notification d'invitation comme traitée : les boutons disparaissent."""
    for n in _notifs_du_lien(lien.id, TYPE_INVITATION):
        extra = dict(n.extra_data or {})
        extra['traitee'] = True
        extra['statut'] = statut
        n.extra_data = extra
        n.is_read = True


def _message_invitation(lien):
    nom = nom_famille_de(lien.proprietaire_id)
    cercle = f"son cercle familial « {nom} »" if nom else "son cercle familial"
    return (f"{_nom(lien.proprietaire)} vous invite à rejoindre {cercle}. "
            f"Lien de parenté indiqué : {lien.lien}.")


# ─── Routes (branchées sur main_bp, endpoints « main.famille_* ») ─────────
def brancher_sur_main(main_bp):

    def famille_page():
        moi = current_user.id
        liens_possedes = (LienFamilial.query.filter(LienFamilial.proprietaire_id == moi)
                          .order_by(LienFamilial.date_creation.desc()).all())
        liens_recus = (LienFamilial.query.filter(LienFamilial.membre_id == moi)
                       .order_by(LienFamilial.date_creation.desc()).all())
        amis_ok = amis_ids(moi)
        # Un membre n'est affiché « accepté » que s'il est toujours ami (cohérent avec la règle de visibilité).
        membres = [l for l in liens_possedes if l.statut == 'accepte' and l.membre_id in amis_ok]
        invitations_envoyees = [l for l in liens_possedes if l.statut == 'en_attente']
        invitations_recues = [l for l in liens_recus if l.statut == 'en_attente']
        cercles = [l for l in liens_recus if l.statut == 'accepte' and l.proprietaire_id in amis_ok]
        deja = {l.membre_id for l in liens_possedes if l.statut in ('accepte', 'en_attente')}
        amis_disponibles = []
        if amis_ok:
            amis_disponibles = (User.query.filter(User.id.in_(list(amis_ok - deja)))
                                .order_by(User.nom_complet.asc()).all())
        nom_famille = nom_famille_de(moi)
        noms_familles = noms_familles_de([l.proprietaire_id for l in cercles] +
                                         [l.proprietaire_id for l in invitations_recues])
        return render_template('famille.html', membres=membres, invitations_envoyees=invitations_envoyees,
                               invitations_recues=invitations_recues, cercles=cercles,
                               amis_disponibles=amis_disponibles, liens_suggeres=LIENS_SUGGERES,
                               longueur_max_lien=LONGUEUR_MAX_LIEN, nom_famille=nom_famille,
                               noms_familles=noms_familles, longueur_max_nom=LONGUEUR_MAX_NOM)

    def famille_inviter():
        data = request.get_json(silent=True) if request.is_json else request.form
        data = data or {}
        try:
            ami_id = int(data.get('ami_id'))
        except (TypeError, ValueError):
            return _reponse(False, "Choisissez un ami dans la liste.")
        lien_txt = nettoyer_lien(data.get('lien'))
        if not lien_txt:
            return _reponse(False, "Indiquez le lien de parenté (par exemple : frère, belle-mère, cousin).")
        if ami_id == current_user.id:
            return _reponse(False, "Vous ne pouvez pas vous ajouter vous-même.")
        if ami_id not in amis_ids(current_user.id):
            return _reponse(False, "Vous ne pouvez ajouter à votre famille que des amis déjà validés.", 403)
        ami = db.session.get(User, ami_id)
        if ami is None:
            return _reponse(False, "Utilisateur introuvable.", 404)
        if LienFamilial.query.filter_by(proprietaire_id=current_user.id).count() >= MAX_MEMBRES:
            return _reponse(False, "Votre cercle familial a atteint sa taille maximale.")
        try:
            lien = LienFamilial.query.filter_by(proprietaire_id=current_user.id, membre_id=ami_id).first()
            if lien is not None and lien.statut == 'accepte':
                return _reponse(False, f"{_nom(ami)} fait déjà partie de votre cercle familial.")
            if lien is not None and lien.statut == 'en_attente':
                return _reponse(False, f"Une invitation est déjà en attente pour {_nom(ami)}.")
            if lien is None:
                lien = LienFamilial(proprietaire_id=current_user.id, membre_id=ami_id, lien=lien_txt)
                db.session.add(lien)
            else:                                   # ancienne invitation refusée : on peut réinviter
                lien.lien, lien.statut = lien_txt, 'en_attente'
                lien.date_creation, lien.date_reponse = datetime.utcnow(), None
                for n in _notifs_du_lien(lien.id):
                    db.session.delete(n)
            db.session.flush()
            _notifier(ami_id, current_user.id, TYPE_INVITATION, _message_invitation(lien), lien)
            db.session.commit()
            _vider_cache()
        except Exception as e:
            db.session.rollback()
            print(f"[famille] invitation impossible : {e}")
            return _reponse(False, "Une erreur est survenue. Réessayez dans un instant.", 500)
        return _reponse(True, f"Invitation envoyée à {_nom(ami)}.", id=lien.id)

    def famille_repondre(lien_id, action):
        if action not in ('accepter', 'refuser'):
            abort(400)
        lien = db.session.get(LienFamilial, lien_id)
        if lien is None or lien.membre_id != current_user.id:
            return _reponse(False, "Invitation introuvable.", 404)
        if lien.statut != 'en_attente':
            return _reponse(False, "Cette invitation a déjà été traitée.", 409)
        try:
            if action == 'accepter':
                if lien.proprietaire_id not in amis_ids(current_user.id):
                    return _reponse(False, "Vous n'êtes plus ami avec cette personne.", 403)
                lien.statut = 'accepte'
                lien.date_reponse = datetime.utcnow()
                _cloturer_invitation(lien, 'accepte')
                _notifier(lien.proprietaire_id, current_user.id, TYPE_ACCEPTATION,
                          f"{_nom(current_user)} a accepté votre invitation : il/elle fait désormais partie "
                          f"de votre cercle familial ({lien.lien}).", lien)
                message = f"Vous faites maintenant partie du cercle familial de {_nom(lien.proprietaire)}."
            else:
                lien.statut = 'refuse'
                lien.date_reponse = datetime.utcnow()
                _cloturer_invitation(lien, 'refuse')
                message = "Invitation refusée."
            db.session.commit()
            _vider_cache()
        except Exception as e:
            db.session.rollback()
            print(f"[famille] réponse impossible : {e}")
            return _reponse(False, "Une erreur est survenue. Réessayez dans un instant.", 500)
        return _reponse(True, message, statut=lien.statut)

    def famille_modifier(lien_id):
        data = request.get_json(silent=True) if request.is_json else request.form
        data = data or {}
        lien = db.session.get(LienFamilial, lien_id)
        if lien is None or lien.proprietaire_id != current_user.id:
            return _reponse(False, "Membre introuvable.", 404)
        if lien.statut == 'refuse':
            return _reponse(False, "Cette invitation a été refusée.", 409)
        nouveau = nettoyer_lien(data.get('lien'))
        if not nouveau:
            return _reponse(False, "Indiquez le lien de parenté.")
        try:
            lien.lien = nouveau
            if lien.statut == 'en_attente':         # l'invitation affichée chez l'invité reste à jour
                for n in _notifs_du_lien(lien.id, TYPE_INVITATION):
                    n.message = _message_invitation(lien)
                    extra = dict(n.extra_data or {})
                    extra['lien'] = nouveau
                    n.extra_data = extra
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"[famille] modification impossible : {e}")
            return _reponse(False, "Une erreur est survenue. Réessayez dans un instant.", 500)
        return _reponse(True, "Lien de parenté mis à jour.", lien=nouveau)

    def famille_nom():
        """Donne, modifie ou retire (nom vide) le nom de SA famille. Chacun ne gère que son propre cercle."""
        data = request.get_json(silent=True) if request.is_json else request.form
        data = data or {}
        nom = nettoyer_nom(data.get('nom'))
        try:
            ligne = NomFamille.query.filter_by(proprietaire_id=current_user.id).first()
            if not nom:
                if ligne is not None:
                    db.session.delete(ligne)
                message = "Le nom de votre famille a été retiré."
            else:
                if ligne is None:
                    db.session.add(NomFamille(proprietaire_id=current_user.id, nom=nom))
                else:
                    ligne.nom = nom
                message = f"Votre famille s'appelle « {nom} »."
            db.session.flush()
            # les invitations encore en attente affichent le nouveau nom chez l'invité
            for l in LienFamilial.query.filter_by(proprietaire_id=current_user.id, statut='en_attente').all():
                for n in _notifs_du_lien(l.id, TYPE_INVITATION):
                    n.message = _message_invitation(l)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"[famille] nom de la famille impossible : {e}")
            return _reponse(False, "Une erreur est survenue. Réessayez dans un instant.", 500)
        return _reponse(True, message, nom=nom)

    def _supprimer_lien(lien):
        for n in _notifs_du_lien(lien.id, TYPE_INVITATION):
            if lien.statut == 'en_attente':         # invitation annulée : elle disparaît chez l'invité
                db.session.delete(n)
        db.session.delete(lien)

    def famille_retirer(lien_id):
        lien = db.session.get(LienFamilial, lien_id)
        if lien is None or lien.proprietaire_id != current_user.id:
            return _reponse(False, "Membre introuvable.", 404)
        try:
            _supprimer_lien(lien)
            db.session.commit()
            _vider_cache()
        except Exception as e:
            db.session.rollback()
            print(f"[famille] retrait impossible : {e}")
            return _reponse(False, "Une erreur est survenue. Réessayez dans un instant.", 500)
        return _reponse(True, "Membre retiré de votre cercle familial.")

    def famille_quitter(lien_id):
        lien = db.session.get(LienFamilial, lien_id)
        if lien is None or lien.membre_id != current_user.id:
            return _reponse(False, "Cercle introuvable.", 404)
        try:
            _supprimer_lien(lien)
            db.session.commit()
            _vider_cache()
        except Exception as e:
            db.session.rollback()
            print(f"[famille] départ impossible : {e}")
            return _reponse(False, "Une erreur est survenue. Réessayez dans un instant.", 500)
        return _reponse(True, "Vous avez quitté ce cercle familial.")

    regles = [
        ('/settings/famille', 'famille_page', famille_page, ['GET']),
        ('/famille/inviter', 'famille_inviter', famille_inviter, ['POST']),
        ('/famille/nom', 'famille_nom', famille_nom, ['POST']),
        ('/famille/<int:lien_id>/repondre/<action>', 'famille_repondre', famille_repondre, ['POST']),
        ('/famille/<int:lien_id>/modifier', 'famille_modifier', famille_modifier, ['POST']),
        ('/famille/<int:lien_id>/retirer', 'famille_retirer', famille_retirer, ['POST']),
        ('/famille/<int:lien_id>/quitter', 'famille_quitter', famille_quitter, ['POST']),
    ]
    for chemin, endpoint, fonction, methodes in regles:
        main_bp.add_url_rule(chemin, endpoint, login_required(fonction), methods=methodes)