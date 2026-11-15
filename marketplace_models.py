"""
marketplace_models.py — NOUVELLES tables du Marketplace (séquestre, messagerie Marketplace, etc.).

Principe : AUCUNE colonne n'est ajoutée à tes tables existantes (user, annonces, messages…).
Tout ce qui manque est stocké dans de NOUVELLES tables, que `db.create_all()` (déjà présent dans
ton app.py) crée automatiquement au prochain démarrage. Pas de migration, rien n'est cassé.

À la fin du fichier, on « branche » sur ta classe Annonce les noms que tes templates lisent
(annonce.proprietaire_id, annonce.statut, annonce.vendue, annonce.latitude, annonce.longitude).
C'est ce qui répare aussi tes routes existantes api_modifier_prix / api_marquer_vendue, qui
utilisaient déjà ces noms alors que le modèle ne les avait pas.
"""
from datetime import datetime

from extensions import db
from models import Annonce, Message, User  # tes modèles existants


# =============================================================================
# 1) Informations supplémentaires d'une annonce (statut, GPS, vues)
# =============================================================================
class AnnonceInfo(db.Model):
    __tablename__ = 'mk_annonce_info'

    annonce_id = db.Column(db.Integer, db.ForeignKey('annonces.id'), primary_key=True)
    statut = db.Column(db.String(12), nullable=False, default='disponible')  # disponible | reserve | vendu
    latitude = db.Column(db.Float, nullable=True)
    longitude = db.Column(db.Float, nullable=True)
    nb_vues = db.Column(db.Integer, nullable=False, default=0)

    annonce = db.relationship('Annonce', backref=db.backref('info', uselist=False, cascade='all, delete-orphan'))


# =============================================================================
# 2) Messagerie Marketplace (séparée de ta table `messages` pour ne rien mélanger)
# =============================================================================
class MkConversation(db.Model):
    __tablename__ = 'mk_conversation'
    __table_args__ = (db.UniqueConstraint('annonce_id', 'acheteur_id', name='uq_mk_conv'),)

    id = db.Column(db.Integer, primary_key=True)
    annonce_id = db.Column(db.Integer, db.ForeignKey('annonces.id'), nullable=True, index=True)
    acheteur_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    vendeur_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    dernier_message_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    # « Supprimer la conversation » = la retirer de MA liste seulement (l'autre la garde).
    masquee_acheteur = db.Column(db.Boolean, default=False, nullable=False)
    masquee_vendeur = db.Column(db.Boolean, default=False, nullable=False)
    efface_acheteur_a = db.Column(db.DateTime, nullable=True)   # messages antérieurs invisibles pour l'acheteur
    efface_vendeur_a = db.Column(db.DateTime, nullable=True)

    annonce = db.relationship('Annonce')
    messages = db.relationship('MkMessage', backref='conversation', lazy='dynamic', cascade='all, delete-orphan')

    def autre_id(self, user_id):
        return self.vendeur_id if user_id == self.acheteur_id else self.acheteur_id

    def est_participant(self, user_id):
        return user_id in (self.acheteur_id, self.vendeur_id)

    def masquee_pour(self, user_id):
        return self.masquee_acheteur if user_id == self.acheteur_id else self.masquee_vendeur

    def efface_a_pour(self, user_id):
        return self.efface_acheteur_a if user_id == self.acheteur_id else self.efface_vendeur_a


class MkMessage(db.Model):
    __tablename__ = 'mk_message'

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey('mk_conversation.id'), nullable=False, index=True)
    expediteur_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    contenu = db.Column(db.Text, nullable=False, default='')
    systeme = db.Column(db.Boolean, default=False, nullable=False)   # événements du séquestre
    lu = db.Column(db.Boolean, default=False, nullable=False)
    date_envoi = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)


class MkSignalement(db.Model):
    """Signalements du Marketplace (ton modèle `Signalement` existant ne sert qu'aux publications)."""
    __tablename__ = 'mk_signalement'

    id = db.Column(db.Integer, primary_key=True)
    auteur_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    cible_type = db.Column(db.String(10), nullable=False)   # annonce | user | message
    cible_id = db.Column(db.Integer, nullable=False)
    motif = db.Column(db.String(30), nullable=False)
    description = db.Column(db.String(500))
    conversation_id = db.Column(db.Integer)
    statut = db.Column(db.String(15), default='ouvert', nullable=False)
    date = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


