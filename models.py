import uuid
from extensions import db
from flask_login import UserMixin
import hashlib
import math
import re
import unicodedata
from datetime import datetime, timedelta
from sqlalchemy import or_
from sqlalchemy import JSON
from sqlalchemy import Index
from sqlalchemy.orm import synonym


# --- TABLE DE LIAISON POUR LES GROUPES ---
# NOTE : cette table brute (db.Table) n'était utilisée nulle part dans routes.py
# (aucune relation many-to-many "secondary=group_members" n'existe). Le vrai lien
# groupe <-> membre passe par le modèle GroupMember ci-dessous. On la supprime
# pour éviter la confusion et les doublons de schéma.

class Group(db.Model):
    __tablename__ = 'group'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=True)
    cover_url = db.Column(db.String(255), nullable=True)
    is_private = db.Column(db.Boolean, default=False)
    admin_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)

    admin = db.relationship('User', foreign_keys=[admin_id])
    # Correction : la classe s'appelle GroupMembers (avec un s), pas GroupMember.
    # Une relation qui pointe vers un nom de classe inexistant fait planter
    # TOUTE requête de l'app (SQLAlchemy configure tous les mappers ensemble).
    members = db.relationship('GroupMembers', backref='group', lazy=True, cascade='all, delete-orphan')
    posts = db.relationship('GroupPost', backref='group', lazy=True, cascade='all, delete-orphan')

class GroupMembers(db.Model):
    __tablename__ = 'group_members'
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    role = db.Column(db.String(20), default='membre')
    date_adhesion = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User')

class GroupPost(db.Model):
    __tablename__ = 'group_post'
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=False)
    auteur_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    contenu = db.Column(db.Text, nullable=False)
    media_url = db.Column(db.String(255), nullable=True)
    est_epingle = db.Column(db.Boolean, default=False)
    date_pub = db.Column(db.DateTime, default=datetime.utcnow)

    auteur_rel = db.relationship('User')
    comments = db.relationship('GroupComment', backref='post', lazy=True, cascade='all, delete-orphan')
    likes = db.relationship('GroupPostLike', backref='post', lazy=True, cascade='all, delete-orphan')

    @property
    def likes_count(self):
        return len(self.likes)

    @property
    def comments_count(self):
        return len(self.comments)

class GroupComment(db.Model):
    __tablename__ = 'group_comment'
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('group_post.id'), nullable=False)
    auteur_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    contenu = db.Column(db.Text, nullable=False)
    date_com = db.Column(db.DateTime, default=datetime.utcnow)

    auteur_rel = db.relationship('User')

