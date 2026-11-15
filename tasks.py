"""
tasks.py — Exécution ASYNCHRONE de la création de notification
(Celery + Redis en production, worker-thread en secours) puis
diffusion temps réel via Socket.IO.

Objectif : la route HTTP qui déclenche `emit_activity(...)` répond en
quelques millisecondes, sans jamais attendre l'écriture en base ni
l'émission WebSocket.
"""
import logging

logger = logging.getLogger(__name__)

try:
    from celery import shared_task
    CELERY_AVAILABLE = True
except ImportError:
    CELERY_AVAILABLE = False


def _process_notification(recipient_id, actor_id, verb, target_type,
                           target_id, extra_data):
    """Traitement réel, exécuté hors du thread de la requête HTTP.
    Import différé pour éviter les imports circulaires entre
    services / app Flask / worker Celery.
    """
    from .services import NotificationService
    from .realtime import push_notification_realtime

    notif = NotificationService.create_notification(
        recipient_id=recipient_id, actor_id=actor_id, verb=verb,
        target_type=target_type, target_id=target_id, extra_data=extra_data,
    )
    if notif is not None:
        push_notification_realtime(notif)
    return notif.id if notif else None


if CELERY_AVAILABLE:
    # --- Mode production recommandé : Celery + Redis ---
    @shared_task(name="notifications.process", bind=True, max_retries=3)
    def process_notification_task(self, recipient_id, actor_id, verb,
                                   target_type, target_id, extra_data):
        try:
            return _process_notification(
                recipient_id, actor_id, verb, target_type, target_id, extra_data
            )
        except Exception as exc:
            logger.exception("Échec du traitement de la notification")
            raise self.retry(exc=exc, countdown=5)

    def enqueue_notification(**kwargs):
        """Empile la tâche dans Redis via Celery — retour immédiat,
        aucun impact sur le temps de réponse HTTP."""
        process_notification_task.delay(**kwargs)

else:
    # --- Fallback sans Redis/Celery : file en mémoire + thread worker ---
    # Pratique en développement local ou petit déploiement mono-serveur.
    # ⚠️ En production à forte charge / multi-instances, préférer Celery
    # + Redis (la file en mémoire ne survit pas à un redémarrage et
    # n'est pas partagée entre plusieurs processus/serveurs).
    import queue
    import threading

    _task_queue = queue.Queue()
    _worker_started = False

    def _worker_loop(app):
        while True:
            kwargs = _task_queue.get()
            try:
                with app.app_context():
                    _process_notification(**kwargs)
            except Exception:
                logger.exception("Échec du worker de notification")
            finally:
                _task_queue.task_done()

    def start_notification_worker(app):
        """À appeler UNE FOIS au démarrage de l'app (voir __init__.py)."""
        global _worker_started
        if _worker_started:
            return
        thread = threading.Thread(target=_worker_loop, args=(app,), daemon=True)
        thread.start()
        _worker_started = True

    def enqueue_notification(**kwargs):
        """Empile la tâche en mémoire — traitée par le thread worker,
        hors du thread de la requête HTTP."""
        _task_queue.put(kwargs)