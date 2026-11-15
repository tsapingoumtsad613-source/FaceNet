"""
__init__.py — Câblage du module notifications dans l'application Flask.

Utilisation dans ton app factory principale :

    from facenet_notifications import init_notifications

    def create_app():
        app = Flask(__name__)
        ...
        init_notifications(app)
        return app
"""


def init_notifications(app):
    from .routes import notifications_bp
    from . import listeners  # noqa: F401 — connecte les écouteurs Blinker
    from .tasks import CELERY_AVAILABLE

    app.register_blueprint(notifications_bp)

    if not CELERY_AVAILABLE:
        from .tasks import start_notification_worker
        start_notification_worker(app)


# ---------------------------------------------------------------------
# EXEMPLE D'INTÉGRATION dans un contrôleur métier existant.
# Le contrôleur ne connaît RIEN du système de notification : il émet
# juste un événement, un point c'est tout.
# ---------------------------------------------------------------------
#
# from facenet_notifications.events import emit_activity
# from facenet_notifications.models import NotificationVerb
#
# @posts_bp.route("/<int:post_id>/like", methods=["POST"])
# @login_required
# def like_post(post_id):
#     post = Post.query.get_or_404(post_id)
#     # ... logique de like existante (créer la ligne Like, etc.) ...
#
#     emit_activity(
#         verb=NotificationVerb.LIKE,
#         actor=current_user,
#         target=post,
#     )
#     return jsonify({"status": "ok"})
#
# @comments_bp.route("/<int:comment_id>/reply", methods=["POST"])
# @login_required
# def reply_to_comment(comment_id):
#     parent = Comment.query.get_or_404(comment_id)
#     reply = Comment(post_id=parent.post_id, parent_id=parent.id, ...)
#     db.session.add(reply)
#     db.session.commit()
#
#     emit_activity(
#         verb=NotificationVerb.REPLY,
#         actor=current_user,
#         target=parent,  # notifie l'auteur du commentaire parent
#         extra_data={"excerpt": reply.content[:80], "post_id": parent.post_id},
#     )
#     return jsonify({"status": "ok"})