class GroupPostLike(db.Model):
    __tablename__ = 'group_post_like'
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('group_post.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date_like = db.Column(db.DateTime, default=datetime.utcnow)

class GroupJoinRequest(db.Model):
    __tablename__ = 'group_join_request'
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('group.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    statut = db.Column(db.String(20), default='en_attente')
    date_demande = db.Column(db.DateTime, default=datetime.utcnow)

class User(db.Model, UserMixin):
    __tablename__ = 'user'

    id = db.Column(db.Integer, primary_key=True)
    
    # --- Identifiants & Connexion ---
    username = db.Column(db.String(80), nullable=False)
    password = db.Column(db.String(200), nullable=False)
    
    # Inscription soit par email, soit par téléphone (les deux acceptent NULL)
    email = db.Column(db.String(120), nullable=True, unique=True)
    phone = db.Column(db.String(20), nullable=True, unique=True)

    # --- Informations de base (Optionnelles à l'inscription) ---
    nom_complet = db.Column(db.String(150), nullable=True) 
    nom = db.Column(db.String(100), nullable=True)
    prenom = db.Column(db.String(80), nullable=True)
    birth_date = db.Column(db.Date, nullable=True)

    last_name_change = db.Column(db.DateTime, nullable=True)
    name_change_count = db.Column(db.Integer, default=0)
    
    # Images de profil / couverture (avec valeurs par défaut)
    avatar = db.Column(db.String(200), default='default_avatar.png', nullable=True)
    couverture = db.Column(db.String(200), default='default_cover.png', nullable=True)

    # --- Profil & Biographie ---
    biographie = db.Column(db.Text, nullable=True)
    bio = db.Column(db.Text, nullable=True)
    localisation = db.Column(db.String(100), nullable=True)
    ville = db.Column(db.String(100), nullable=True)
    emploi_actuel = db.Column(db.String(100), nullable=True)

    # --- Statuts & Badges ---
    is_pdg = db.Column(db.Boolean, default=False)
    is_verify = db.Column(db.Boolean, default=False)
    has_badge_bleu = db.Column(db.Boolean, default=False)
    is_online = db.Column(db.Boolean, default=False)
    # Horodatage réel de la dernière activité (login + heartbeat périodique côté client).
    # Sert à calculer dynamiquement "En ligne" / "Actif il y a X minutes/heures/jours".
    last_seen = db.Column(db.DateTime, nullable=True)
    followers_count = db.Column(db.Integer, default=0)
    following_count = db.Column(db.Integer, default=0)
    forfait_type = db.Column(db.String(50), nullable=True)
    badge_expire = db.Column(db.DateTime, nullable=True)

    # --- Vérification d'identité (badge Tsapi Verified) ---
    piece_identite_type = db.Column(db.String(50), nullable=True)
    piece_identite_fichier = db.Column(db.String(255), nullable=True)
    piece_identite_date = db.Column(db.DateTime, nullable=True)

    # --- Sécurité & Réinitialisation ---
    reset_code = db.Column(db.String(10), nullable=True)
    reset_code_expires = db.Column(db.DateTime, nullable=True)
    reset_attempts = db.Column(db.Integer, nullable=False, default=0, server_default='0')  # AJOUT : essais faux du code e-mail
    is_restricted = db.Column(db.Boolean, default=False)
    restriction_raison = db.Column(db.String(200), nullable=True)
    restriction_fin = db.Column(db.DateTime, nullable=True)

    # --- AJOUT pour le système de signalement (signalements.py) ---
    # server_default indispensable : donne False aux comptes déjà existants.
    is_banned = db.Column(db.Boolean, nullable=False, server_default=db.false())

    # --- Réseaux & Horodatage ---
    reseaux_sociaux = db.Column(db.Text, default="{}")
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=True)

    # --- Informations personnelles ---
    sexe = db.Column(db.String(20), nullable=True)
    situation_amoureuse = db.Column(db.String(50), nullable=True)
    langues = db.Column(db.String(200), nullable=True)
    site_web = db.Column(db.String(200), nullable=True)

    # --- Travail et études ---
    entreprise = db.Column(db.String(150), nullable=True)
    ecole = db.Column(db.String(150), nullable=True)
    universite = db.Column(db.String(150), nullable=True)

    # --- Centres d'intérêt ---
    groupes_musicaux_preferes = db.Column(db.String(300), nullable=True)
    films_preferes = db.Column(db.String(300), nullable=True)
    jeux_video_preferes = db.Column(db.String(300), nullable=True)
    emissions_tv_preferees = db.Column(db.String(300), nullable=True)

    #--- class pour standards de la communauté ---
    accepted_standards = db.Column(db.Boolean, default=False)

    # --- Préférences story : Confidentialité de la story ---
    instagram_username = db.Column(db.String(80), nullable=True)
    partage_instagram_actif = db.Column(db.Boolean, default=False)
    pellicule_sync_actif = db.Column(db.Boolean, default=True)

    # --- Confidentialité & sécurité de la messagerie (écran "Confidentialité et sécurité") ---
    message_permission = db.Column(db.String(20), default='tout_le_monde')  # 'tout_le_monde' | 'amis'
    confirmations_lecture_actif = db.Column(db.Boolean, default=True)
    apercus_liens_actif = db.Column(db.Boolean, default=True)

    # --- AJOUT ADDITIF : publication automatique lors d'un changement de
    # photo de profil/couverture (visible dans le fil + historique du profil).
    # True par défaut pour ne pas changer le comportement visible des comptes
    # existants tant que l'utilisateur n'a pas explicitement désactivé l'option.
    notifier_changement_photo = db.Column(db.Boolean, default=True)

    # --- AJOUT ADDITIF : alias « compte certifié » pour les templates (badge bleu #1DA1F2) ---
    # Aucune colonne ajoutée à `user` : rien à migrer, aucune requête existante n'est touchée.
    # Même règle que _verification_statut_utilisateur() : is_verify ET has_badge_bleu.
    @property
    def is_verified(self):
        return bool(self.is_verify and self.has_badge_bleu)

    # --- Règle des 15 jours pour le changement de nom (ajout) ---
    def jours_restants_changement_nom(self, delai_jours=15):
        """0 si le changement est autorisé, sinon le nombre de jours restants."""
        if not self.last_name_change:
            return 0
        reste = (self.last_name_change + timedelta(days=delai_jours)) - datetime.utcnow()
        if reste.total_seconds() <= 0:
            return 0
        return math.ceil(reste.total_seconds() / 86400)

    @property
    def friends(self):
        demandes_acceptees = DemandeAmitie.query.filter(
            DemandeAmitie.statut == 'acceptee',
            or_(DemandeAmitie.emetteur_id == self.id,
                DemandeAmitie.recepteur_id == self.id)
        ).all()
        amis_ids = [
            d.recepteur_id if d.emetteur_id == self.id else d.emetteur_id
            for d in demandes_acceptees
        ]
        if not amis_ids:
            return []
        return User.query.filter(User.id.in_(amis_ids)).all()

    # --- AJOUT ADDITIF : bouton d'action du profil (table `bouton_action`) ---
    # Aucune colonne ajoutée à `user` : rien à migrer. Ces propriétés permettent
    # à profile.html de lire le bouton comme s'il s'agissait de simples champs.
    @property
    def badge_bleu_actif(self):
        """True seulement si l'abonnement du badge bleu est en cours (badge_expire dans le futur)."""
        exp = self.badge_expire
        return bool(exp and exp > datetime.utcnow())

    @property
    def bouton_action_data(self):
        """dict prêt pour le template (type, valeur, label, icon, color, href...) ou None.
        Le bouton n'existe que pendant l'abonnement badge bleu ; la ligne en base est conservée."""
        if not self.badge_bleu_actif:
            return None
        return donnees_bouton_action(self.id)

    @property
    def action_button_type(self):
        d = self.bouton_action_data
        return d['type'] if d else None

    @property
    def action_button_value(self):
        d = self.bouton_action_data
        return (d['valeur'] or '') if d else None

# --- AUTRES MODÈLES ---
class Publication(db.Model):
    __tablename__ = 'publication'
    id = db.Column(db.Integer, primary_key=True)
    contenu = db.Column(db.Text, nullable=False)
    media_url = db.Column(db.String(200), nullable=True)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    background_color = db.Column(db.String(100), default='transparent', nullable=True)
    confidentialite = db.Column(db.String(20), default='public', nullable=False)
    share_count = db.Column(db.Integer, default=0, nullable=False)
    est_reel = db.Column(db.Boolean, default=False, nullable=False)   # ← AJOUT
    humeur = db.Column(db.String(50), nullable=True)  # ← AJOUT : "se sent heureux", etc. (utilisé par feed.html)
    # ── AJOUT ADDITIF : champs envoyés par le composer de feed.html et affichés par
    # _feed_card_macro.html (personnes identifiées, numéro d'appel, pays). ──
    identifies = db.Column(db.Text, nullable=True)        # ids séparés par des virgules : "3,12,40"
    telephone = db.Column(db.String(40), nullable=True)   # ex. "+237 612345678"
    pays = db.Column(db.String(100), nullable=True)
    # --- AJOUT pour le système de signalement (signalements.py) ---
    # Masque la publication du feed/profil quand un signalement est approuvé.
    is_removed = db.Column(db.Boolean, nullable=False, server_default=db.false())
    # ── AJOUT ADDITIF : la musique attachée à une publication n'était jamais enregistrée
    # (le formulaire l'envoyait mais aucune colonne ni route ne la sauvegardait). ──
    musique = db.Column(db.String(200), nullable=True)              # "Titre — Artiste"
    musique_preview_url = db.Column(db.String(500), nullable=True)  # extrait audio (iTunes)
    musique_cover_url = db.Column(db.String(500), nullable=True)    # pochette
    # ── AJOUT ADDITIF : point de départ (en secondes) choisi par l'utilisateur
    # dans l'écran "Terminé" du sélecteur de musique, pour ajuster le passage
    # de l'extrait qui sera entendu par les autres. ──
    musique_debut = db.Column(db.Float, nullable=True, default=0)
    musique_duree = db.Column(db.Integer, default=0, nullable=True) # ← AJOUT DE LA COLONNE MANQUANTE ICI !
    # ── AJOUT ADDITIF : distingue une publication normale d'une publication
    # automatique créée lors d'un changement de photo de profil/couverture.
    # None/'' pour toute publication existante ou normale (comportement inchangé).
    type_publication = db.Column(db.String(30), nullable=True)  # None | 'photo_profil' | 'photo_couverture'
    # Mention de transparence IA, persistée avec la publication.
    mention_ia = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    mention_ia_type = db.Column(db.String(30), nullable=True)  # texte | image | video | mixte

    commentaires = db.relationship('Commentaire', backref='publication', lazy=True, cascade="all, delete-orphan")
    likes = db.relationship('Like', backref='publication', lazy=True, cascade="all, delete-orphan")
    # ← AJOUT : sans cette relation, feed.html (pub.author.nom_complet) plantait
    # dès qu'une publication existait, car Publication n'avait qu'un user_id brut,
    # pas de vraie relation SQLAlchemy vers User.
    author = db.relationship('User', foreign_keys=[user_id], backref=db.backref('publications', lazy=True)) 

    # ── AJOUT ADDITIF : nombre de vues, lu par routes.py (p.vues / pub.vues) et par profile.html.
    # Cette colonne n'a jamais existé sur Publication : toute lecture de .vues levait une AttributeError
    # (500 sur /profile/<username>/photos/<type>, /api/photo/<type>/publication, etc.) et Jinja imprimait
    # une valeur vide dans le onclick du visualiseur (erreur de syntaxe JS). Propriété en lecture seule,
    # calculée depuis PublicationVideoView : aucune colonne ni migration.
    @property
    def vues(self):
        try:
            if not _assurer_table_vues_modele():
                return 0
            return PublicationVideoView.query.filter_by(publication_id=self.id).count()
        except Exception:
            return 0


class ScheduledPublication(db.Model):
    """File durable des publications à publier à une date future.

    Le contenu reste hors du fil tant que le worker ne l'a pas converti en
    Publication. Le statut est verrouillé atomiquement pour éviter les doublons
    si plusieurs workers Flask sont actifs.
    """
    __tablename__ = 'scheduled_publication'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    payload = db.Column(JSON, nullable=False)
    scheduled_at = db.Column(db.DateTime, nullable=False, index=True)  # UTC naïf
    status = db.Column(db.String(20), nullable=False, default='pending', server_default='pending', index=True)
    attempts = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    last_error = db.Column(db.Text, nullable=True)
    published_publication_id = db.Column(db.Integer, db.ForeignKey('publication.id'), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    user = db.relationship('User', foreign_keys=[user_id])
    publication = db.relationship('Publication', foreign_keys=[published_publication_id])


class Like(db.Model):
    __tablename__ = 'likes'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    publication_id = db.Column(db.Integer, db.ForeignKey('publication.id'), nullable=False)

class Commentaire(db.Model):
    __tablename__ = 'commentaire'
    id = db.Column(db.Integer, primary_key=True)
    contenu = db.Column(db.Text, nullable=False)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    publication_id = db.Column(db.Integer, db.ForeignKey('publication.id'), nullable=False)
    author = db.relationship('User', backref=db.backref('mes_commentaires', lazy=True))
    # ── AJOUT ADDITIF : réponses, modification et réactions des commentaires ──
    # parent_id = commentaire racine du fil (les réponses restent à 2 niveaux, comme Facebook).
    parent_id = db.Column(db.Integer, db.ForeignKey('commentaire.id'), nullable=True)
    # reply_to_id / reply_to_user_id = commentaire et personne précis auxquels on répond
    # (pour afficher « En réponse à … » même dans un fil de réponses).
    reply_to_id = db.Column(db.Integer, nullable=True)
    reply_to_user_id = db.Column(db.Integer, nullable=True)
    date_modification = db.Column(db.DateTime, nullable=True)
    parent = db.relationship('Commentaire', remote_side=[id],
                             backref=db.backref('reponses', lazy=True, cascade='all, delete-orphan'))

class CommentaireReaction(db.Model):
    """Une réaction emoji d'un utilisateur sur un commentaire (une seule par personne)."""
    __tablename__ = 'commentaire_reaction'
    id = db.Column(db.Integer, primary_key=True)
    commentaire_id = db.Column(db.Integer, db.ForeignKey('commentaire.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    emoji = db.Column(db.String(16), nullable=False)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    commentaire = db.relationship('Commentaire', backref=db.backref('reactions', lazy=True, cascade='all, delete-orphan'))
    __table_args__ = (db.UniqueConstraint('commentaire_id', 'user_id', name='uq_commentaire_reaction_user'),)

class PublicationShare(db.Model):
    __tablename__ = 'publication_share'
    id = db.Column(db.Integer, primary_key=True)
    publication_id = db.Column(db.Integer, db.ForeignKey('publication.id'), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    recipient_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    share_type = db.Column(db.String(20), default='interne', nullable=False)  # interne | externe
    plateforme = db.Column(db.String(50), nullable=True)
    date_partage = db.Column(db.DateTime, default=datetime.utcnow)
    publication = db.relationship('Publication', backref=db.backref('partages', lazy=True, cascade='all, delete-orphan'))
    sender = db.relationship('User', foreign_keys=[sender_id])
    recipient = db.relationship('User', foreign_keys=[recipient_id])
    __table_args__ = (db.UniqueConstraint('publication_id', 'sender_id', 'recipient_id', name='uq_publication_share_recipient'),)


class CommentaireSignalement(db.Model):
    __tablename__ = 'commentaire_signalement'
    id = db.Column(db.Integer, primary_key=True)
    commentaire_id = db.Column(db.Integer, db.ForeignKey('commentaire.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    raison = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    date_signalement = db.Column(db.DateTime, default=datetime.utcnow)
    statut = db.Column(db.String(20), default='En attente')
    commentaire = db.relationship('Commentaire', backref=db.backref('signalements', lazy=True, cascade='all, delete-orphan'))
    signaleur = db.relationship('User', foreign_keys=[user_id])


class Message(db.Model):
    __tablename__ = 'messages'
    id = db.Column(db.Integer, primary_key=True)
    expediteur_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    destinataire_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    contenu = db.Column(db.Text, nullable=True)
    date_envoi = db.Column(db.DateTime, default=datetime.utcnow)

    # --- Confirmations de lecture ---
    lu = db.Column(db.Boolean, default=False)
    date_lu = db.Column(db.DateTime, nullable=True)

    # --- Pièces jointes (photo / vidéo / vocal / document) : AJOUT ADDITIF ---
    # Colonnes nullable -> ne casse rien sur les messages texte déjà existants.
    media_url = db.Column(db.String(300), nullable=True)       # nom du fichier stocké sur le serveur
    media_type = db.Column(db.String(20), nullable=True)       # 'image' | 'video' | 'audio' | 'document'
    media_filename = db.Column(db.String(200), nullable=True)  # nom d'origine du fichier (affiché pour les documents)

class Friendship(db.Model):
    __tablename__ = 'friendship'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    friend_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    status = db.Column(db.String(20), default='pending')

class Story(db.Model):
    __tablename__ = 'story'
    id = db.Column(db.Integer, primary_key=True)
    image = db.Column(db.String(200), nullable=True)  # nullable : une story texte n'a pas d'image
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)

    # --- Ajouts pour correspondre au créateur de story (texte / média / vocal) ---
    type = db.Column(db.String(20), default='media')       # 'text' | 'media' | 'vocal'
    texte = db.Column(db.Text, nullable=True)               # contenu texte ou légende
    bg_color = db.Column(db.String(20), nullable=True)
    audio = db.Column(db.String(200), nullable=True)        # fichier vocal
    music_title = db.Column(db.String(200), nullable=True)
    music_artist = db.Column(db.String(200), nullable=True)
    music_preview_url = db.Column(db.String(300), nullable=True)
    music_cover = db.Column(db.String(300), nullable=True)

    # --- Confidentialité (écran "Confidentialité de la story") ---
    privacy = db.Column(db.String(20), default='public')    # 'public' | 'amis' | 'personnalise'

    # --- Brouillon : story commencée mais pas encore publiée (dossier "Brouillons") ---
    est_brouillon = db.Column(db.Boolean, default=False)

    auteur = db.relationship('User', backref='stories')

# --- SUIVI DES VUES DE STORY : qui a déjà vu quelle story (anneau bleu = non vue / gris = vue, comme Facebook) ---
class StoryView(db.Model):
    __tablename__ = 'story_view'
    id = db.Column(db.Integer, primary_key=True)
    story_id = db.Column(db.Integer, db.ForeignKey('story.id'), nullable=False)
    viewer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date_vue = db.Column(db.DateTime, default=datetime.utcnow)

    story = db.relationship('Story', backref=db.backref('vues', lazy=True, cascade='all, delete-orphan'))

    __table_args__ = (db.UniqueConstraint('story_id', 'viewer_id', name='uq_story_view_unique'),)

# --- AMI(E)S PROCHES (utilisé par "Ami(e)s proches" dans Confidentialité de la story) ---
class CloseFriend(db.Model):
    __tablename__ = 'close_friend'
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    friend_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date_ajout = db.Column(db.DateTime, default=datetime.utcnow)

# --- "Masquer la story pour" : ces personnes ne verront jamais mes stories ---
class StoryHiddenUser(db.Model):
    __tablename__ = 'story_hidden_user'
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)       # moi
    hidden_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)  # cette personne

# --- "Stories mises en sourdine" : je ne veux plus voir les stories de cette personne ---
class StoryMute(db.Model):
    __tablename__ = 'story_mute'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)         # moi
    muted_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)   # dont je masque les stories

# --- "COMPTES BLOQUÉS" (écran Confidentialité et sécurité > Diffusion des messages) ---
class BlockedUser(db.Model):
    __tablename__ = 'blocked_user'
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)    # moi
    blocked_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)  # la personne bloquée
    date_blocage = db.Column(db.DateTime, default=datetime.utcnow)

    blocked_user = db.relationship('User', foreign_keys=[blocked_id])

# --- "CONTACTS MASQUÉS" : masqués des suggestions de contacts ---
class HiddenContact(db.Model):
    __tablename__ = 'hidden_contact'
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    hidden_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date_ajout = db.Column(db.DateTime, default=datetime.utcnow)

    hidden_user = db.relationship('User', foreign_keys=[hidden_id])

