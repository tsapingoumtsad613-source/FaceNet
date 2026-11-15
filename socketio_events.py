"""
socketio_events.py — Gestion de la connexion Socket.IO côté serveur.

Chaque utilisateur authentifié rejoint sa room personnelle à la
connexion. C'est ce qui permet à realtime.py de cibler précisément
le bon destinataire sans jamais diffuser en broadcast.
"""
from flask_socketio import Namespace, join_room, disconnect
from flask_login import current_user  # remplace par ton système d'auth si différent

from .extensions import socketio


class NotificationsNamespace(Namespace):
    def on_connect(self):
        if not current_user.is_authenticated:
            disconnect()
            return
        join_room(f"user_{current_user.id}")

    def on_disconnect(self):
        pass  # Flask-SocketIO retire automatiquement le client des rooms


socketio.on_namespace(NotificationsNamespace("/notifications"))