# =============================================================================
# 3) Paiement sécurisé (séquestre) + portefeuille
# =============================================================================
class Transaction(db.Model):
    __tablename__ = 'mk_transaction'

    id = db.Column(db.Integer, primary_key=True)
    reference = db.Column(db.String(40), unique=True, nullable=False, index=True)   # notre référence (= externalId Fapshi)
    acheteur_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    vendeur_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    annonce_id = db.Column(db.Integer, db.ForeignKey('annonces.id'), nullable=False, index=True)
    conversation_id = db.Column(db.Integer, db.ForeignKey('mk_conversation.id'), nullable=True)

    montant = db.Column(db.BigInteger, nullable=False)               # XAF, lu sur l'annonce côté serveur
    frais = db.Column(db.BigInteger, nullable=False, default=0)
    montant_net = db.Column(db.BigInteger, nullable=False)
    devise = db.Column(db.String(3), nullable=False, default='XAF')

    # en_attente | sous_sequestre | validee | en_litige | remboursee | echouee
    statut = db.Column(db.String(20), nullable=False, default='en_attente', index=True)
    passerelle = db.Column(db.String(20), nullable=False)
    reference_passerelle = db.Column(db.String(120), index=True)     # transId Fapshi
    lien_paiement = db.Column(db.String(500))

    date_creation = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    date_paiement = db.Column(db.DateTime)
    date_preparation = db.Column(db.DateTime)
    liberation_auto_le = db.Column(db.DateTime)
    date_validation = db.Column(db.DateTime)
    date_litige = db.Column(db.DateTime)
    litige_ouvert_par_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    motif_litige = db.Column(db.String(30))
    description_litige = db.Column(db.Text)
    resolution_litige = db.Column(db.Text)

    annonce = db.relationship('Annonce')


class PortefeuilleUtilisateur(db.Model):
    """Fonds LIBÉRÉS d'un utilisateur (ta table `user` n'est pas modifiée : le solde vit ici)."""
    __tablename__ = 'mk_portefeuille'

    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    solde = db.Column(db.BigInteger, nullable=False, default=0)


class MouvementPortefeuille(db.Model):
    """Journal comptable : chaque variation de solde laisse une ligne."""
    __tablename__ = 'mk_mouvement'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    transaction_id = db.Column(db.Integer, db.ForeignKey('mk_transaction.id'))
    type = db.Column(db.String(30), nullable=False)       # vente | remboursement
    montant = db.Column(db.BigInteger, nullable=False)
    solde_apres = db.Column(db.BigInteger, nullable=False)
    date = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


# =============================================================================
# 4) Suppression de messages privés (« pour moi » / « pour tous »)
#    Alimente ta fonction _ids_messages_caches_pour() de routes.py (qui renvoyait set()).
# =============================================================================
class MessageSuppression(db.Model):
    __tablename__ = 'mk_message_suppression'
    __table_args__ = (db.UniqueConstraint('message_id', 'user_id', name='uq_msg_suppr'),)

    id = db.Column(db.Integer, primary_key=True)
    message_id = db.Column(db.Integer, db.ForeignKey('messages.id'), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    pour_tous = db.Column(db.Boolean, nullable=False, default=False)
    date = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)


# =============================================================================
# 5) Branchement sur ta classe Annonce (propriétés lues par les templates et par routes.py)
# =============================================================================
def _info(annonce, creer=False):
    if annonce.info is None and creer:
        annonce.info = AnnonceInfo(statut='disponible')
    return annonce.info


def _get_statut(self):
    info = self.info
    return info.statut if info and info.statut else 'disponible'


def _set_statut(self, valeur):
    _info(self, creer=True).statut = valeur


def _get_vendue(self):
    return _get_statut(self) == 'vendu'


def _set_vendue(self, valeur):
    _set_statut(self, 'vendu' if valeur else 'disponible')


def _coord(nom):
    def lire(self):
        return getattr(self.info, nom) if self.info else None

    def ecrire(self, valeur):
        setattr(_info(self, creer=True), nom, valeur)
    return property(lire, ecrire)


if not hasattr(Annonce, 'statut'):          # sécurité : n'écrase rien si tu ajoutes ces colonnes un jour
    Annonce.proprietaire_id = property(lambda self: self.user_id)
    Annonce.statut = property(_get_statut, _set_statut)
    Annonce.vendue = property(_get_vendue, _set_vendue)
    Annonce.latitude = _coord('latitude')
    Annonce.longitude = _coord('longitude')