# --- "ALERTES DE SÉCURITÉ" : nouvelles connexions / modifications de clé de discussion ---
class SecurityAlert(db.Model):
    __tablename__ = 'security_alert'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    type = db.Column(db.String(50), default='connexion')  # 'connexion' | 'cle_modifiee'
    appareil = db.Column(db.String(150), nullable=True)
    localisation = db.Column(db.String(150), nullable=True)
    date_alerte = db.Column(db.DateTime, default=datetime.utcnow)
    est_lu = db.Column(db.Boolean, default=False)

"""
models.py — Modèle de données universel pour les notifications.

Une seule table `Notification` gère TOUS les types de notifications
(likes, commentaires, réponses, mentions, messages, demandes d'amis,
abonnements, badges de vérification...) grâce à un schéma générique
inspiré du pattern "Activity Stream" : un verbe (verb) + une cible
polymorphe (target_type / target_id).

Aucune colonne spécifique par type de notification : ajouter un
nouveau type de notification à l'avenir ne demandera AUCUNE migration
de schéma, juste un nouveau "verb" et un listener.
"""

class NotificationVerb:
    """Catalogue centralisé des verbes d'action supportés.
    Évite les chaînes magiques éparpillées dans tout le code.
    """
    LIKE = "like"
    COMMENT = "comment"
    REPLY = "reply"
    MENTION = "mention"
    MESSAGE = "message"
    FRIEND_REQUEST = "friend_request"
    FRIEND_ACCEPT = "friend_accept"
    FOLLOW = "follow"
    VERIFICATION_BADGE = "verification_badge"


class TargetType:
    """Types d'entités pouvant être la cible d'une notification."""
    POST = "post"
    COMMENT = "comment"
    USER = "user"
    MESSAGE = "message"
    FRIEND_REQUEST = "friend_request"


from sqlalchemy.orm import synonym

class Notification(db.Model):
    __tablename__ = "notifications"

    # ✅ CORRECTION : l'id est désormais généré AUTOMATIQUEMENT côté Python
    # grâce à uuid. Plus besoin de recréer la table ni de compter sur
    # l'autoincrement de SQLite, qui ne fonctionnait pas pour BigInteger.
    id = db.Column(
        db.BigInteger,
        primary_key=True,
        default=lambda: uuid.uuid4().int >> 65
    )

    # Destinataire : 'user.id' au singulier pour correspondre à User.__tablename__
    recipient_id = db.Column(
        db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False, index=True
    )

    # Alias pour la compatibilité
    user_id = synonym('recipient_id')

    # Acteur "principal" : 'user.id' au singulier
    actor_id = db.Column(
        db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"),
        nullable=False
    )

    # Alias pour corriger le 'TypeError: sender_id is an invalid keyword argument'
    sender_id = synonym('actor_id')

    # Action réalisée — voir NotificationVerb
    # default= : plusieurs endroits de routes.py (paiement badge, signalements...)
    # créent une Notification sans passer "verb" -> évite l'IntegrityError.
    verb = db.Column(db.String(32), nullable=False, index=True, default="notification")

    # Cible polymorphe (ex: post #42, comment #7, user #3...)
    target_type = db.Column(db.String(32), nullable=False, default="user")
    target_id = db.Column(db.BigInteger, nullable=False, default=0)

    # --- Compatibilité avec le code existant (routes.py, notifications.html) ---
    # Plusieurs routes créent des Notification(type=..., message=...) et le
    # template notifications.html affiche {{ notif.type }} / {{ notif.message }} :
    # ces deux colonnes n'existaient pas ("type" et "message" n'étaient pas
    # des champs valides) -> ajoutées ici pour que ce code (déjà en place,
    # indépendant des signalements) fonctionne enfin.
    type = db.Column(db.String(50), nullable=True)
    message = db.Column(db.Text, nullable=True)

    # Remplacement de JSON par db.JSON
    extra_data = db.Column(db.JSON, nullable=True, default=dict)

    # --- Agrégation ---
    is_aggregated = db.Column(db.Boolean, default=False, nullable=False)
    aggregated_count = db.Column(db.Integer, default=1, nullable=False)
    
    # Remplacement de JSON par db.JSON
    aggregated_actor_ids = db.Column(db.JSON, default=list)

    is_read = db.Column(db.Boolean, default=False, nullable=False, index=True)
    read_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow,
        onupdate=datetime.utcnow, nullable=False
    )

    recipient = db.relationship("User", foreign_keys=[recipient_id])
    actor = db.relationship("User", foreign_keys=[actor_id])

    __table_args__ = (
        db.Index(
            "ix_notif_aggregation_key",
            "recipient_id", "verb", "target_type", "target_id",
        ),
        db.Index("ix_notif_recipient_created", "recipient_id", "created_at"),
    )

    def to_dict(self):
        """Sérialisation prête pour l'API JSON / le WebSocket."""
        return {
            "id": self.id,
            "verb": self.verb,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "is_read": self.is_read,
            "created_at": self.created_at.isoformat(),
            "is_aggregated": self.is_aggregated,
            "aggregated_count": self.aggregated_count,
            "actor": {
                "id": self.actor.id,
                "name": getattr(self.actor, "display_name", None) or self.actor.username,
                "avatar_url": getattr(self.actor, "avatar_url", None),
            },
            "extra_data": self.extra_data or {},
        }
        

class GhostPost(db.Model):
    __tablename__ = 'ghost_post'
    id = db.Column(db.Integer, primary_key=True)
    contenu = db.Column(db.Text, nullable=False)
    expire_at = db.Column(db.DateTime, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    auteur = db.relationship('User', backref='ghost_posts')

# AJOUT : message anonyme laissé sur le profil de quelqu'un (onglet Ghost).
# Nouvelle table créée automatiquement (rien à migrer). `auteur_id` sert uniquement à la
# modération (blocage, limite anti-spam) : il n'est JAMAIS envoyé aux templates.
class GhostMessage(db.Model):
    __tablename__ = 'ghost_message'
    id = db.Column(db.Integer, primary_key=True)
    profil_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)  # destinataire
    auteur_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)              # secret
    contenu = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expire_at = db.Column(db.DateTime, nullable=False)

# AJOUT : indices choisis (volontairement) par l'expéditeur d'un Ghost. Nouvelle table, rien à migrer.
class GhostIndice(db.Model):
    __tablename__ = 'ghost_indice'
    id = db.Column(db.Integer, primary_key=True)
    ghost_id = db.Column(db.Integer, db.ForeignKey('ghost_message.id'), nullable=False, index=True)
    cle = db.Column(db.String(40), nullable=False)

# AJOUT : réponses sous un Ghost (propriétaire du profil <-> expéditeur anonyme). Nouvelle table.
class GhostReponse(db.Model):
    __tablename__ = 'ghost_reponse'
    id = db.Column(db.Integer, primary_key=True)
    ghost_id = db.Column(db.Integer, db.ForeignKey('ghost_message.id'), nullable=False, index=True)
    role = db.Column(db.String(10), nullable=False)   # 'proprio' ou 'anonyme'
    contenu = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class DemandeAmitie(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    emetteur_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    recepteur_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    statut = db.Column(db.String(20), default='en_attente')  # en_attente, acceptee, refusee
    date_envoi = db.Column(db.DateTime, default=datetime.utcnow)

    emetteur = db.relationship('User', foreign_keys=[emetteur_id], backref='sent_requests')
    recepteur = db.relationship('User', foreign_keys=[recepteur_id], backref='received_requests')

class Signalement(db.Model):
    __tablename__ = 'signalement'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    publication_id = db.Column(db.Integer, db.ForeignKey('publication.id'), nullable=False)
    raison = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    date_signalement = db.Column(db.DateTime, default=datetime.utcnow)
    statut = db.Column(db.String(20), default="En attente")
    signaleur = db.relationship('User', foreign_keys=[user_id], backref='mes_signalements_envoyes')
    publication = db.relationship('Publication', foreign_keys=[publication_id], backref='tous_les_signalements')

class DemandeExamen(db.Model):
    __tablename__ = 'demande_examen'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    raison_contestation = db.Column(db.Text, nullable=False)
    date_demande = db.Column(db.DateTime, default=datetime.utcnow)
    statut = db.Column(db.String(20), default='En attente')
    user = db.relationship('User', backref=db.backref('demandes_examen', lazy=True))

class Invitation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    expediteur_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    destinataire_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    date_envoi = db.Column(db.DateTime, default=datetime.utcnow) # en attente, accepter, refuser
    statut = db.Column(db.String(20), default='en_attente')


    expéditeur = db.relationship('User', foreign_keys=[expediteur_id], backref='invitations_envoyees')
    destinataire = db.relationship('User', foreign_keys=[destinataire_id], backref='invitations_recues')

class IAPersonnalisee(db.Model):
    __tablename__ = "ia_personnalisees"
    id = db.Column(db.Integer, primary_key=True)
    proprietaire_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    nom = db.Column(db.String(40), nullable=False)
    avatar_emoji = db.Column(db.String(8), default="🤖")
    personnalite = db.Column(db.Text)
    connaissances = db.Column(db.Text)
    niveau = db.Column(db.String(20), default="basique")  # basique | standard
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)


class IAPersonnaliseeMessage(db.Model):
    __tablename__ = "ia_personnalisee_messages"
    id = db.Column(db.Integer, primary_key=True)
    ia_id = db.Column(db.Integer, db.ForeignKey("ia_personnalisees.id"), nullable=False)
    contenu_utilisateur = db.Column(db.Text)
    reponse_ia = db.Column(db.Text)
    date_envoi = db.Column(db.DateTime, default=datetime.utcnow)

