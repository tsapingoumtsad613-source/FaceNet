"""
listeners.py — Écouteurs connectés au bus d'événements (events.py).

Ce module traduit un événement métier générique en appel au service
de notification, exécuté de façon ASYNCHRONE (voir tasks.py) pour ne
JAMAIS bloquer la requête HTTP qui a déclenché l'action.

⚠️ Ce module doit être importé UNE FOIS au démarrage de l'app pour que
`@activity_occurred.connect` enregistre bien l'écouteur (voir __init__.py).
"""
from .events import activity_occurred
from .models import TargetType
from .tasks import enqueue_notification


def _resolve_target(target):
    """Déduit (target_type, target_id, recipient_id par défaut) depuis
    l'objet métier passé par le contrôleur.

    Adapte cette fonction à tes vrais modèles applicatifs (Post,
    Comment, User, Message...). Elle est volontairement isolée ici
    pour rester le SEUL endroit à modifier si tu ajoutes un nouveau
    type de cible.
    """
    # Import différé pour éviter les imports circulaires avec les
    # modèles métier de ton app principale.
    from .models_app import Post, Comment, User, Message  # noqa

    if isinstance(target, Post):
        return TargetType.POST, target.id, target.author_id
    if isinstance(target, Comment):
        return TargetType.COMMENT, target.id, target.author_id
    if isinstance(target, User):
        return TargetType.USER, target.id, target.id
    if isinstance(target, Message):
        return TargetType.MESSAGE, target.id, target.recipient_id

    raise ValueError(f"Type de cible non supporté pour une notification : {type(target)}")


@activity_occurred.connect
def on_activity(sender, verb, actor_id, target, recipient_id, extra_data):
    """Écouteur unique : reçoit TOUS les événements d'activité de la
    plateforme. Ne fait aucun traitement lourd ni écriture en base
    ici — on délègue immédiatement à la file d'attente asynchrone.
    """
    target_type, target_id, default_recipient_id = _resolve_target(target)
    final_recipient_id = recipient_id or default_recipient_id

    enqueue_notification(
        recipient_id=final_recipient_id,
        actor_id=actor_id,
        verb=verb,
        target_type=target_type,
        target_id=target_id,
        extra_data=extra_data,
    )