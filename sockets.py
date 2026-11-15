# sockets.py
# ─────────────────────────────────────────────────────────────
# Signalisation WebRTC réelle entre 2 utilisateurs via SocketIO.
# Gère uniquement les événements d'appel audio/vidéo.
# ─────────────────────────────────────────────────────────────
from flask_socketio import SocketIO, join_room
from flask import request

# ══════════════════════════════════════════════════════════════════
# CORRECTION : retiré async_mode="eventlet"
# Raison : eventlet est incompatible avec app.run() de ton app.py.
# SocketIO utilise maintenant son mode threading par défaut,
# qui fonctionne parfaitement.
# ══════════════════════════════════════════════════════════════════
socketio = SocketIO(cors_allowed_origins="*")

# user_id → socket_id  (qui est connecté en ce moment)
connected_users = {}


@socketio.on('connect')
def _on_connect():
    print(f"🔌 Socket connecté : {request.sid}")


@socketio.on('disconnect')
def _on_disconnect():
    for uid, sid in list(connected_users.items()):
        if sid == request.sid:
            del connected_users[uid]
            print(f"❌ Socket déconnecté : user {uid}")
            break


@socketio.on('register')
def _on_register(data):
    uid = data.get('user_id')
    if uid:
        connected_users[int(uid)] = request.sid
        join_room(f"user_{uid}")
        print(f"✅ User {uid} enregistré")


@socketio.on('call:start')
def _on_call_start(data):
    caller_id = int(data.get('caller_id'))
    peer_id = int(data.get('peer_id'))
    if peer_id not in connected_users:
        socketio.emit('call:unavailable', {'reason': 'offline'}, to=request.sid)
        return
    socketio.emit('call:incoming', {
        'caller_id': caller_id,
        'caller_name': data.get('caller_name', 'Quelqu\'un'),
        'caller_avatar': data.get('caller_avatar', ''),
        'call_type': data.get('call_type', 'audio')
    }, to=f"user_{peer_id}")
    print(f"📞 Appel {data.get('call_type')} de {caller_id} vers {peer_id}")


@socketio.on('call:accept')
def _on_call_accept(data):
    caller_id = int(data.get('caller_id'))
    socketio.emit('call:accepted', {'by': int(data.get('by'))}, to=f"user_{caller_id}")
    print(f"✅ Appel accepté par {data.get('by')}")


@socketio.on('call:reject')
def _on_call_reject(data):
    caller_id = int(data.get('caller_id'))
    socketio.emit('call:rejected', {'by': int(data.get('by'))}, to=f"user_{caller_id}")
    print(f"❌ Appel refusé par {data.get('by')}")


@socketio.on('call:hangup')
def _on_call_hangup(data):
    peer_id = int(data.get('peer_id'))
    socketio.emit('call:hangup', {'by': int(data.get('by'))}, to=f"user_{peer_id}")
    print(f"📵 Raccroché par {data.get('by')}")


@socketio.on('webrtc:offer')
def _on_offer(data):
    peer_id = int(data.get('peer_id'))
    socketio.emit('webrtc:offer', {
        'sdp': data.get('sdp'), 'from': int(data.get('from'))
    }, to=f"user_{peer_id}")


@socketio.on('webrtc:answer')
def _on_answer(data):
    peer_id = int(data.get('peer_id'))
    socketio.emit('webrtc:answer', {
        'sdp': data.get('sdp'), 'from': int(data.get('from'))
    }, to=f"user_{peer_id}")


@socketio.on('webrtc:ice')
def _on_ice(data):
    peer_id = int(data.get('peer_id'))
    socketio.emit('webrtc:ice', {
        'candidate': data.get('candidate'), 'from': int(data.get('from'))
    }, to=f"user_{peer_id}")


def init_socketio(app):
    """À appeler une seule fois depuis app.py."""
    # ══════════════════════════════════════════════════════════════════
    # CORRECTION : retiré async_mode="eventlet" ici aussi.
    # ══════════════════════════════════════════════════════════════════
    socketio.init_app(app, cors_allowed_origins="*")