class Reel(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fichier_video = db.Column(db.String(300), nullable=False)
    thumbnail = db.Column(db.String(300))
    description = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    auteur = db.relationship('User', backref='reels')
    publication_id = db.Column(db.Integer, db.ForeignKey('publication.id'), nullable=False)  # ← AJOUT
    publication = db.relationship('Publication')                                              # ← AJOUT

class SignalementPhoto(db.Model):
    __tablename__ = 'signalement_photo'
    id = db.Column(db.Integer, primary_key=True)
    reporter_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    image_url = db.Column(db.String(500), nullable=False)
    publication_id = db.Column(db.Integer, db.ForeignKey('publication.id'), nullable=True)
    date_signalement = db.Column(db.DateTime, default=datetime.utcnow)
    traite = db.Column(db.Boolean, default=False)

class SignalementVideo(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    # Ajoute ici tes autres colonnes (par exemple : user_id, video_id, motif, etc.)

class EnregistrementReel(db.Model):
    __tablename__ = 'enregistrement_reel'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    publication_id = db.Column(db.Integer, db.ForeignKey('publication.id'), nullable=False)  # ou 'reel.id' selon le nom de ta table de vidéos
    date_enregistrement = db.Column(db.DateTime, default=datetime.utcnow)

    # (Optionnel) Relations SQLAlchemy si besoin dans tes templates
    # user = db.relationship('User', backref='reels_enregistres')
    # publication = db.relationship('Publication', backref='enregistrements')

class PostBoost(db.Model):
    __tablename__ = 'post_boosts'

    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('publication.id'), nullable=False)  # Corrigé ici : 'publication.id'
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    objective = db.Column(db.String(50), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    currency = db.Column(db.String(10), nullable=False)
    country = db.Column(db.String(100), nullable=False)
    total_amount = db.Column(db.String(50), nullable=False)
    payment_method = db.Column(db.String(50), nullable=False)
    phone_number = db.Column(db.String(30), nullable=True)
    custom_comments = db.Column(db.JSON, nullable=True)
    status = db.Column(db.String(20), default='active')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # ── AJOUT ADDITIF : date de fin du boost, pour l'expiration automatique ──
    date_fin = db.Column(db.DateTime, nullable=True)

# NOTE (correction) : cette 2e classe « Group » était une définition en double
# de la table 'group' (déjà déclarée plus haut avec name/admin_id/description...).
# Deux classes db.Model sur la même __tablename__ font planter SQLAlchemy au
# chargement de models.py. Supprimée : la classe Group du haut fait déjà tout
# ce qu'il faut (elle a déjà .members via GroupMembers).

# ── AJOUT ADDITIF (Marketplace Pro) : imports nécessaires au statut de l'annonce ──
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy import select as _select, func as _func


class Annonce(db.Model):
    __tablename__ = 'annonces'

    id = db.Column(db.Integer, primary_key=True)
    titre = db.Column(db.String(80), nullable=False)
    description = db.Column(db.Text, nullable=False)
    prix = db.Column(db.Integer, nullable=False)
    negociable = db.Column(db.Boolean, default=False)
    localisation = db.Column(db.String(50), nullable=False)
    categorie = db.Column(db.String(50), nullable=False)
    condition = db.Column(db.String(30), default='Bon etat')
    quantite = db.Column(db.Integer, default=1)
    contact_telephone = db.Column(db.String(30))
    livraison = db.Column(db.Boolean, default=False)
    fait_main = db.Column(db.Boolean, default=False)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)

    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    # ⚠️ adapte 'user.id' au vrai nom de table de ton modèle User si différent

    photos = db.relationship('AnnonceImage', backref='annonce', lazy=True, cascade='all, delete-orphan')

    # ── AJOUT ADDITIF (Marketplace Pro) ─────────────────────────────────────
    # routes_marketplace.py lit « proprietaire_id » : c'est ici le user_id.
    proprietaire_id = synonym('user_id')
    # Le statut (disponible / reserve / vendu) est stocké dans une table à part
    # (AnnonceStatut) : aucune colonne n'est ajoutée à la table 'annonces' existante.
    statut_info = db.relationship('AnnonceStatut', uselist=False, backref='annonce',
                                  cascade='all, delete-orphan')

    @hybrid_property
    def statut(self):
        if self.statut_info is not None and self.statut_info.statut:
            return self.statut_info.statut
        return 'disponible'

    @statut.setter
    def statut(self, valeur):
        if self.statut_info is None:
            self.statut_info = AnnonceStatut(statut=valeur)
        else:
            self.statut_info.statut = valeur

    @statut.expression
    def statut(cls):
        return _func.coalesce(
            _select(AnnonceStatut.statut)
            .where(AnnonceStatut.annonce_id == cls.id)
            .scalar_subquery(),
            'disponible')

    @property
    def statut_modifie_le(self):
        return self.statut_info.modifie_le if self.statut_info is not None else None

    @statut_modifie_le.setter
    def statut_modifie_le(self, valeur):
        if self.statut_info is None:
            self.statut_info = AnnonceStatut(statut='disponible')
        self.statut_info.modifie_le = valeur

    @property
    def image(self):
        # Compatibilité avec marketplace.html, qui lit annonce.image (photo principale)
        return self.photos[0].filename if self.photos else None


class AnnonceImage(db.Model):
    __tablename__ = 'annonce_images'

    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(255), nullable=False)
    annonce_id = db.Column(db.Integer, db.ForeignKey('annonces.id'), nullable=False)
 

# ==========================================================================
# ============  NOUVELLES FONCTIONNALITÉS (ajout additif) ================
# ==========================================================================
# Rien au-dessus n'a été modifié. Les 2 classes ci-dessous sont neuves :
#   - PublicationReaction : réactions multiples (like/love/haha/wow/sad/angry)
#   - PublicationVideoView : compteur de vues vidéo
# Types de réactions autorisés (facile à étendre plus tard)
TYPES_REACTION = ('like', 'love', 'haha', 'wow', 'sad', 'angry')


class PublicationReaction(db.Model):
    """
    Une réaction (type Facebook) d'un utilisateur sur une publication.
    Coexiste avec Like : Like reste utilisé pour le simple clic "J'aime"
    (icône pouce bleu), PublicationReaction mémorise en plus le TYPE de
    réaction choisi via l'appui long.
    """
    __tablename__ = 'publication_reaction'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    publication_id = db.Column(db.Integer, db.ForeignKey('publication.id'), nullable=False)
    type = db.Column(db.String(20), nullable=False, default='like')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('user_id', 'publication_id', name='uq_user_publication_reaction'),
    )


