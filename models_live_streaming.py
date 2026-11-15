"""
models_live_streaming.py
--------------------------------
Modèles de données pour le module Live Streaming de FaceNet.

Ce fichier est prévu pour être fusionné dans le models.py principal du
projet FaceNet. Il suppose qu'une instance SQLAlchemy `db` existe déjà
(généralement créée dans extensions.py ou app.py via `db = SQLAlchemy()`)
et qu'un modèle `User` existe déjà avec une clé primaire entière `id`.

Si votre projet utilise déjà `from extensions import db`, remplacez
l'import ci-dessous en conséquence.
"""

import secrets
import string
from datetime import datetime

from extensions import db  # Adaptez cet import à la structure réelle du projet


def generate_stream_key(length: int = 24) -> str:
    """Génère une clé de stream aléatoire et sûre (utilisée pour l'ingestion RTMP/WebRTC)."""
    alphabet = string.ascii_letters + string.digits
    return "fnet_" + "".join(secrets.choice(alphabet) for _ in range(length))


class LiveStream(db.Model):
    __tablename__ = "live_stream"

    id = db.Column(db.Integer, primary_key=True)
    titre = db.Column(db.String(150), nullable=False, default="Live sans titre")
    description = db.Column(db.Text, nullable=True)

    # offline | live | ended
    statut = db.Column(db.String(20), nullable=False, default="offline", index=True)

    stream_key = db.Column(db.String(64), unique=True, nullable=False, default=generate_stream_key)

    viewer_count = db.Column(db.Integer, nullable=False, default=0)
    like_count = db.Column(db.Integer, nullable=False, default=0)

    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)

    started_at = db.Column(db.DateTime, nullable=True)
    ended_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    # Relations
    messages = db.relationship(
        "ChatMessage",
        backref="stream",
        lazy="dynamic",
        cascade="all, delete-orphan",
        order_by="ChatMessage.created_at",
    )
    stats = db.relationship(
        "StreamStat",
        backref="stream",
        lazy="dynamic",
        cascade="all, delete-orphan",
        order_by="StreamStat.timestamp",
    )
    # host : adaptez `backref` si `User` a déjà un attribut `live_streams`
    host = db.relationship("User", foreign_keys=[user_id])

    def to_dict(self, include_host=True):
        data = {
            "id": self.id,
            "titre": self.titre,
            "description": self.description,
            "statut": self.statut,
            "viewer_count": self.viewer_count,
            "like_count": self.like_count,
            "user_id": self.user_id,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "created_at": self.created_at.isoformat(),
        }
        if include_host and self.host is not None:
            data["host"] = {
                "id": self.host.id,
                "nom": getattr(self.host, "nom_complet", None) or getattr(self.host, "username", "Hôte"),
                "photo": getattr(self.host, "photo_profil", None),
            }
        return data

    def __repr__(self):
        return f"<LiveStream id={self.id} statut={self.statut} user_id={self.user_id}>"


class ChatMessage(db.Model):
    __tablename__ = "stream_chat_message"

    id = db.Column(db.Integer, primary_key=True)
    stream_id = db.Column(db.Integer, db.ForeignKey("live_stream.id"), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)

    message = db.Column(db.String(500), nullable=False)

    # host | moderator | vip | user
    user_role = db.Column(db.String(20), nullable=False, default="user")

    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    author = db.relationship("User", foreign_keys=[user_id])

    def to_dict(self):
        return {
            "id": self.id,
            "stream_id": self.stream_id,
            "user_id": self.user_id,
            "auteur": (
                getattr(self.author, "nom_complet", None)
                or getattr(self.author, "username", "Utilisateur")
                if self.author
                else "Utilisateur"
            ),
            "avatar": getattr(self.author, "photo_profil", None) if self.author else None,
            "message": self.message,
            "user_role": self.user_role,
            "created_at": self.created_at.isoformat(),
        }

    def __repr__(self):
        return f"<ChatMessage id={self.id} stream_id={self.stream_id} role={self.user_role}>"


class StreamStat(db.Model):
    __tablename__ = "stream_stat"

    id = db.Column(db.Integer, primary_key=True)
    stream_id = db.Column(db.Integer, db.ForeignKey("live_stream.id"), nullable=False, index=True)

    bitrate = db.Column(db.Integer, nullable=True)  # en kbps
    fps = db.Column(db.Integer, nullable=True)
    total_views = db.Column(db.Integer, nullable=False, default=0)

    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "stream_id": self.stream_id,
            "bitrate": self.bitrate,
            "fps": self.fps,
            "total_views": self.total_views,
            "timestamp": self.timestamp.isoformat(),
        }

    def __repr__(self):
        return f"<StreamStat stream_id={self.stream_id} fps={self.fps} bitrate={self.bitrate}>"