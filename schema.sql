CREATE TABLE IF NOT EXISTS user (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username VARCHAR(80) UNIQUE NOT NULL,
    nom_complet VARCHAR(150),
    email VARCHAR(120) UNIQUE NOT NULL,
    phone VARCHAR(50) UNIQUE,
    password VARCHAR(200) NOT NULL,
    birth_date VARCHAR(20),
    is_pdg BOOLEAN DEFAULT 0,
    is_verified BOOLEAN DEFAULT 0,
    has_badge_bleu BOOLEAN DEFAULT 0,
    forfait_badge VARCHAR(50),
    forfait_actif VARCHAR(50),
    date_expiration_badge DATETIME
);

CREATE TABLE IF NOT EXISTS publication (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contenu TEXT NOT NULL,
    image_nom VARCHAR(200),
    date_pub TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    user_id INTEGER NOT NULL,
    is_boosted_expires_at TEXT DEFAULT NULL,
    FOREIGN KEY (user_id) REFERENCES user (id)
);

CREATE TABLE IF NOT EXISTS certification_request (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    photo_cni VARCHAR(255) NOT NULL,
    statut VARCHAR(50) DEFAULT 'En attente',
    FOREIGN KEY (user_id) REFERENCES user (id)
);

-- =========================================================
--  SCHEMA SQL - Fonctionnalités "Groupe" style Facebook
--  A intégrer / adapter à ton schéma existant (users_facebook.sql)
--  Adapte le type de la clé étrangère vers users.id si besoin
-- =========================================================

-- ---------- Groupes ----------
CREATE TABLE IF NOT EXISTS groups (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,   -- SERIAL en PostgreSQL
    name            VARCHAR(150)  NOT NULL,
    description     TEXT,
    cover_url       VARCHAR(255),
    is_private      BOOLEAN       NOT NULL DEFAULT 0,
    admin_id        INTEGER       NOT NULL,
    date_creation   DATETIME      DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (admin_id) REFERENCES users(id) ON DELETE CASCADE
);

-- ---------- Membres du groupe ----------
CREATE TABLE IF NOT EXISTS group_members (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id        INTEGER NOT NULL,
    user_id         INTEGER NOT NULL,
    role            VARCHAR(20) NOT NULL DEFAULT 'membre',  -- 'membre' | 'admin' | 'moderateur'
    date_adhesion   DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (group_id, user_id),
    FOREIGN KEY (group_id) REFERENCES groups(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id)  REFERENCES users(id)  ON DELETE CASCADE
);

-- ---------- Demandes d'adhésion (groupes privés) ----------
CREATE TABLE IF NOT EXISTS group_join_requests (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id        INTEGER NOT NULL,
    user_id         INTEGER NOT NULL,
    statut          VARCHAR(20) NOT NULL DEFAULT 'en_attente', -- 'en_attente' | 'acceptee' | 'refusee'
    date_demande    DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (group_id) REFERENCES groups(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id)  REFERENCES users(id)  ON DELETE CASCADE
);

-- ---------- Publications du groupe ----------
CREATE TABLE IF NOT EXISTS group_posts (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id        INTEGER NOT NULL,
    auteur_id       INTEGER NOT NULL,
    contenu         TEXT NOT NULL,
    media_url       VARCHAR(255),
    est_epingle     BOOLEAN NOT NULL DEFAULT 0,
    date_pub        DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (group_id)  REFERENCES groups(id) ON DELETE CASCADE,
    FOREIGN KEY (auteur_id) REFERENCES users(id)  ON DELETE CASCADE
);

-- ---------- J'aime sur une publication de groupe ----------
CREATE TABLE IF NOT EXISTS group_post_likes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id         INTEGER NOT NULL,
    user_id         INTEGER NOT NULL,
    date_like       DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (post_id, user_id),
    FOREIGN KEY (post_id) REFERENCES group_posts(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id)        ON DELETE CASCADE
);

-- ---------- Commentaires sur une publication de groupe ----------
CREATE TABLE IF NOT EXISTS group_comments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id         INTEGER NOT NULL,
    auteur_id       INTEGER NOT NULL,
    contenu         TEXT NOT NULL,
    date_com        DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (post_id)   REFERENCES group_posts(id) ON DELETE CASCADE,
    FOREIGN KEY (auteur_id) REFERENCES users(id)       ON DELETE CASCADE
);

-- ---------- Index utiles pour la performance ----------
CREATE INDEX IF NOT EXISTS idx_group_members_group   ON group_members(group_id);
CREATE INDEX IF NOT EXISTS idx_group_members_user    ON group_members(user_id);
CREATE INDEX IF NOT EXISTS idx_group_posts_group     ON group_posts(group_id);
CREATE INDEX IF NOT EXISTS idx_group_comments_post   ON group_comments(post_id);
CREATE INDEX IF NOT EXISTS idx_group_post_likes_post ON group_post_likes(post_id);


-- =========================================================
--  MODELES SQLAlchemy correspondants (à coller dans models.py)
-- =========================================================
/*
class Group(db.Model):
    __tablename__ = 'groups'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text)
    cover_url = db.Column(db.String(255))
    is_private = db.Column(db.Boolean, default=False)
    admin_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    members = db.relationship('GroupMember', backref='group', cascade='all, delete-orphan')
    posts = db.relationship('GroupPost', backref='group', cascade='all, delete-orphan')

    @property
    def members_count(self):
        return len(self.members)


class GroupMember(db.Model):
    __tablename__ = 'group_members'
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    role = db.Column(db.String(20), default='membre')
    date_adhesion = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User')


class GroupJoinRequest(db.Model):
    __tablename__ = 'group_join_requests'
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    statut = db.Column(db.String(20), default='en_attente')
    date_demande = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship('User')


class GroupPost(db.Model):
    __tablename__ = 'group_posts'
    id = db.Column(db.Integer, primary_key=True)
    group_id = db.Column(db.Integer, db.ForeignKey('groups.id'), nullable=False)
    auteur_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    contenu = db.Column(db.Text, nullable=False)
    media_url = db.Column(db.String(255))
    est_epingle = db.Column(db.Boolean, default=False)
    date_pub = db.Column(db.DateTime, default=datetime.utcnow)
    auteur_rel = db.relationship('User')
    comments = db.relationship('GroupComment', backref='post', cascade='all, delete-orphan')
    likes = db.relationship('GroupPostLike', backref='post', cascade='all, delete-orphan')

    @property
    def likes_count(self):
        return len(self.likes)

    @property
    def comments_count(self):
        return len(self.comments)


class GroupPostLike(db.Model):
    __tablename__ = 'group_post_likes'
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('group_posts.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    date_like = db.Column(db.DateTime, default=datetime.utcnow)


class GroupComment(db.Model):
    __tablename__ = 'group_comments'
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('group_posts.id'), nullable=False)
    auteur_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    contenu = db.Column(db.Text, nullable=False)
    date_com = db.Column(db.DateTime, default=datetime.utcnow)
    auteur_rel = db.relationship('User')
*/
 