class PublicationVideoView(db.Model):
    """
    Une vue enregistrée sur la vidéo d'une publication.
    On enregistre une ligne par vue (dédoublonnée côté route par
    session/utilisateur) plutôt que d'ajouter une colonne à Publication,
    pour ne rien modifier au modèle existant.
    """
    __tablename__ = 'publication_video_view'

    id = db.Column(db.Integer, primary_key=True)
    publication_id = db.Column(db.Integer, db.ForeignKey('publication.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    session_key = db.Column(db.String(64), nullable=True)  # pour visiteurs non connectés
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


_VUES_TABLE_OK = False


def _assurer_table_vues_modele():
    """Crée la table des vues si elle manque (une seule fois par processus)."""
    global _VUES_TABLE_OK
    if _VUES_TABLE_OK:
        return True
    try:
        PublicationVideoView.__table__.create(bind=db.engine, checkfirst=True)
        _VUES_TABLE_OK = True
    except Exception:
        pass
    return _VUES_TABLE_OK


# ==========================================================================
# ============  SONDAGES & ÉVÉNEMENTS (ajout additif) =====================
# ==========================================================================
# Rien au-dessus n'a été modifié. Un Sondage/Événement est toujours rattaché
# à une Publication existante (comme un "type" de post), sans ajouter la
# moindre colonne à la table Publication : la clé étrangère vit du côté
# de Poll / Event, donc aucun risque de casser Publication.

class Poll(db.Model):
    __tablename__ = 'poll'

    id = db.Column(db.Integer, primary_key=True)
    publication_id = db.Column(db.Integer, db.ForeignKey('publication.id'), nullable=False, unique=True)
    question = db.Column(db.String(300), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    publication = db.relationship('Publication', backref=db.backref('sondage', uselist=False, cascade="all, delete-orphan"))
    options = db.relationship('PollOption', backref='poll', lazy=True, cascade="all, delete-orphan", order_by="PollOption.ordre")
    votes = db.relationship('PollVote', backref='poll', lazy=True, cascade="all, delete-orphan")


class PollOption(db.Model):
    __tablename__ = 'poll_option'

    id = db.Column(db.Integer, primary_key=True)
    poll_id = db.Column(db.Integer, db.ForeignKey('poll.id'), nullable=False)
    texte = db.Column(db.String(120), nullable=False)
    ordre = db.Column(db.Integer, default=0)

    votes = db.relationship('PollVote', backref='option', lazy=True, cascade="all, delete-orphan")


class PollVote(db.Model):
    __tablename__ = 'poll_vote'

    id = db.Column(db.Integer, primary_key=True)
    poll_id = db.Column(db.Integer, db.ForeignKey('poll.id'), nullable=False)
    option_id = db.Column(db.Integer, db.ForeignKey('poll_option.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('poll_id', 'user_id', name='uq_poll_user_vote'),
    )


class Event(db.Model):
    __tablename__ = 'event'

    id = db.Column(db.Integer, primary_key=True)
    publication_id = db.Column(db.Integer, db.ForeignKey('publication.id'), nullable=False, unique=True)
    organisateur_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    titre = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=True)
    lieu = db.Column(db.String(200), nullable=True)
    date_debut = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    publication = db.relationship('Publication', backref=db.backref('evenement', uselist=False, cascade="all, delete-orphan"))
    participations = db.relationship('EventParticipation', backref='event', lazy=True, cascade="all, delete-orphan")


class EventParticipation(db.Model):
    __tablename__ = 'event_participation'

    id = db.Column(db.Integer, primary_key=True)
    event_id = db.Column(db.Integer, db.ForeignKey('event.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    statut = db.Column(db.String(20), nullable=False, default='interesse')  # 'interesse' ou 'participe'
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('event_id', 'user_id', name='uq_event_user_participation'),
    )

# ==========================================
# Modèles Ajoutés pour la Gestion de la Musique
# ==========================================
# ⚠️ CORRECTIF : ces 2 classes ne correspondaient plus à ce que routes.py
# utilise réellement (routes.py lit/écrit titre, artiste, cover_url,
# preview_url — pas musique_id). Avec le schéma précédent (musique_id
# seul), le moindre clic sur le marque-page ou le menu ⋮ du sélecteur de
# musique aurait fait planter le serveur (TypeError: 'titre' is an
# invalid keyword argument). Remis en cohérence avec routes.py ci-dessous.

class MusiqueFavori(db.Model):
    """Une musique qu'un utilisateur a mise en favori depuis le sélecteur
    de musique (bouton marque-page), pour la retrouver rapidement."""
    __tablename__ = 'musique_favori'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    titre = db.Column(db.String(200), nullable=False)
    artiste = db.Column(db.String(200), nullable=True)
    cover_url = db.Column(db.String(500), nullable=True)
    preview_url = db.Column(db.String(500), nullable=True)
    date_ajout = db.Column(db.DateTime, default=datetime.utcnow)


class MusiqueSignalement(db.Model):
    """Un signalement d'audio effectué depuis le menu ⋮ du sélecteur
    de musique (distinct de Signalement/SignalementVideo qui visent
    des publications, pas des morceaux du catalogue iTunes)."""
    __tablename__ = 'musique_signalement'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    titre = db.Column(db.String(200), nullable=False)
    artiste = db.Column(db.String(200), nullable=True)
    date_signalement = db.Column(db.DateTime, default=datetime.utcnow)

# ==========================================================================
# ============  BROUILLONS DE REEL (ajout additif) =======================
# ==========================================================================
# Nouvelle table créée automatiquement par db.create_all() (rien à migrer).
# Un reel enregistré comme brouillon (vidéo pas encore publiée) plutôt que
# publié tout de suite depuis l'écran "Créer un reel".
class ReelBrouillon(db.Model):
    __tablename__ = 'reel_brouillon'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    fichier_video = db.Column(db.String(300), nullable=False)
    miniature = db.Column(db.String(300), nullable=True)
    description = db.Column(db.Text, nullable=True)
    musique = db.Column(db.String(200), nullable=True)
    musique_preview_url = db.Column(db.String(500), nullable=True)
    musique_cover_url = db.Column(db.String(500), nullable=True)
    musique_debut = db.Column(db.Float, nullable=True, default=0)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)

    auteur = db.relationship('User', backref='reels_brouillons')

class NotorietyRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False) # 'user.id' dépend de ton modèle User
    category = db.Column(db.String(50), nullable=False)
    press_links = db.Column(db.Text, nullable=False) # On stocke les liens séparés par des virgules
    id_doc_type = db.Column(db.String(50), nullable=False)
    recto_path = db.Column(db.String(255), nullable=False)
    verso_path = db.Column(db.String(255), nullable=True) # Peut être NULL
    status = db.Column(db.String(20), default='en_attente') # en_attente, approuve, rejete
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relation avec l'utilisateur (optionnel mais recommandé)
    # user = db.relationship('User', backref='notoriety_requests')

# ==========================================================================
# ============  HISTORIQUE PHOTOS DE PROFIL / COUVERTURE (ajout additif) ==
# ==========================================================================
# Nouvelle table créée automatiquement par db.create_all() (rien à migrer).
# Conserve chaque photo de profil/couverture successive d'un utilisateur
# pour permettre un carrousel avec compteur (comme sur Facebook) quand on
# clique sur la photo de profil/couverture de quelqu'un.
class PhotoHistorique(db.Model):
    __tablename__ = 'photo_historique'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    type_photo = db.Column(db.String(20), nullable=False)  # 'avatar' | 'couverture'
    url = db.Column(db.String(200), nullable=False)
    # Publication correspondante dans le fil (peut être vide si l'utilisateur
    # a désactivé la publication automatique au moment du changement).
    publication_id = db.Column(db.Integer, db.ForeignKey('publication.id'), nullable=True)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)

    auteur = db.relationship('User', backref=db.backref('photos_historique', lazy=True))


class MarketplaceConversation(db.Model):
    # NOTE : nouvelle table (l'ancienne 'marketplace_conversation' n'avait que
    # user_id et created_at). db.create_all() la crée toute seule, sans migration.
    __tablename__ = 'marketplace_conversations'

    id = db.Column(db.Integer, primary_key=True)
    annonce_id = db.Column(db.Integer, db.ForeignKey('annonces.id'), nullable=True, index=True)
    seller_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    buyer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_message_at = db.Column(db.DateTime, nullable=True)
    last_message_preview = db.Column(db.String(200), nullable=True)
    # « Supprimer la discussion » : masque l'historique pour une seule personne
    cleared_at_seller = db.Column(db.DateTime, nullable=True)
    cleared_at_buyer = db.Column(db.DateTime, nullable=True)

    __table_args__ = (db.UniqueConstraint('annonce_id', 'buyer_id', name='uq_marketplace_conv_annonce_buyer'),)

    annonce = db.relationship('Annonce', foreign_keys=[annonce_id])
    seller = db.relationship('User', foreign_keys=[seller_id])
    buyer = db.relationship('User', foreign_keys=[buyer_id])

    def a_pour_participant(self, uid):
        return uid is not None and uid in (self.seller_id, self.buyer_id)

    def autre_id(self, uid):
        return self.buyer_id if uid == self.seller_id else self.seller_id

    def cleared_at_pour(self, uid):
        return self.cleared_at_seller if uid == self.seller_id else self.cleared_at_buyer

    def est_visible_pour(self, uid):
        cleared = self.cleared_at_pour(uid)
        if not cleared:
            return True
        # supprimée par cette personne : réapparaît seulement si un nouveau message est arrivé
        return bool(self.last_message_at and self.last_message_at > cleared)

class TelemetryLog(db.Model):
    __tablename__ = 'telemetry_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    ip_address = db.Column(db.String(45), nullable=True)
    screen_resolution = db.Column(db.String(20), nullable=True)
    user_agent = db.Column(db.Text, nullable=True)
    language = db.Column(db.String(10), nullable=True)
    battery_level = db.Column(db.Integer, nullable=True)
    charging = db.Column(db.Boolean, nullable=True)
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Evenement(db.Model):
    __tablename__ = 'evenements'

    id = db.Column(db.Integer, primary_key=True)
    titre = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, nullable=True)
    date_evenement = db.Column(db.DateTime, nullable=False)
    lieu = db.Column(db.String(150), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

 

# ==========================================================================
# ====  ÉVÉNEMENTS : infos complémentaires + réponses (ajout additif)  =====
# ==========================================================================
# Nouvelles tables créées automatiquement par db.create_all() ; la table
# `evenements` existante n'est PAS modifiée (aucune migration).
class EvenementExtra(db.Model):
    __tablename__ = 'evenement_extra'
    evenement_id = db.Column(db.Integer, db.ForeignKey('evenements.id'), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    categorie = db.Column(db.String(60), nullable=True)
    type_evenement = db.Column(db.String(120), nullable=True)
    icone = db.Column(db.String(40), nullable=True)
    image = db.Column(db.String(255), nullable=True)
    reponses = db.Column(db.Text, nullable=True)


class EvenementReponse(db.Model):
    __tablename__ = 'evenement_reponses'
    id = db.Column(db.Integer, primary_key=True)
    evenement_id = db.Column(db.Integer, db.ForeignKey('evenements.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    statut = db.Column(db.String(20), nullable=False)  # 'participe' | 'interesse'
    __table_args__ = (db.UniqueConstraint('evenement_id', 'user_id', name='uq_evenement_reponse'),)


class HistoriqueActivite(db.Model):
    __tablename__ = 'historique_activite'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    type = db.Column(db.String(50), nullable=False)
    url = db.Column(db.String(500), nullable=False)
    titre = db.Column(db.String(255), default='')
    date_consultation = db.Column(db.DateTime, default=datetime.utcnow)

class MarketplaceFavori(db.Model):
    __tablename__ = 'marketplace_favori'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    annonce_id = db.Column(db.Integer, db.ForeignKey('annonces.id'), nullable=False, index=True)
    __table_args__ = (db.UniqueConstraint('user_id', 'annonce_id', name='uq_marketplace_favori'),)
    # AJOUT ADDITIF (Marketplace Pro) : f.annonce, et tri « plus récent d'abord »
    annonce = db.relationship('Annonce')
    created_at = synonym('id')


# ==========================================================================
# ============  VISIBILITÉ DU PROFIL + PARCOURS (ajout additif) ============
# ==========================================================================
# Nouvelle table (créée automatiquement, aucune migration de la table `user`).
#  - visibilite : JSON {"ecole": true, "email": false, ...} -> ce que
#    l'utilisateur accepte d'afficher sur son profil public.
#  - *_debut / *_fin : dates "AAAA-MM" de début et de fin (école, université,
#    entreprise). Elles suivent la visibilité de l'école/université/entreprise.
class ProfilExtra(db.Model):
    __tablename__ = 'profil_extra'

    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    visibilite = db.Column(db.Text, nullable=True)
    ecole_debut = db.Column(db.String(10), nullable=True)
    ecole_fin = db.Column(db.String(10), nullable=True)
    universite_debut = db.Column(db.String(10), nullable=True)
    universite_fin = db.Column(db.String(10), nullable=True)
    entreprise_debut = db.Column(db.String(10), nullable=True)
    entreprise_fin = db.Column(db.String(10), nullable=True)


# ── AJOUT ADDITIF : partenaire identifié dans « Situation amoureuse » ──
# Nouvelle table `profil_partenaire` (créée automatiquement, aucune migration des tables existantes).
# partenaire_id : ami FaceNet réel (vérifié côté serveur) ; sinon nom saisi à la main (manuel=True,
# après confirmation explicite de l'utilisateur).
class ProfilPartenaire(db.Model):
    __tablename__ = 'profil_partenaire'

    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    partenaire_id = db.Column(db.Integer, nullable=True)
    partenaire_nom = db.Column(db.String(80), nullable=True)
    manuel = db.Column(db.Boolean, default=False, nullable=False)
    date_maj = db.Column(db.DateTime, default=datetime.utcnow)


# ── AJOUT ADDITIF : informations de profil supplémentaires (loisirs, sports, livres, plat préféré…) ──
# Table clé/valeur `profil_info_sup`, créée automatiquement : ajouter une information plus tard
# n'exigera aucune nouvelle colonne ni migration.
class ProfilInfoSup(db.Model):
    __tablename__ = 'profil_info_sup'

    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    cle = db.Column(db.String(40), primary_key=True)
    valeur = db.Column(db.String(200), nullable=True)


# ==========================================================================
# ============  BOUTON D'ACTION DU PROFIL (ajout additif) ==================
# ==========================================================================
# Nouvelle table `bouton_action` (créée automatiquement, aucune migration de
# la table `user`). Un seul bouton par utilisateur : le moyen principal par
# lequel les visiteurs peuvent le contacter / agir depuis son profil.
import re as _re_ba
from urllib.parse import urlparse as _urlparse_ba

ACTION_BUTTON_GROUPS = [
    ('contact', 'Contact direct'),
    ('web', 'Site web et services'),
    ('social', 'Réseaux sociaux'),
]

# kind : none (aucune valeur) | phone | email | url | handle (nom d'utilisateur OU lien du réseau)
ACTION_BUTTON_CATALOG = [
    # ---- Contact direct ----
    {'key': 'message', 'group': 'contact', 'label': 'Envoyer un message', 'icon': 'fa-solid fa-comment-dots', 'color': '#1877F2',
     'kind': 'none', 'desc': 'Ouvre la messagerie FaceNet avec vous', 'placeholder': '', 'help': ''},
    {'key': 'whatsapp', 'group': 'contact', 'label': 'Contacter par WhatsApp', 'icon': 'fa-brands fa-whatsapp', 'color': '#25D366',
     'kind': 'phone', 'desc': 'Ouvre une discussion WhatsApp', 'placeholder': 'Ex : 237690000000',
     'help': "Numéro avec l'indicatif du pays, sans + ni espaces."},
    {'key': 'appel', 'group': 'contact', 'label': 'Appeler', 'icon': 'fa-solid fa-phone', 'color': '#1877F2',
     'kind': 'phone', 'desc': 'Lance un appel téléphonique', 'placeholder': 'Ex : +237690000000',
     'help': "Numéro de téléphone, de préférence avec l'indicatif du pays."},
    {'key': 'sms', 'group': 'contact', 'label': 'Envoyer un SMS', 'icon': 'fa-solid fa-message', 'color': '#0E9F6E',
     'kind': 'phone', 'desc': 'Ouvre un SMS pré-adressé', 'placeholder': 'Ex : +237690000000',
     'help': "Numéro de téléphone, de préférence avec l'indicatif du pays."},
    {'key': 'email', 'group': 'contact', 'label': 'Envoyer un e-mail', 'icon': 'fa-solid fa-envelope', 'color': '#5f6368',
     'kind': 'email', 'desc': 'Ouvre votre messagerie e-mail', 'placeholder': 'Ex : contact@exemple.com',
     'help': 'Adresse e-mail de contact.'},
    {'key': 'telegram', 'group': 'contact', 'label': 'Contacter sur Telegram', 'icon': 'fa-brands fa-telegram', 'color': '#229ED9',
     'kind': 'handle', 'desc': 'Ouvre une discussion Telegram', 'placeholder': 'Ex : @votre_nom',
     'help': "Votre nom d'utilisateur Telegram ou votre lien t.me.",
     'base': 'https://t.me/', 'domains': ['t.me', 'telegram.me']},
    # ---- Site web et services ----
    {'key': 'site', 'group': 'web', 'label': 'Visiter le site', 'icon': 'fa-solid fa-globe', 'color': '#1877F2',
     'kind': 'url', 'desc': 'Envoie vers votre site web', 'placeholder': 'Ex : https://exemple.com', 'help': 'Lien complet de votre site.'},
    {'key': 'boutique', 'group': 'web', 'label': 'Voir la boutique', 'icon': 'fa-solid fa-store', 'color': '#E8590C',
     'kind': 'url', 'desc': 'Envoie vers votre boutique en ligne', 'placeholder': 'Ex : https://boutique.exemple.com', 'help': 'Lien de votre boutique.'},
    {'key': 'reserver', 'group': 'web', 'label': 'Réserver', 'icon': 'fa-solid fa-calendar-check', 'color': '#7048E8',
     'kind': 'url', 'desc': 'Envoie vers votre page de réservation', 'placeholder': 'Ex : https://reservation.exemple.com', 'help': 'Lien de votre page de réservation.'},
    {'key': 'rdv', 'group': 'web', 'label': 'Prendre rendez-vous', 'icon': 'fa-solid fa-calendar-days', 'color': '#0C8599',
     'kind': 'url', 'desc': 'Envoie vers votre agenda de rendez-vous', 'placeholder': 'Ex : https://calendly.com/votre-nom', 'help': 'Lien de votre agenda.'},
    {'key': 'inscrire', 'group': 'web', 'label': "S'inscrire", 'icon': 'fa-solid fa-user-plus', 'color': '#2B8A3E',
     'kind': 'url', 'desc': "Envoie vers un formulaire d'inscription", 'placeholder': 'Ex : https://exemple.com/inscription', 'help': "Lien du formulaire d'inscription."},
    {'key': 'video', 'group': 'web', 'label': 'Regarder la vidéo', 'icon': 'fa-solid fa-circle-play', 'color': '#E03131',
     'kind': 'url', 'desc': 'Envoie vers une vidéo', 'placeholder': 'Ex : https://youtube.com/watch?v=...', 'help': 'Lien de la vidéo.'},
    {'key': 'app', 'group': 'web', 'label': "Télécharger l'application", 'icon': 'fa-solid fa-mobile-screen-button', 'color': '#364FC7',
     'kind': 'url', 'desc': "Envoie vers le téléchargement de l'app", 'placeholder': 'Ex : https://play.google.com/store/apps/...', 'help': "Lien de l'application."},
    {'key': 'en_savoir_plus', 'group': 'web', 'label': 'En savoir plus', 'icon': 'fa-solid fa-circle-info', 'color': '#495057',
     'kind': 'url', 'desc': "Envoie vers une page d'information", 'placeholder': 'Ex : https://exemple.com/a-propos', 'help': 'Lien de la page.'},
    # ---- Réseaux sociaux ----
    {'key': 'facebook', 'group': 'social', 'label': 'Voir sur Facebook', 'icon': 'fa-brands fa-facebook', 'color': '#1877F2',
     'kind': 'handle', 'desc': 'Envoie vers votre page Facebook', 'placeholder': "Ex : votre.nom ou lien Facebook",
     'help': "Votre nom d'utilisateur ou le lien de votre profil / page.",
     'base': 'https://www.facebook.com/', 'domains': ['facebook.com', 'fb.com', 'fb.me']},
    {'key': 'instagram', 'group': 'social', 'label': 'Voir sur Instagram', 'icon': 'fa-brands fa-instagram', 'color': '#D6249F',
     'kind': 'handle', 'desc': 'Envoie vers votre compte Instagram', 'placeholder': 'Ex : @votre_nom',
     'help': "Votre nom d'utilisateur Instagram ou le lien de votre profil.",
     'base': 'https://www.instagram.com/', 'domains': ['instagram.com']},
    {'key': 'tiktok', 'group': 'social', 'label': 'Voir sur TikTok', 'icon': 'fa-brands fa-tiktok', 'color': '#111111',
     'kind': 'handle', 'desc': 'Envoie vers votre compte TikTok', 'placeholder': 'Ex : @votre_nom',
     'help': "Votre nom d'utilisateur TikTok ou le lien de votre profil.",
     'base': 'https://www.tiktok.com/@', 'domains': ['tiktok.com']},
    {'key': 'youtube', 'group': 'social', 'label': 'Voir sur YouTube', 'icon': 'fa-brands fa-youtube', 'color': '#FF0000',
     'kind': 'handle', 'desc': 'Envoie vers votre chaîne YouTube', 'placeholder': 'Ex : @votre_chaine',
     'help': "Le nom de votre chaîne (@...) ou le lien de votre chaîne.",
     'base': 'https://www.youtube.com/@', 'domains': ['youtube.com', 'youtu.be']},
    {'key': 'linkedin', 'group': 'social', 'label': 'Voir sur LinkedIn', 'icon': 'fa-brands fa-linkedin', 'color': '#0A66C2',
     'kind': 'handle', 'desc': 'Envoie vers votre profil LinkedIn', 'placeholder': 'Ex : votre-nom ou lien LinkedIn',
     'help': "Votre identifiant LinkedIn ou le lien de votre profil.",
     'base': 'https://www.linkedin.com/in/', 'domains': ['linkedin.com']},
    {'key': 'x', 'group': 'social', 'label': 'Voir sur X', 'icon': 'fa-brands fa-twitter', 'color': '#111111',
     'kind': 'handle', 'desc': 'Envoie vers votre compte X (Twitter)', 'placeholder': 'Ex : @votre_nom',
     'help': "Votre nom d'utilisateur X ou le lien de votre profil.",
     'base': 'https://x.com/', 'domains': ['x.com', 'twitter.com']},
]
_ACTION_BY_KEY = {e['key']: e for e in ACTION_BUTTON_CATALOG}


class BoutonAction(db.Model):
    __tablename__ = 'bouton_action'

    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    type = db.Column(db.String(30), nullable=False)
    valeur = db.Column(db.String(500), nullable=True, default='')
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


def _normaliser_url_ba(v):
    """Retourne une URL http(s) propre, ou None si invalide / dangereuse."""
    v = (v or '').strip()
    low = v.lower()
    if _re_ba.search(r'\s', v):
        return None
    if not (low.startswith('http://') or low.startswith('https://')):
        if '://' in low or _re_ba.match(r'^(javascript|data|vbscript|file|about|blob|mailto|tel|sms):', low):
            return None
        v = 'https://' + v
    try:
        hote = _urlparse_ba(v).hostname or ''
    except ValueError:
        return None
    if '.' not in hote or hote.startswith('.') or hote.endswith('.'):
        return None
    return v


def normaliser_bouton_action(type_, valeur):
    """Valide et nettoie la valeur. Retourne (valeur_normalisée, message_erreur)."""
    entree = _ACTION_BY_KEY.get(type_)
    if not entree:
        return None, "Type de bouton inconnu."
    kind = entree['kind']
    if kind == 'none':
        return '', None
    v = (valeur or '').strip()
    if not v:
        return None, "Veuillez renseigner la valeur du bouton d'action."
    if len(v) > 500:
        return None, "La valeur est trop longue."

    if kind == 'phone':
        a_plus = v.startswith('+') or v.startswith('00')
        chiffres = _re_ba.sub(r'\D', '', v)
        if v.startswith('00'):
            chiffres = chiffres[2:]
        if type_ == 'whatsapp':
            if not (8 <= len(chiffres) <= 15):
                return None, "Entrez un numéro WhatsApp valide avec l'indicatif du pays, ex : 237690000000."
            return chiffres, None
        if not (6 <= len(chiffres) <= 15):
            return None, "Entrez un numéro de téléphone valide."
        return ('+' if a_plus else '') + chiffres, None

    if kind == 'email':
        if len(v) > 254 or not _re_ba.match(r'^[^\s@]+@[^\s@]+\.[^\s@]+$', v):
            return None, "Entrez une adresse e-mail valide."
        return v, None

    if kind == 'url':
        url = _normaliser_url_ba(v)
        if not url:
            return None, "Entrez un lien valide, ex : https://exemple.com"
        return url, None

    if kind == 'handle':
        low = v.lower()
        domaines = entree.get('domains', [])
        ressemble_lien = low.startswith('http://') or low.startswith('https://') or '/' in v or any(d in low for d in domaines)
        if ressemble_lien:
            url = _normaliser_url_ba(v)
            hote = (_urlparse_ba(url).hostname or '').lower() if url else ''
            if not url or not any(hote == d or hote.endswith('.' + d) for d in domaines):
                return None, "Entrez un lien valide de cette plateforme ou simplement votre nom d'utilisateur."
            return url, None
        nom = v.lstrip('@')
        if not _re_ba.match(r'^[A-Za-z0-9._-]{2,64}$', nom):
            return None, "Nom d'utilisateur invalide (lettres, chiffres, points, tirets et underscores uniquement)."
        return nom, None

    return None, "Type de bouton inconnu."


def href_bouton_action(type_, valeur):
    entree = _ACTION_BY_KEY.get(type_)
    if not entree:
        return None
    v = valeur or ''
    if type_ == 'whatsapp':
        return 'https://wa.me/' + v
    if type_ == 'appel':
        return 'tel:' + v
    if type_ == 'sms':
        return 'sms:' + v
    if type_ == 'email':
        return 'mailto:' + v
    if entree['kind'] == 'url':
        return v
    if entree['kind'] == 'handle':
        return v if v.lower().startswith('http') else entree['base'] + v
    return None  # 'message' : lien interne construit dans le template


def donnees_bouton_action(user_id):
    """Dict prêt pour le template, ou None si l'utilisateur n'a pas de bouton."""
    try:
        ba = db.session.get(BoutonAction, user_id)
    except Exception:
        try:
            db.session.rollback()
        except Exception:
            pass
        return None
    if not ba:
        return None
    entree = _ACTION_BY_KEY.get(ba.type)
    if not entree:
        return None
    return {
        'type': ba.type,
        'valeur': ba.valeur or '',
        'label': entree['label'],
        'icon': entree['icon'],
        'color': entree['color'],
        'href': href_bouton_action(ba.type, ba.valeur),
        'new_tab': entree['kind'] in ('url', 'handle') or ba.type == 'whatsapp',
        'interne': entree['kind'] == 'none',
    }


# ==========================================================================
# ====  PROTECTION DES NOMS DES PERSONNALITÉS PUBLIQUES CERTIFIÉES  ========
# ====  + UNICITÉ DES NOMS + SUGGESTIONS (ajout additif)            ========
# ==========================================================================
# Un simple abonné au forfait « Tsapi Verify » (is_verify) n'est PAS protégé : son nom peut être repris.
# Seules les personnalités publiques réellement certifiées (table ci-dessous) sont protégées.
DELAI_CHANGEMENT_NOM_JOURS = 15

# True  : le username ET le nom affiché (nom_complet) des personnalités certifiées sont protégés.
# False : seul le username est protégé.
PROTEGER_NOM_AFFICHE = True

MSG_NOM_CERTIFIE = ("Ce nom est réservé à une personnalité publique certifiée sur FaceNet. "
                    "Veuillez saisir votre propre nom, celui que vos proches utilisent.")


# Nouvelle table `personnalite_certifiee` (créée automatiquement, aucune migration de la table `user`).
# Une ligne = une personnalité publique certifiée dont le nom est protégé contre l'usurpation.
class PersonnaliteCertifiee(db.Model):
    __tablename__ = 'personnalite_certifiee'

    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    categorie = db.Column(db.String(60), nullable=True)
    certifie_le = db.Column(db.DateTime, default=datetime.utcnow)
    certifie_par = db.Column(db.Integer, nullable=True)


def _cle_nom(valeur):
    """Forme comparable : sans accents, minuscules, uniquement lettres/chiffres.
    'Jéan  Dupont', 'jean_dupont' et 'JeanDupont' donnent la même clé,
    ce qui empêche les imitations évidentes d'une personnalité certifiée."""
    s = unicodedata.normalize('NFKD', valeur or '')
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return re.sub(r'[^a-z0-9]', '', s.lower())


def _personnalites_certifiees(exclure_user_id=None):
    q = User.query.join(PersonnaliteCertifiee, PersonnaliteCertifiee.user_id == User.id)
    if exclure_user_id is not None:
        q = q.filter(User.id != exclure_user_id)
    return q.all()


def compte_certifie_possedant_nom(username=None, noms_affiches=(), exclure_user_id=None):
    """Retourne la personnalité publique certifiée dont le username / nom affiché correspond
    à l'un des noms demandés, sinon None. `exclure_user_id` = l'utilisateur lui-même
    (une personnalité certifiée peut évidemment garder son propre nom)."""
    cles = set()
    c = _cle_nom(username)
    if c:
        cles.add(c)
    if PROTEGER_NOM_AFFICHE:
        for n in (noms_affiches or ()):
            c = _cle_nom(n)
            if c:
                cles.add(c)
    if not cles:
        return None
    for u in _personnalites_certifiees(exclure_user_id):
        if _cle_nom(u.username) in cles:
            return u
        if PROTEGER_NOM_AFFICHE and _cle_nom(u.nom_complet) in cles:
            return u
    return None


def username_deja_pris(username, exclure_user_id=None):
    """Règle d'unicité standard (insensible à la casse) pour tous les autres comptes."""
    v = (username or '').strip().lower()
    if not v:
        return False
    q = User.query.filter(db.func.lower(User.username) == v)
    if exclure_user_id is not None:
        q = q.filter(User.id != exclure_user_id)
    return q.first() is not None


def username_libre(base):
    """Username généré à l'inscription : ajoute 2, 3... s'il est déjà pris."""
    base = (base or '').strip().lower() or 'user'
    candidat, n = base, 1
    while username_deja_pris(candidat) or compte_certifie_possedant_nom(username=candidat):
        n += 1
        candidat = f"{base}{n}"
    return candidat


# ── Suggestions de noms proches (écran « Choisissez un autre nom ») ──
_GROUPES_SONS = ('bpv', 'cks', 'dt', 'gj', 'mn', 'lr', 'fv', 'sz', 'yst', 'aeiou')


def _nom_plausible(candidat, original):
    """Écarte les variantes qui ne ressemblent pas à un vrai nom de famille."""
    if len(candidat) < 3 or candidat == original:
        return False
    if not re.search(r'[aeiouy]', candidat):
        return False
    if re.search(r'(.)\1\1', candidat):
        return False
    if re.search(r'([a-z])\1', candidat) and not re.search(r'([a-z])\1', original):
        return False
    if re.search(r'[aeiouy]{3,}', candidat) and not re.search(r'[aeiouy]{3,}', original):
        return False
    if re.search(r'[^aeiouy\W\d_]{4,}', candidat) and not re.search(r'[^aeiouy\W\d_]{4,}', original):
        return False
    return True


def suggerer_noms_proches(prenom, nom, n=3):
    """Jusqu'à `n` variantes proches du nom de famille (même prénom), jamais protégées.
    Seule la dernière partie alphabétique du nom varie (« Van Der Berg » -> « Van Der Bers »).
    Résultat stable : le même nom donne toujours les mêmes suggestions."""
    prenom = (prenom or '').strip()
    nom = (nom or '').strip()
    m = re.search(r"[^\W\d_]+$", nom)
    if not m or len(m.group(0)) < 3:
        return []
    prefixe = nom[:m.start()]
    original = m.group(0)
    low = original.lower()
    variantes = []
    for i in range(1, len(low)):
        variantes.append(low[:i] + low[i + 1:])          # lettre en moins
        ch = low[i]
        for g in _GROUPES_SONS:
            if ch in g:
                for autre in g:
                    if autre != ch:
                        variantes.append(low[:i] + autre + low[i + 1:])   # lettre proche
    vues, pool = set(), []
    for v in variantes:
        if v not in vues and _nom_plausible(v, low):
            vues.add(v)
            pool.append(v)
    pool.sort(key=lambda c: hashlib.md5((low + '|' + c).encode('utf-8')).hexdigest())

    cles_protegees = set()
    for u in _personnalites_certifiees():
        cles_protegees.add(_cle_nom(u.username))
        if PROTEGER_NOM_AFFICHE:
            cles_protegees.add(_cle_nom(u.nom_complet))
    res = []
    for c in pool:
        token = c.capitalize() if original[0].isupper() else c
        nom_s = prefixe + token
        if _cle_nom(f"{prenom}{nom_s}") in cles_protegees or _cle_nom(nom_s) in cles_protegees:
            continue
        res.append({'prenom': prenom, 'nom': nom_s})
        if len(res) >= n:
            break
    return res


def suggerer_depuis_nom_complet(texte, n=3):
    parties = (texte or '').split()
    if len(parties) < 2:
        return []
    return suggerer_noms_proches(' '.join(parties[:-1]), parties[-1], n)

# ==========================================================================
# ============  ABONNEMENTS « SUIVRE » (ajout additif) ====================
# ==========================================================================
# Nouvelle table créée automatiquement (rien à migrer). Un utilisateur
# (follower_id) suit un compte (suivi_id) : utilisé pour le compte officiel
# FaceNet Support, qu'on suit au lieu de l'ajouter en ami.
class Abonnement(db.Model):
    __tablename__ = 'abonnement'
    __table_args__ = (db.UniqueConstraint('follower_id', 'suivi_id', name='uq_abonnement_follower_suivi'),)

    id = db.Column(db.Integer, primary_key=True)
    follower_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    suivi_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)

# --- AJOUT ADDITIF : langue d'interface choisie par l'utilisateur ---
# Table séparée : aucune colonne ajoutée à `user`, rien à migrer.
# Une seule ligne par utilisateur (clé primaire = user_id).
class PreferenceLangue(db.Model):
    __tablename__ = 'preference_langue'

    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    code = db.Column(db.String(10), nullable=False, default='fr')
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

# ==========================================================================
# ============  TRANSPARENCE DU PROFIL (ajout additif) ====================
# ==========================================================================
# À COLLER À LA TOUTE FIN de models.py. Deux nouvelles tables créées à la
# demande (aucune colonne ajoutée à `user`, rien à migrer).

TYPES_AUTRE_NOM = (
    ('pseudo', 'Pseudo'),
    ('nom_jeune_fille', 'Nom de jeune fille'),
    ('autre_orthographe', 'Autre orthographe'),
    ('nom_epoux', "Nom d'époux(se)"),
    ('nom_pere', 'Nom du père'),
    ('nom_naissance', 'Nom de naissance'),
    ('nom_titre', 'Nom avec titre'),
    ('nom_commercial', 'Nom commercial / de marque'),
    ('nom_artiste', "Nom d'artiste"),
    ('autre', 'Autre nom'),
)


class AutreNom(db.Model):
    __tablename__ = 'autre_nom'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    type_nom = db.Column(db.String(30), nullable=False, default='autre')
    nom = db.Column(db.String(150), nullable=False)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)


class ProfilTransparence(db.Model):
    __tablename__ = 'profil_transparence'

    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    mis_a_jour_le = db.Column(db.DateTime, default=datetime.utcnow)
    prononciation = db.Column(db.String(150), nullable=True)
    mentions_legales = db.Column(db.Text, nullable=True)


# --- NOTIFICATIONS PUSH : appareils abonnés (notification même application fermée) ---
class PushSubscription(db.Model):
    __tablename__ = 'push_subscription'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    endpoint = db.Column(db.Text, nullable=False, unique=True)
    p256dh = db.Column(db.String(255), nullable=False)
    auth = db.Column(db.String(255), nullable=False)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)


# ==========================================================================
# ============  PACK SÉCURITÉ PRÉSIDENTIELLE (ajout additif) ===============
# ==========================================================================
# Tables créées automatiquement (rien à migrer, la table `user` n'est pas touchée).
class ProtectionPresidentielle(db.Model):
    __tablename__ = 'protection_presidentielle'

    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    is_president_secure = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    anti_screenshot = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    mode_activation = db.Column(db.String(20), nullable=True)      # 'paiement' | 'protocole'
    reference_paiement = db.Column(db.String(120), nullable=True)  # transId Fapshi
    activated_at = db.Column(db.DateTime, nullable=True)
    # Anti force-brute sur le code de protocole (par utilisateur)
    code_echecs = db.Column(db.Integer, nullable=False, default=0, server_default='0')
    code_bloque_jusqua = db.Column(db.DateTime, nullable=True)


class ProtocolKeyUsage(db.Model):
    """Une clé de protocole = un seul usage. On ne stocke que son hash."""
    __tablename__ = 'protocol_key_usage'

    id = db.Column(db.Integer, primary_key=True)
    key_hash = db.Column(db.String(64), nullable=False, unique=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    used_at = db.Column(db.DateTime, default=datetime.utcnow)


# ==========================================================================
# ============  MARKETPLACE PRO : nouvelles tables (ajout additif) =========
# ==========================================================================
# Créées automatiquement par db.create_all() (aucune migration à faire).
class AnnonceStatut(db.Model):
    __tablename__ = 'annonce_statut'

    annonce_id = db.Column(db.Integer, db.ForeignKey('annonces.id'), primary_key=True)
    statut = db.Column(db.String(20), nullable=False, default='disponible')  # disponible | reserve | vendu
    modifie_le = db.Column(db.DateTime, nullable=True)


class MarketplaceMessage(db.Model):
    __tablename__ = 'marketplace_message'

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey('marketplace_conversations.id'), nullable=False, index=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    contenu = db.Column(db.Text, nullable=False)
    lu = db.Column(db.Boolean, default=False, nullable=False)
    lu_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class MarketplaceBlock(db.Model):
    __tablename__ = 'marketplace_block'

    id = db.Column(db.Integer, primary_key=True)
    blocker_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    blocked_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('blocker_id', 'blocked_id', name='uq_marketplace_block'),)


class MarketplaceReport(db.Model):
    __tablename__ = 'marketplace_report'

    id = db.Column(db.Integer, primary_key=True)
    reporter_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    reported_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    cible_type = db.Column(db.String(20), nullable=False)      # annonce | utilisateur | message
    motif = db.Column(db.String(40), nullable=False)
    description = db.Column(db.String(500), nullable=True)
    annonce_id = db.Column(db.Integer, db.ForeignKey('annonces.id'), nullable=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey('marketplace_conversations.id'), nullable=True)
    message_id = db.Column(db.Integer, db.ForeignKey('marketplace_message.id'), nullable=True)
    extrait_message = db.Column(db.String(1000), nullable=True)
    statut = db.Column(db.String(20), nullable=False, default='en_attente')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

"""
groupes_models.py — Modèles du module « Groupes FaceNet » (tables préfixées grp_).

Ne touche à AUCUNE table existante (ton ancien système Group / GroupMember / GroupPost reste intact).
Toutes les tables enfants portent `groupe_id` : on peut donc purger un groupe en quelques requêtes.
Les identifiants d'utilisateurs sont de simples entiers (pas de clé étrangère vers `user`) pour ne
dépendre ni du nom de ta table utilisateur ni de son moteur.
"""
import json
from datetime import datetime

from extensions import db

VISIBILITES = ('public', 'prive', 'secret')
ROLES = ('membre', 'moderateur', 'admin')
CATEGORIES = ('amis', 'famille', 'etudes', 'travail', 'business', 'sport', 'musique', 'cuisine', 'technologie',
              'religion', 'voyage', 'jeux', 'sante', 'immobilier', 'autre')
REACTIONS = ('jaime', 'adore', 'haha', 'wouah', 'triste', 'grr')


class Grp(db.Model):
    __tablename__ = 'grp_groupe'
    id = db.Column(db.Integer, primary_key=True)
    nom = db.Column(db.String(120), nullable=False, index=True)
    description = db.Column(db.Text, default='')
    categorie = db.Column(db.String(40), default='autre', index=True)
    visibilite = db.Column(db.String(10), default='public', nullable=False, index=True)   # public | prive | secret
    avatar = db.Column(db.String(255))
    couverture = db.Column(db.String(255))
    createur_id = db.Column(db.Integer, nullable=False, index=True)
    cree_le = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    archive = db.Column(db.Boolean, default=False, nullable=False)          # lecture seule
    nb_membres = db.Column(db.Integer, default=0, nullable=False)           # compteur mis à jour par recompter()

    # --- réglages ---
    validation_adhesion = db.Column(db.Boolean, default=False, nullable=False)       # un admin valide chaque demande
    validation_publications = db.Column(db.Boolean, default=False, nullable=False)   # chaque publication passe par la modération
    qui_peut_publier = db.Column(db.String(10), default='tous', nullable=False)      # tous | admins
    qui_peut_inviter = db.Column(db.String(10), default='tous', nullable=False)      # tous | admins
    publications_anonymes = db.Column(db.Boolean, default=True, nullable=False)
    mots_interdits = db.Column(db.Text, default='')                                  # un par ligne ou séparés par des virgules
    anti_flood_secondes = db.Column(db.Integer, default=10, nullable=False)

    def recompter(self):
        self.nb_membres = GrpMembre.query.filter_by(groupe_id=self.id, statut='actif').count()


class GrpMembre(db.Model):
    __tablename__ = 'grp_membre'
    __table_args__ = (db.UniqueConstraint('groupe_id', 'user_id', name='uq_grp_membre'),)
    id = db.Column(db.Integer, primary_key=True)
    groupe_id = db.Column(db.Integer, db.ForeignKey('grp_groupe.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    role = db.Column(db.String(12), default='membre', nullable=False)         # membre | moderateur | admin
    statut = db.Column(db.String(10), default='actif', nullable=False)        # actif | banni
    rejoint_le = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    muet_jusqua = db.Column(db.DateTime)
    avertissements = db.Column(db.Integer, default=0, nullable=False)
    raison_bannissement = db.Column(db.String(255))
    banni_le = db.Column(db.DateTime)

    def est_muet(self):
        return bool(self.muet_jusqua and self.muet_jusqua > datetime.utcnow())


class GrpDemande(db.Model):
    """Demande d'adhésion (groupes à validation / privés)."""
    __tablename__ = 'grp_demande'
    id = db.Column(db.Integer, primary_key=True)
    groupe_id = db.Column(db.Integer, db.ForeignKey('grp_groupe.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    reponses_json = db.Column(db.Text, default='[]')
    statut = db.Column(db.String(12), default='en_attente', nullable=False, index=True)   # en_attente | accepte | refuse
    cree_le = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    traite_par = db.Column(db.Integer)
    traite_le = db.Column(db.DateTime)

    @property
    def reponses(self):
        try:
            return json.loads(self.reponses_json or '[]')
        except ValueError:
            return []


class GrpInvitation(db.Model):
    __tablename__ = 'grp_invitation'
    id = db.Column(db.Integer, primary_key=True)
    groupe_id = db.Column(db.Integer, db.ForeignKey('grp_groupe.id'), nullable=False, index=True)
    invite_id = db.Column(db.Integer, nullable=False, index=True)
    par_id = db.Column(db.Integer, nullable=False)
    statut = db.Column(db.String(12), default='en_attente', nullable=False, index=True)   # en_attente | accepte | refuse
    cree_le = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class GrpQuestion(db.Model):
    """Questions posées aux candidats."""
    __tablename__ = 'grp_question'
    id = db.Column(db.Integer, primary_key=True)
    groupe_id = db.Column(db.Integer, db.ForeignKey('grp_groupe.id'), nullable=False, index=True)
    texte = db.Column(db.String(300), nullable=False)
    ordre = db.Column(db.Integer, default=0, nullable=False)


class GrpRegle(db.Model):
    __tablename__ = 'grp_regle'
    id = db.Column(db.Integer, primary_key=True)
    groupe_id = db.Column(db.Integer, db.ForeignKey('grp_groupe.id'), nullable=False, index=True)
    titre = db.Column(db.String(120), nullable=False)
    detail = db.Column(db.String(600), default='')
    ordre = db.Column(db.Integer, default=0, nullable=False)


class GrpPost(db.Model):
    __tablename__ = 'grp_post'
    id = db.Column(db.Integer, primary_key=True)
    groupe_id = db.Column(db.Integer, db.ForeignKey('grp_groupe.id'), nullable=False, index=True)
    auteur_id = db.Column(db.Integer, nullable=False, index=True)
    contenu = db.Column(db.Text, default='')
    type = db.Column(db.String(10), default='texte', nullable=False)          # texte | annonce | sondage
    statut = db.Column(db.String(12), default='publie', nullable=False, index=True)   # publie | en_attente | refuse | supprime
    motif_attente = db.Column(db.String(60))                                  # pourquoi la modération (info pour les admins)
    epingle = db.Column(db.Boolean, default=False, nullable=False)
    anonyme = db.Column(db.Boolean, default=False, nullable=False)            # nom caché aux membres, visible des admins
    commentaires_fermes = db.Column(db.Boolean, default=False, nullable=False)
    medias_json = db.Column(db.Text, default='[]')
    sondage_fin = db.Column(db.DateTime)
    cree_le = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)
    modifie_le = db.Column(db.DateTime)

    @property
    def medias(self):
        try:
            return json.loads(self.medias_json or '[]')
        except ValueError:
            return []


class GrpOption(db.Model):
    __tablename__ = 'grp_option'
    id = db.Column(db.Integer, primary_key=True)
    groupe_id = db.Column(db.Integer, db.ForeignKey('grp_groupe.id'), nullable=False, index=True)
    post_id = db.Column(db.Integer, db.ForeignKey('grp_post.id'), nullable=False, index=True)
    texte = db.Column(db.String(100), nullable=False)
    ordre = db.Column(db.Integer, default=0, nullable=False)


class GrpVote(db.Model):
    __tablename__ = 'grp_vote'
    __table_args__ = (db.UniqueConstraint('post_id', 'user_id', name='uq_grp_vote'),)
    id = db.Column(db.Integer, primary_key=True)
    groupe_id = db.Column(db.Integer, db.ForeignKey('grp_groupe.id'), nullable=False, index=True)
    post_id = db.Column(db.Integer, db.ForeignKey('grp_post.id'), nullable=False, index=True)
    option_id = db.Column(db.Integer, db.ForeignKey('grp_option.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, nullable=False)


class GrpCom(db.Model):
    __tablename__ = 'grp_com'
    id = db.Column(db.Integer, primary_key=True)
    groupe_id = db.Column(db.Integer, db.ForeignKey('grp_groupe.id'), nullable=False, index=True)
    post_id = db.Column(db.Integer, db.ForeignKey('grp_post.id'), nullable=False, index=True)
    parent_id = db.Column(db.Integer, index=True)                              # réponse à un commentaire (1 niveau)
    auteur_id = db.Column(db.Integer, nullable=False, index=True)
    contenu = db.Column(db.Text, nullable=False)
    supprime = db.Column(db.Boolean, default=False, nullable=False)
    cree_le = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class GrpReaction(db.Model):
    """Réaction sur une publication (cible_type='post') ou un commentaire (cible_type='com')."""
    __tablename__ = 'grp_reaction'
    __table_args__ = (db.UniqueConstraint('cible_type', 'cible_id', 'user_id', name='uq_grp_reaction'),)
    id = db.Column(db.Integer, primary_key=True)
    groupe_id = db.Column(db.Integer, db.ForeignKey('grp_groupe.id'), nullable=False, index=True)
    cible_type = db.Column(db.String(4), nullable=False)
    cible_id = db.Column(db.Integer, nullable=False, index=True)
    user_id = db.Column(db.Integer, nullable=False)
    type = db.Column(db.String(10), default='jaime', nullable=False)


class GrpEvenement(db.Model):
    __tablename__ = 'grp_evenement'
    id = db.Column(db.Integer, primary_key=True)
    groupe_id = db.Column(db.Integer, db.ForeignKey('grp_groupe.id'), nullable=False, index=True)
    createur_id = db.Column(db.Integer, nullable=False)
    titre = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, default='')
    lieu = db.Column(db.String(200), default='')
    debut = db.Column(db.DateTime, nullable=False, index=True)
    fin = db.Column(db.DateTime)
    cree_le = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class GrpRsvp(db.Model):
    __tablename__ = 'grp_rsvp'
    __table_args__ = (db.UniqueConstraint('evenement_id', 'user_id', name='uq_grp_rsvp'),)
    id = db.Column(db.Integer, primary_key=True)
    groupe_id = db.Column(db.Integer, db.ForeignKey('grp_groupe.id'), nullable=False, index=True)
    evenement_id = db.Column(db.Integer, db.ForeignKey('grp_evenement.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, nullable=False)
    reponse = db.Column(db.String(10), default='participe', nullable=False)   # participe | interesse | non


class GrpSignalement(db.Model):
    __tablename__ = 'grp_signalement'
    id = db.Column(db.Integer, primary_key=True)
    groupe_id = db.Column(db.Integer, db.ForeignKey('grp_groupe.id'), nullable=False, index=True)
    cible_type = db.Column(db.String(6), nullable=False)                       # post | com | membre
    cible_id = db.Column(db.Integer, nullable=False)
    signaleur_id = db.Column(db.Integer, nullable=False)
    motif = db.Column(db.String(30), nullable=False)
    detail = db.Column(db.String(500), default='')
    statut = db.Column(db.String(10), default='ouvert', nullable=False, index=True)   # ouvert | traite | rejete
    traite_par = db.Column(db.Integer)
    cree_le = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


class GrpJournal(db.Model):
    """Journal d'audit : qui a fait quoi dans le groupe (visible des admins)."""
    __tablename__ = 'grp_journal'
    id = db.Column(db.Integer, primary_key=True)
    groupe_id = db.Column(db.Integer, db.ForeignKey('grp_groupe.id'), nullable=False, index=True)
    acteur_id = db.Column(db.Integer, nullable=False)
    action = db.Column(db.String(40), nullable=False)
    cible = db.Column(db.String(80), default='')
    detail = db.Column(db.String(300), default='')
    cree_le = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)


class GrpNotif(db.Model):
    __tablename__ = 'grp_notif'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    groupe_id = db.Column(db.Integer, nullable=False)
    texte = db.Column(db.String(300), nullable=False)
    lien = db.Column(db.String(200), default='')
    lu = db.Column(db.Boolean, default=False, nullable=False, index=True)
    cree_le = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


# Ordre de purge d'un groupe (enfants d'abord)
TABLES_ENFANTS = (GrpVote, GrpOption, GrpReaction, GrpCom, GrpPost, GrpRsvp, GrpEvenement, GrpSignalement,
                  GrpJournal, GrpQuestion, GrpRegle, GrpInvitation, GrpDemande, GrpMembre)


def creer_tables():
    """À appeler une fois (dans un app_context) : crée uniquement les tables grp_* manquantes."""
    db.create_all()

# ============================================================================
# À COLLER À LA TOUTE FIN de models.py (après la dernière classe).
# Une nouvelle table, créée automatiquement : aucune migration, aucune
# table existante n'est modifiée.
# ============================================================================

class UneCollection(db.Model):
    """Un contenu « À la une » épinglé sur le profil (ex. « Collection »).
    Les photos sont stockées dans `items` : liste JSON de noms de fichiers
    (relatifs à static/uploads/). `cover_index` = photo de couverture."""
    __tablename__ = 'une_collection'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    titre = db.Column(db.String(18), nullable=False)
    items = db.Column(db.Text, default='[]')
    cover_index = db.Column(db.Integer, default=0)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)