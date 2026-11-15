"""
routes_live_streaming.py
--------------------------------
Blueprint Flask exposant les routes du module Live Streaming de FaceNet.

Intégration dans app.py :

    from routes_live_streaming import live_bp
    app.register_blueprint(live_bp)

Hypothèses (à adapter si votre projet diffère) :
- `db` est l'instance SQLAlchemy partagée (extensions.py)
- L'authentification utilise Flask-Login (`current_user`, `login_required`)
- Le modèle `User` possède un champ `role` optionnel utilisé pour distinguer
  moderator/vip ; à défaut, le rôle "host" est déduit de `stream.user_id == current_user.id`
"""

from datetime import datetime

from flask import Blueprint, jsonify, render_template, request
from flask_login import current_user, login_required

from extensions import db
from models_live_streaming import ChatMessage, LiveStream, StreamStat, generate_stream_key

live_bp = Blueprint("live_streaming", __name__, url_prefix="")


# ---------------------------------------------------------------------------
# Fonctions utilitaires
# ---------------------------------------------------------------------------

def _get_or_create_active_stream_for_user(user_id):
    """Retourne le stream 'live' ou 'offline' le plus récent de l'utilisateur, ou en crée un."""
    stream = (
        LiveStream.query.filter_by(user_id=user_id)
        .filter(LiveStream.statut.in_(["offline", "live"]))
        .order_by(LiveStream.created_at.desc())
        .first()
    )
    if stream is None:
        stream = LiveStream(
            titre=f"Live de {getattr(current_user, 'username', 'utilisateur')}",
            user_id=user_id,
            statut="offline",
        )
        db.session.add(stream)
        db.session.commit()
    return stream


def _resolve_user_role(stream: LiveStream, user) -> str:
    """Détermine le rôle affiché dans le chat pour un utilisateur donné sur un stream donné."""
    if user.id == stream.user_id:
        return "host"
    role = getattr(user, "role", None)
    if role in ("moderator", "vip"):
        return role
    return "user"


# ---------------------------------------------------------------------------
# Vue principale
# ---------------------------------------------------------------------------

@live_bp.route("/live", methods=["GET"])
@login_required
def live_page():
    """Affiche la page live_streaming.html.

    Si l'utilisateur possède déjà un live actif, l'ID est transmis au
    template afin que le frontend se resynchronise automatiquement.
    """
    active_stream = LiveStream.query.filter_by(user_id=current_user.id, statut="live").first()
    return render_template(
        "live_streaming.html",
        active_stream_id=active_stream.id if active_stream else None,
    )


@live_bp.route("/live/<int:stream_id>", methods=["GET"])
def watch_stream(stream_id):
    """Affiche la page pour un spectateur regardant un live existant."""
    stream = LiveStream.query.get_or_404(stream_id)
    return render_template("live_streaming.html", active_stream_id=stream.id, is_viewer=True)


# ---------------------------------------------------------------------------
# Démarrage / arrêt du direct
# ---------------------------------------------------------------------------

@live_bp.route("/api/stream/start", methods=["POST"])
@login_required
def stream_start():
    data = request.get_json(silent=True) or {}
    titre = (data.get("titre") or "").strip()
    description = (data.get("description") or "").strip()

    stream = _get_or_create_active_stream_for_user(current_user.id)

    if stream.statut == "live":
        return jsonify({"success": False, "error": "Un live est déjà en cours."}), 409

    stream.titre = titre or stream.titre or "Live sans titre"
    stream.description = description or stream.description
    stream.statut = "live"
    stream.viewer_count = 0
    stream.like_count = 0
    stream.started_at = datetime.utcnow()
    stream.ended_at = None
    if not stream.stream_key:
        stream.stream_key = generate_stream_key()

    db.session.commit()

    return jsonify({"success": True, "stream": stream.to_dict()}), 200


@live_bp.route("/api/stream/stop", methods=["POST"])
@login_required
def stream_stop():
    data = request.get_json(silent=True) or {}
    stream_id = data.get("stream_id")

    query = LiveStream.query.filter_by(user_id=current_user.id, statut="live")
    stream = query.filter_by(id=stream_id).first() if stream_id else query.first()

    if stream is None:
        return jsonify({"success": False, "error": "Aucun live actif trouvé."}), 404

    stream.statut = "ended"
    stream.ended_at = datetime.utcnow()
    db.session.commit()

    return jsonify({"success": True, "stream": stream.to_dict()}), 200


