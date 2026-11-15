"""
events.py — Bus d'événements découplé (Pub/Sub) basé sur Blinker
(la lib de signaux utilisée en interne par Flask).

Principe clé : les contrôleurs n'appellent JAMAIS directement le
service de notification. Ils se contentent d'émettre un événement
métier ("un like a eu lieu"). Cela permet de :
  - découpler totalement la logique métier (liker un post) de la
    logique de notification ;
  - brancher facilement d'autres écouteurs plus tard (emailing,
    analytics, webhooks...) sans toucher aux contrôleurs existants ;
  - tester la logique métier sans se soucier des notifications.
"""
from blinker import Namespace

notifications_signals = Namespace()

# Un signal générique unique, le "verb" étant transporté dans le payload.
# (Alternative : un signal par verbe — plus explicite à l'auto-complétion,
# mais plus verbeux à maintenir. On choisit ici la version générique.)
activity_occurred = notifications_signals.signal("activity-occurred")


def emit_activity(verb, actor, target, recipient_id=None, **extra_data):
    """
    Point d'entrée UNIQUE utilisé par les contrôleurs métier.

    :param verb: str — voir models.NotificationVerb
    :param actor: instance User qui déclenche l'action
    :param target: l'objet cible (Post, Comment, User, Message...) ;
                    utilisé pour déduire target_type/target_id et,
                    si non fourni explicitement, le destinataire.
    :param recipient_id: destinataire explicite (utile quand il n'est
                          pas déductible de `target`, ex: demande d'ami)
    :param extra_data: données libres utiles à l'affichage
                        (ex: excerpt="...", post_id=42)
    """
    activity_occurred.send(
        "facenet",  # sender symbolique, requis par Blinker
        verb=verb,
        actor_id=actor.id,
        target=target,
        recipient_id=recipient_id,
        extra_data=extra_data,
    )