"""
realtime.py — Diffusion temps réel des notifications via Flask-SocketIO.

Chaque utilisateur connecté rejoint une "room" personnelle nommée
`user_<id>` (voir socketio_events.py). On y pousse la notification
dès sa création en base — l'utilisateur la voit apparaître sans
recharger la page.
"""
from .extensions import socketio


def push_notification_realtime(notification):
    """Émet l'événement 'new_notification' uniquement au destinataire
    concerné (jamais un broadcast global)."""
    room = f"user_{notification.recipient_id}"
    socketio.emit(
        "new_notification",
        notification.to_dict(),
        room=room,
        namespace="/notifications",
    )