@live_bp.route("/api/stream/<int:stream_id>/status", methods=["GET"])
def stream_status(stream_id):
    stream = LiveStream.query.get_or_404(stream_id)
    return jsonify({"success": True, "stream": stream.to_dict()}), 200


# ---------------------------------------------------------------------------
# Chat en direct
# ---------------------------------------------------------------------------

@live_bp.route("/api/stream/chat/send", methods=["POST"])
@login_required
def chat_send():
    data = request.get_json(silent=True) or {}
    stream_id = data.get("stream_id")
    message = (data.get("message") or "").strip()

    if not stream_id or not message:
        return jsonify({"success": False, "error": "stream_id et message sont requis."}), 400
    if len(message) > 500:
        return jsonify({"success": False, "error": "Message trop long (500 caractères max)."}), 400

    stream = LiveStream.query.get_or_404(stream_id)
    role = _resolve_user_role(stream, current_user)

    chat_message = ChatMessage(
        stream_id=stream.id,
        user_id=current_user.id,
        message=message,
        user_role=role,
    )
    db.session.add(chat_message)
    db.session.commit()

    return jsonify({"success": True, "message": chat_message.to_dict()}), 201


@live_bp.route("/api/stream/chat/messages", methods=["GET"])
def chat_messages():
    stream_id = request.args.get("stream_id", type=int)
    after_id = request.args.get("after_id", type=int, default=0)
    limit = min(request.args.get("limit", type=int, default=50), 100)

    if not stream_id:
        return jsonify({"success": False, "error": "stream_id est requis."}), 400

    query = ChatMessage.query.filter_by(stream_id=stream_id)
    if after_id:
        query = query.filter(ChatMessage.id > after_id)

    messages = query.order_by(ChatMessage.created_at.asc()).limit(limit).all()

    return jsonify({"success": True, "messages": [m.to_dict() for m in messages]}), 200


# ---------------------------------------------------------------------------
# Likes
# ---------------------------------------------------------------------------

@live_bp.route("/api/stream/like", methods=["POST"])
@login_required
def stream_like():
    data = request.get_json(silent=True) or {}
    stream_id = data.get("stream_id")

    if not stream_id:
        return jsonify({"success": False, "error": "stream_id est requis."}), 400

    stream = LiveStream.query.get_or_404(stream_id)
    stream.like_count = (stream.like_count or 0) + 1
    db.session.commit()

    return jsonify({"success": True, "like_count": stream.like_count}), 200


# ---------------------------------------------------------------------------
# Statistiques du flux
# ---------------------------------------------------------------------------

@live_bp.route("/api/stream/stats", methods=["POST"])
@login_required
def stream_stats_push():
    """Reçoit une mise à jour de métriques (appelée périodiquement par le frontend)."""
    data = request.get_json(silent=True) or {}
    stream_id = data.get("stream_id")
    bitrate = data.get("bitrate")
    fps = data.get("fps")
    viewer_count = data.get("viewer_count")

    if not stream_id:
        return jsonify({"success": False, "error": "stream_id est requis."}), 400

    stream = LiveStream.query.get_or_404(stream_id)

    if viewer_count is not None:
        stream.viewer_count = max(0, int(viewer_count))

    last_total = stream.stats.order_by(StreamStat.timestamp.desc()).first()
    total_views = (last_total.total_views if last_total else 0)
    if viewer_count is not None and int(viewer_count) > total_views:
        total_views = int(viewer_count)

    stat = StreamStat(
        stream_id=stream.id,
        bitrate=int(bitrate) if bitrate is not None else None,
        fps=int(fps) if fps is not None else None,
        total_views=total_views,
    )
    db.session.add(stat)
    db.session.commit()

    return jsonify({"success": True, "stat": stat.to_dict(), "stream": stream.to_dict()}), 201


@live_bp.route("/api/stream/<int:stream_id>/stats/latest", methods=["GET"])
def stream_stats_latest(stream_id):
    stream = LiveStream.query.get_or_404(stream_id)
    stat = stream.stats.order_by(StreamStat.timestamp.desc()).first()
    return jsonify({
        "success": True,
        "stream": stream.to_dict(),
        "stat": stat.to_dict() if stat else None,
    }), 200