# -*- coding: utf-8 -*-
"""
Notifications « push » FaceNet : la notification arrive sur le téléphone même
quand l'application est fermée (bannière en haut de l'écran).

Fonctionnement :
  - Dès qu'une Notification est enregistrée en base (n'importe où dans routes.py),
    un écouteur SQLAlchemy envoie un push à tous les appareils abonnés du destinataire.
  - Aucun code existant n'est modifié : l'envoi est branché sur le modèle Notification.
  - Si pywebpush ou les clés VAPID manquent, rien ne se passe (aucune erreur, rien ne casse).

Installation : pip install pywebpush  puis  python generer_cles_push.py
"""
import os
import json
import threading

from flask import current_app
from sqlalchemy import event
from sqlalchemy.orm import Session, object_session

from extensions import db
from models import Notification, PushSubscription, User

_DOSSIER = os.path.dirname(os.path.abspath(__file__))
CHEMIN_CLE_PRIVEE = os.path.join(_DOSSIER, 'vapid_private.pem')
CHEMIN_CLE_PUBLIQUE = os.path.join(_DOSSIER, 'vapid_public.txt')
VAPID_CONTACT = os.environ.get('VAPID_CONTACT', 'mailto:contact@facenet.local')


def cle_publique():
    """Clé publique VAPID (base64url) pour le navigateur, ou None si non configurée."""
    try:
        with open(CHEMIN_CLE_PUBLIQUE, 'r', encoding='utf-8') as f:
            return f.read().strip() or None
    except Exception:
        return os.environ.get('VAPID_PUBLIC_KEY') or None


def push_disponible():
    try:
        import pywebpush  # noqa: F401
    except Exception:
        return False
    return bool(cle_publique()) and os.path.exists(CHEMIN_CLE_PRIVEE)


_TEXTES = {
    'like': "a aimé votre publication",
    'comment': "a commenté votre publication",
    'reply': "a répondu à votre commentaire",
    'mention': "vous a mentionné",
    'message': "vous a envoyé un message",
    'friend_request': "vous a envoyé une invitation",
    'friend_accept': "a accepté votre invitation",
    'follow': "a commencé à vous suivre",
}


def _construire_charge(vals):
    destinataire_id, acteur_id, verb, type_, message, notif_id = vals
    acteur = db.session.get(User, acteur_id) if acteur_id else None
    nom = (getattr(acteur, 'nom_complet', None) or getattr(acteur, 'username', None) or 'FaceNet')
    cle = (type_ or verb or '').lower()
    if message and str(message).strip():
        corps = str(message).strip()
        if acteur and nom not in corps and cle in _TEXTES:
            corps = f"{nom} {_TEXTES[cle]}"
    elif cle in _TEXTES:
        corps = f"{nom} {_TEXTES[cle]}"
    else:
        corps = "Vous avez une nouvelle notification"
    avatar = getattr(acteur, 'avatar', None) or 'default_avatar.png'
    return {
        'title': 'FaceNet',
        'body': corps[:180],
        'icon': '/static/uploads/' + avatar,
        'url': '/notifications',
        'tag': 'facenet-notif-' + str(notif_id),
    }


def _envoyer(app, vals):
    if not push_disponible():
        return
    from pywebpush import webpush, WebPushException
    with app.app_context():
        try:
            abonnements = PushSubscription.query.filter_by(user_id=vals[0]).all()
            if not abonnements:
                return
            charge = json.dumps(_construire_charge(vals))
            for ab in abonnements:
                try:
                    webpush(
                        subscription_info={'endpoint': ab.endpoint,
                                           'keys': {'p256dh': ab.p256dh, 'auth': ab.auth}},
                        data=charge,
                        vapid_private_key=CHEMIN_CLE_PRIVEE,
                        vapid_claims={'sub': VAPID_CONTACT},
                        ttl=86400,
                    )
                except WebPushException as e:
                    code = getattr(getattr(e, 'response', None), 'status_code', None)
                    if code in (404, 410):  # abonnement expiré : on le retire
                        db.session.delete(ab)
                        db.session.commit()
                except Exception:
                    pass
        except Exception:
            try:
                db.session.rollback()
            except Exception:
                pass
        finally:
            try:
                db.session.remove()
            except Exception:
                pass


@event.listens_for(Notification, 'after_insert')
def _noter_notification(mapper, connection, target):
    """On mémorise des valeurs simples ; l'envoi se fait seulement après le commit réussi."""
    try:
        sess = object_session(target)
        if sess is not None:
            sess.info.setdefault('_push_en_attente', []).append(
                (target.recipient_id, target.actor_id, target.verb, target.type, target.message, target.id))
    except Exception:
        pass


@event.listens_for(Session, 'after_commit')
def _apres_commit(session):
    try:
        en_attente = session.info.pop('_push_en_attente', None)
        if not en_attente:
            return
        app = current_app._get_current_object()
        for vals in en_attente:
            threading.Thread(target=_envoyer, args=(app, vals), daemon=True).start()
    except Exception:
        pass


@event.listens_for(Session, 'after_rollback')
def _apres_rollback(session):
    try:
        session.info.pop('_push_en_attente', None)
    except Exception:
        pass
