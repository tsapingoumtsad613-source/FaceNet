"""
routes.py — Endpoints REST pour les notifications.
"""
from datetime import datetime

from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user

from .extensions import db
from .models import Notification
from .services import NotificationService

notifications_bp = Blueprint(
    "notifications", __name__, url_prefix="/api/notifications"
)


@notifications_bp.route("", methods=["GET"])
@login_required
def list_notifications():
    """Liste paginée des notifications du destinataire connecté,
    avec les données de l'acteur (nom, avatar) et l'URL de redirection."""
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 20, type=int), 50)

    pagination = (
        Notification.query
        .filter_by(recipient_id=current_user.id)
        .order_by(Notification.created_at.desc())
        .paginate(page=page, per_page=per_page, error_out=False)
    )

    items = []
    for n in pagination.items:
        data = n.to_dict()
        data["redirect_url"] = NotificationService.build_redirect_url(
            n.target_type, n.target_id, n.extra_data
        )
        items.append(data)

    return jsonify({
        "items": items,
        "page": pagination.page,
        "pages": pagination.pages,
        "total": pagination.total,
        "has_next": pagination.has_next,
        "unread_count": Notification.query.filter_by(
            recipient_id=current_user.id, is_read=False
        ).count(),
    })


@notifications_bp.route("/<int:notification_id>/read", methods=["PATCH"])
@login_required
def mark_as_read(notification_id):
    """Marque une notification précise comme lue."""
    notif = Notification.query.filter_by(
        id=notification_id, recipient_id=current_user.id
    ).first_or_404()

    if not notif.is_read:
        notif.is_read = True
        notif.read_at = datetime.utcnow()
        db.session.commit()

    return jsonify(notif.to_dict())


@notifications_bp.route("/read-all", methods=["PATCH"])
@login_required
def mark_all_as_read():
    """Marque toutes les notifications non lues du user comme lues."""
    updated = (
        Notification.query
        .filter_by(recipient_id=current_user.id, is_read=False)
        .update({"is_read": True, "read_at": datetime.utcnow()})
    )
    db.session.commit()
    return jsonify({"updated": updated})