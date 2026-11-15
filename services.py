"""
services.py — Logique métier de création des notifications.

Contient :
  - la règle "on ne se notifie jamais soi-même" ;
  - l'agrégation des notifications répétitives (likes, follows...) ;
  - la construction des URLs de redirection selon le type de cible.
"""
from datetime import datetime, timedelta

from .extensions import db
from .models import Notification

# Fenêtre de temps pendant laquelle on agrège les notifications
# similaires au lieu d'en créer une nouvelle à chaque fois.
AGGREGATION_WINDOW = timedelta(hours=24)

# Verbes concernés par l'agrégation. Les messages ou demandes d'amis,
# eux, doivent rester des notifications individuelles distinctes.
AGGREGABLE_VERBS = {"like", "follow", "verification_badge"}

# Un "builder" d'URL par type de cible — ajouter un type de cible ne
# demande qu'une ligne ici, jamais de toucher aux routes.
REDIRECT_BUILDERS = {
    "post": lambda tid, extra: f"/posts/{tid}",
    "comment": lambda tid, extra: f"/posts/{extra.get('post_id')}#comment-{tid}",
    "user": lambda tid, extra: f"/profile/{tid}",
    "message": lambda tid, extra: f"/messages/{extra.get('conversation_id', tid)}",
    "friend_request": lambda tid, extra: "/friends/requests",
}


class NotificationService:

    @staticmethod
    def build_redirect_url(target_type, target_id, extra_data=None):
        extra_data = extra_data or {}
        builder = REDIRECT_BUILDERS.get(target_type)
        return builder(target_id, extra_data) if builder else "/notifications"

    @classmethod
    def create_notification(cls, recipient_id, actor_id, verb,
                             target_type, target_id, extra_data=None):
        """
        Point d'entrée unique pour créer OU agréger une notification.
        Retourne l'objet Notification (créé ou mis à jour), ou None
        si l'action est ignorée (auto-notification).
        """
        extra_data = extra_data or {}

        # Règle n°1 : on ne se notifie jamais soi-même
        if str(recipient_id) == str(actor_id):
            return None

        if verb in AGGREGABLE_VERBS:
            notif = cls._aggregate_or_create(
                recipient_id, actor_id, verb, target_type, target_id, extra_data
            )
        else:
            notif = cls._create_single(
                recipient_id, actor_id, verb, target_type, target_id, extra_data
            )

        db.session.commit()
        return notif

    @classmethod
    def _aggregate_or_create(cls, recipient_id, actor_id, verb,
                              target_type, target_id, extra_data):
        cutoff = datetime.utcnow() - AGGREGATION_WINDOW

        existing = (
            Notification.query
            .filter_by(
                recipient_id=recipient_id, verb=verb,
                target_type=target_type, target_id=target_id,
                is_read=False,
            )
            .filter(Notification.created_at >= cutoff)
            .order_by(Notification.created_at.desc())
            .first()
        )

        if existing:
            actors = set(existing.aggregated_actor_ids or [])
            if actor_id not in actors:
                actors.add(actor_id)
                existing.aggregated_count += 1
            # On ne garde que les 5 derniers acteurs pour l'affichage
            # des avatars empilés côté front.
            existing.aggregated_actor_ids = list(actors)[-5:]
            existing.is_aggregated = existing.aggregated_count > 1
            existing.actor_id = actor_id  # le plus récent devient l'acteur affiché
            existing.updated_at = datetime.utcnow()
            existing.created_at = datetime.utcnow()  # remonte en tête de flux
            db.session.add(existing)
            return existing

        return cls._create_single(
            recipient_id, actor_id, verb, target_type, target_id, extra_data,
            aggregated_actor_ids=[actor_id],
        )

    @staticmethod
    def _create_single(recipient_id, actor_id, verb, target_type, target_id,
                        extra_data, aggregated_actor_ids=None):
        notif = Notification(
            recipient_id=recipient_id,
            actor_id=actor_id,
            verb=verb,
            target_type=target_type,
            target_id=target_id,
            extra_data=extra_data,
            aggregated_actor_ids=aggregated_actor_ids or [actor_id],
        )
        db.session.add(notif)
        db.session.flush()  # récupère notif.id avant le commit final
        return notif