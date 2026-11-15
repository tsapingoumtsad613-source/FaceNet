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