"""Modèles des Pages FaceNet.

Fichier AUTONOME : il n'ajoute que de nouvelles tables (préfixe fn_page_*) et ne
modifie ni models.py ni les tables existantes. Les tables sont créées
automatiquement au premier chargement (voir pages_routes._assurer_tables_pages).
"""
from datetime import datetime

from extensions import db
from models import User  # noqa: F401  (enregistre le modèle User pour les clés étrangères)


class Page(db.Model):
    __tablename__ = 'fn_page'

    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    nom = db.Column(db.String(120), nullable=False)
    categorie = db.Column(db.String(150), nullable=False)
    type_page = db.Column(db.String(20), default='entreprise')   # 'entreprise' | 'creator'
    objectifs = db.Column(db.Text, nullable=True)                # clés séparées par des virgules
    bio = db.Column(db.Text, nullable=True)
    site_web = db.Column(db.String(255), nullable=True)
    email = db.Column(db.String(120), nullable=True)
    telephone = db.Column(db.String(40), nullable=True)
    adresse = db.Column(db.String(200), nullable=True)
    ville = db.Column(db.String(100), nullable=True)
    code_postal = db.Column(db.String(20), nullable=True)
    avatar = db.Column(db.String(200), nullable=True)
    couverture = db.Column(db.String(200), nullable=True)
    emails_promo = db.Column(db.Boolean, default=True)
    notif_profil = db.Column(db.Boolean, default=True)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)

    owner = db.relationship('User', foreign_keys=[owner_id],
                            backref=db.backref('pages_possedees', lazy=True))
    publications = db.relationship('PagePublication', backref='page', lazy=True,
                                   cascade='all, delete-orphan')
    abonnes = db.relationship('PageAbonne', backref='page', lazy=True,
                              cascade='all, delete-orphan')

    @property
    def verifiee(self):
        """Une Page est vérifiée quand son propriétaire a le badge vérifié
        (mêmes règles et mêmes pages d'avantages / d'obtention que le profil)."""
        return bool(getattr(self.owner, 'badge_expire', None))

    @property
    def nb_abonnes(self):
        return PageAbonne.query.filter_by(page_id=self.id).count()

    @property
    def nb_publications(self):
        return PagePublication.query.filter_by(page_id=self.id).count()


class PageAbonne(db.Model):
    """Un utilisateur qui aime / suit une Page."""
    __tablename__ = 'fn_page_abonne'
    __table_args__ = (db.UniqueConstraint('page_id', 'user_id', name='uq_fn_page_abonne'),)

    id = db.Column(db.Integer, primary_key=True)
    page_id = db.Column(db.Integer, db.ForeignKey('fn_page.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    date_abonnement = db.Column(db.DateTime, default=datetime.utcnow)

    user = db.relationship('User')


class PageInvitation(db.Model):
    """Ami invité à aimer la Page lors de sa création."""
    __tablename__ = 'fn_page_invitation'
    __table_args__ = (db.UniqueConstraint('page_id', 'user_id', name='uq_fn_page_invitation'),)

    id = db.Column(db.Integer, primary_key=True)
    page_id = db.Column(db.Integer, db.ForeignKey('fn_page.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    date_invitation = db.Column(db.DateTime, default=datetime.utcnow)


class PageSuit(db.Model):
    """Une Page qui en suit une autre : alimente le fil d'actualité de la Page."""
    __tablename__ = 'fn_page_suit'
    __table_args__ = (db.UniqueConstraint('page_id', 'suivie_id', name='uq_fn_page_suit'),)

    id = db.Column(db.Integer, primary_key=True)
    page_id = db.Column(db.Integer, db.ForeignKey('fn_page.id'), nullable=False, index=True)
    suivie_id = db.Column(db.Integer, db.ForeignKey('fn_page.id'), nullable=False, index=True)
    date_suivi = db.Column(db.DateTime, default=datetime.utcnow)


class PagePublication(db.Model):
    __tablename__ = 'fn_page_publication'

    id = db.Column(db.Integer, primary_key=True)
    page_id = db.Column(db.Integer, db.ForeignKey('fn_page.id'), nullable=False, index=True)
    contenu = db.Column(db.Text, nullable=True)
    media_url = db.Column(db.String(200), nullable=True)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    likes = db.relationship('PageLike', backref='publication', lazy=True,
                            cascade='all, delete-orphan')
    commentaires = db.relationship('PageCommentaire', backref='publication', lazy=True,
                                   cascade='all, delete-orphan',
                                   order_by='PageCommentaire.date_creation')

    @property
    def est_video(self):
        return bool(self.media_url) and self.media_url.rsplit('.', 1)[-1].lower() in ('mp4', 'mov', 'webm')


class PageLike(db.Model):
    __tablename__ = 'fn_page_like'
    __table_args__ = (db.UniqueConstraint('publication_id', 'user_id', name='uq_fn_page_like'),)

    id = db.Column(db.Integer, primary_key=True)
    publication_id = db.Column(db.Integer, db.ForeignKey('fn_page_publication.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)


class PageCommentaire(db.Model):
    __tablename__ = 'fn_page_commentaire'

    id = db.Column(db.Integer, primary_key=True)
    publication_id = db.Column(db.Integer, db.ForeignKey('fn_page_publication.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    contenu = db.Column(db.Text, nullable=False)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)

    author = db.relationship('User')


TABLES_PAGES = (Page, PageAbonne, PageInvitation, PageSuit,
                PagePublication, PageLike, PageCommentaire)