"""
notifications_service.py — Système central de notifications de FaceNet.

UNE seule fonction à appeler partout :

    notifier(destinataire_id, "like", acteur=current_user, cible=("post", pub.id), pub_id=pub.id)

• Elle crée la ligne dans la table `notifications` (modèle déjà existant dans models.py,
  aucune migration nécessaire : le lien et les infos annexes vont dans `extra_data`).
• Elle ne fait PAS de commit : l'appelant commit comme d'habitude.
• Elle ne lève JAMAIS d'exception : en cas de souci, elle renvoie None et l'action
  principale (like, commentaire, paiement…) continue normalement.

Ajouter un nouveau type de notification = ajouter UNE entrée dans CATALOGUE.
"""
import re
from datetime import datetime

from flask import url_for

from models import db, Notification, User

SUPPORT_ID = 1  # compte « FaceNet Support »

# ──────────────────────────────────────────────────────────────────────────
#  CATALOGUE DES TYPES
#   message      : texte ({nom} = acteur, + toute variable passée à notifier)
#   icone        : icône Font Awesome affichée sur la pastille
#   support      : True → affichée comme message officiel « FaceNet Support »
#   groupe       : (like) regroupe « X et N autres personnes … »
#   unique_non_lu: pas de doublon tant que la précédente n'est pas lue
# ──────────────────────────────────────────────────────────────────────────
CATALOGUE = {
    # ── Réactions ─────────────────────────────────────────────────────────
    "like": {
        "message": "{nom} a aimé votre publication.",
        "message_groupe": "{nom} et {autres} {autres_mot} ont aimé votre publication.",
        "icone": "fa-heart", "groupe": True,
    },
    "comment": {"message": "{nom} a commenté votre publication.", "icone": "fa-comment"},
    "reply": {"message": "{nom} a répondu à votre commentaire.", "icone": "fa-reply"},
    "share": {"message": "{nom} a partagé votre publication.", "icone": "fa-share"},
    "repost": {"message": "{nom} a republié votre publication.", "icone": "fa-retweet"},
    "mention": {"message": "{nom} vous a mentionné dans un commentaire.", "icone": "fa-at"},
    # ── Relations ─────────────────────────────────────────────────────────
    "friend_request": {
        "message": "{nom} vous a envoyé une demande d'amitié.",
        "icone": "fa-user-plus", "unique_non_lu": True,
    },
    "friend_accept": {"message": "{nom} a accepté votre invitation.", "icone": "fa-user-check"},
    "follow": {"message": "{nom} s'est abonné à votre profil.", "icone": "fa-user-plus", "unique_non_lu": True},
    # ── Contrôle parental par invitation (controle_parental_invitations.py) ──
    "parental_invite": {
        "message": "{nom} vous invite à activer le contrôle parental sur votre profil.",
        "icone": "fa-lock", "unique_non_lu": True,
    },
    "parental_reponse": {"message": "{nom} a {reponse} votre invitation de contrôle parental.", "icone": "fa-check-circle"},
    "parental_demande": {
        "message": "{nom} demande l'autorisation d'accéder à son profil.",
        "icone": "fa-bell", "unique_non_lu": True,
    },
    "parental_blocage": {"message": "{nom} a programmé le blocage de votre compte.", "icone": "fa-lock"},
    "parental_deblocage": {"message": "{nom} a levé le blocage de votre compte. Vous pouvez vous reconnecter.", "icone": "fa-check-circle"},
    "parental_fin": {"message": "{nom} a mis fin au contrôle parental de votre compte.", "icone": "fa-lock"},
    # ── Messages ──────────────────────────────────────────────────────────
    "message": {"message": "{nom} vous a envoyé un message.", "icone": "fa-envelope", "unique_non_lu": True},
    # ── Modération ────────────────────────────────────────────────────────
    "signalement_recu": {
        "message": "Nous avons bien reçu votre signalement. Notre équipe l'examine.",
        "icone": "fa-flag", "support": True,
    },
    "signalement_traite": {
        "message": "Votre signalement a été examiné. Merci de nous aider à garder FaceNet sûr.",
        "icone": "fa-shield-halved", "support": True,
    },
    "contenu_signale": {
        "message": "Une de vos publications a été signalée et est en cours d'examen.",
        "icone": "fa-flag", "support": True,
    },
    "contenu_supprime": {
        "message": "Votre publication a été supprimée car nous avons constaté qu'elle ne respectais pas nos standards de la communauté.",
        "icone": "fa-trash", "support": True,
    },
    "profil_probleme": {
        "message": "Un problème a été détecté sur votre profil. Veuillez le vérifier et le corriger.",
        "icone": "fa-triangle-exclamation", "support": True,
    },
    "avertissement": {
        "message": "Avertissement : votre compte a enfreint nos règles. Une récidive peut entraîner une suspension.",
        "icone": "fa-triangle-exclamation", "support": True,
    },
    # ── Badge bleu (les noms de types existants sont conservés) ──────────
    "blue_badge_sub": {
        "message": "Merci d'avoir souscrit à l'offre Tsapi Verified !",
        "icone": "fa-circle-check", "support": True,
    },
    "blue_badge_active": {
        "message": "Félicitations ! Votre badge bleu Tsapi Verified est désormais actif.",
        "icone": "fa-circle-check", "support": True,
    },
    "blue_badge_rejete": {
        "message": "Votre vérification n'a pas pu être validée. Vous pouvez soumettre une nouvelle demande.",
        "icone": "fa-circle-xmark", "support": True,
    },
    "blue_badge_expire_bientot": {
        "message": "Votre badge bleu expire dans {jours} {jours_mot}. Renouvelez-le pour le conserver.",
        "icone": "fa-hourglass-half", "support": True,
    },
    "blue_badge_expire": {
        "message": "Votre badge bleu a expiré. Renouvelez votre abonnement pour le retrouver.",
        "icone": "fa-circle-xmark", "support": True,
    },
    # ── Revérification du nom / de la photo d'un abonné vérifié (le clic mène à la bonne page) ──
    "reverif_approuvee": {
        "message": "Votre modification de profil a été vérifiée et appliquée.",
        "icone": "fa-circle-check", "support": True,
    },
    "reverif_refusee": {
        "message": "Votre modification de profil n'a pas pu être validée. Vous pouvez réessayer.",
        "icone": "fa-circle-xmark", "support": True,
    },
    # ── Paiement ──────────────────────────────────────────────────────────
    "paiement_confirme": {
        "message": "Votre paiement du forfait {forfait} a été confirmé.",
        "icone": "fa-credit-card", "support": True,
    },
    "paiement_echoue": {
        "message": "Votre paiement du forfait {forfait} n'a pas abouti. Vous pouvez réessayer.",
        "icone": "fa-credit-card", "support": True,
    },
    # ── Support / sécurité ────────────────────────────────────────────────
    "support": {
        "message": "L'équipe FaceNet vous a envoyé un message.",
        "icone": "fa-headset", "support": True,
    },
    "securite_connexion": {
        "message": "Une nouvelle connexion à votre compte a été détectée.",
        "icone": "fa-lock", "support": True,
    },
    "securite_mot_de_passe": {
        "message": "Votre mot de passe a été modifié. Si ce n'est pas vous, contactez-nous.",
        "icone": "fa-lock", "support": True,
    },
}


class _SansErreur(dict):
    """Une variable manquante dans un message reste vide au lieu de planter."""
    def __missing__(self, cle):
        return ""


def _nom_acteur(acteur):
    if acteur is None:
        return "Quelqu'un"
    return (getattr(acteur, "nom_complet", None) or getattr(acteur, "username", None) or "Quelqu'un")


def _id_acteur(acteur):
    if acteur is None:
        return None
    if isinstance(acteur, int):
        return acteur
    return getattr(acteur, "id", None)


def _url(endpoint, **valeurs):
    """url_for protégé : un lien introuvable ne casse jamais une notification."""
    try:
        return url_for(endpoint, **valeurs)
    except Exception:
        return None


def _lien(type_notif, contexte, acteur_id):
    pub_id = contexte.get("pub_id")
    if type_notif in ("like", "comment", "reply", "share", "mention", "repost") and pub_id:
        return _url("main.publication_lien", pub_id=pub_id)
    if type_notif == "message" and acteur_id:
        return _url("main.messagerie", destinataire_id=acteur_id)
    if type_notif in ("contenu_signale", "contenu_supprime", "profil_probleme", "avertissement"):
        return _url("main.statut_profil")
    if type_notif in ("blue_badge_rejete", "blue_badge_expire_bientot", "blue_badge_expire", "paiement_echoue"):
        return _url("main.forfait")
    if type_notif == "reverif_refusee":
        return _url("main.reverif_choix")
    if type_notif.startswith("parental_"):
        return (_url("main.settings") or "/settings") + "#parental-enfants"
    return None


def _json_sur(valeur):
    """Ne garde que ce qui peut être enregistré en JSON."""
    if isinstance(valeur, (str, int, float, bool)) or valeur is None:
        return valeur
    if isinstance(valeur, (list, tuple)):
        return [_json_sur(v) for v in valeur]
    if isinstance(valeur, dict):
        return {str(k): _json_sur(v) for k, v in valeur.items()}
    return str(valeur)


def _texte(type_notif, modele, nom, contexte):
    variables = _SansErreur(contexte)
    variables["nom"] = nom
    if "jours" in variables:
        variables["jours_mot"] = "jour" if str(variables["jours"]) == "1" else "jours"
    if "autres" in variables:
        variables["autres_mot"] = "autre personne" if variables["autres"] == 1 else "autres personnes"
    return modele.format_map(variables)


_pub_action_ok = False
_TYPES_PUBLICATION = ("like", "comment", "reply", "share", "mention", "repost")


def _sourdine(destinataire_id, pub_id):
    """True si le destinataire a coupé les notifications de cette publication
    (menu ⋮ « Désactiver les notifications pour cette publication » : table pub_action).
    Ne lève jamais d'exception ; en cas de doute, la notification est envoyée normalement."""
    global _pub_action_ok
    try:
        if not pub_id:
            return False
        if not _pub_action_ok:
            from sqlalchemy import inspect as _inspect
            if not _inspect(db.engine).has_table("pub_action"):
                return False
            _pub_action_ok = True
        from sqlalchemy import text as _text
        with db.session.no_autoflush:
            ligne = db.session.execute(
                _text("SELECT 1 FROM pub_action WHERE user_id = :u AND publication_id = :p "
                      "AND type = 'muet' LIMIT 1"),
                {"u": int(destinataire_id), "p": int(pub_id)}).first()
        return ligne is not None
    except Exception:
        return False


def notifier(destinataire_id, type_notif, acteur=None, *, cible=None, message=None, **contexte):
    """Crée (ou regroupe) une notification. Retourne la Notification, ou None.

    destinataire_id : id de l'utilisateur à prévenir
    type_notif      : une clé de CATALOGUE
    acteur          : User (ou id) qui a fait l'action — inutile pour les messages « Support »
    cible           : ("post" | "comment" | "user" | ..., id)
    message         : remplace le texte du catalogue (rare)
    **contexte      : variables du message et infos annexes (pub_id, forfait, jours, demande_id…)
    """
    try:
        modele = CATALOGUE.get(type_notif)
        if not modele or not destinataire_id:
            return None
        destinataire_id = int(destinataire_id)
        if db.session.get(User, destinataire_id) is None:
            return None
        if type_notif in _TYPES_PUBLICATION and _sourdine(destinataire_id, contexte.get("pub_id")):
            return None  # le destinataire a coupé les notifications de cette publication

        support = bool(modele.get("support"))
        acteur_id = SUPPORT_ID if support else _id_acteur(acteur)
        if not acteur_id:
            acteur_id = SUPPORT_ID
        if not support and acteur_id == destinataire_id:
            return None  # on ne se notifie jamais soi-même

        nom = _nom_acteur(acteur) if not support else "FaceNet"
        cible_type, cible_id = (cible or ("user", 0))
        cible_id = int(cible_id or 0)

        # ── Regroupement des likes : « Paul et 5 autres personnes ont aimé… » ──
        if modele.get("groupe"):
            precedente = (Notification.query
                          .filter_by(recipient_id=destinataire_id, type=type_notif,
                                     target_type=cible_type, target_id=cible_id)
                          .order_by(Notification.created_at.desc()).first())
            if precedente is not None:
                ids = list(precedente.aggregated_actor_ids or [])
                if acteur_id in ids:
                    return None  # déjà notifié (évite le spam like / unlike)
                if not precedente.is_read:
                    ids.append(acteur_id)
                    extra = dict(precedente.extra_data or {})
                    premier = extra.get("premier_nom") or nom
                    extra["premier_nom"] = premier
                    autres = len(ids) - 1
                    precedente.aggregated_actor_ids = ids
                    precedente.aggregated_count = len(ids)
                    precedente.is_aggregated = True
                    precedente.extra_data = extra
                    precedente.message = _texte(type_notif, modele["message_groupe"], premier,
                                                {"autres": autres})
                    precedente.updated_at = datetime.utcnow()
                    precedente.created_at = datetime.utcnow()  # remonte en haut de la liste
                    return precedente

        # ── Pas de doublon tant que la précédente n'est pas lue ──
        if modele.get("unique_non_lu"):
            existe = (Notification.query
                      .filter_by(recipient_id=destinataire_id, type=type_notif,
                                 actor_id=acteur_id, is_read=False).first())
            if existe is not None:
                return None

        texte = message or _texte(type_notif, modele["message"], nom, contexte)
        extra = {k: _json_sur(v) for k, v in contexte.items()}
        extra["lien"] = _lien(type_notif, contexte, acteur_id)
        extra["icone"] = modele.get("icone", "fa-bell")
        extra["support"] = support
        if modele.get("groupe"):
            extra["premier_nom"] = nom

        notif = Notification(
            recipient_id=destinataire_id,
            actor_id=acteur_id,
            type=type_notif,
            verb=type_notif[:32],
            target_type=str(cible_type)[:32],
            target_id=cible_id,
            message=texte,
            extra_data=extra,
            aggregated_actor_ids=[acteur_id],
            aggregated_count=1,
            is_aggregated=False,
            is_read=False,
        )
        db.session.add(notif)
        return notif
    except Exception as e:  # une notification ne doit JAMAIS casser l'action principale
        print(f"DEBUG notifier({type_notif}) : {e}")
        return None


_RE_MENTION = re.compile(r"@([A-Za-z0-9_.]{2,30})")
_MOTS_GROUPE = ("followers", "amis")   # @followers → abonnés + amis ; @amis → amis seulement
_LIMITE_GROUPE = 500                   # garde-fou : nombre maximum de destinataires d'une mention de groupe


def _ids_audience(acteur_id, mots, limite=_LIMITE_GROUPE):
    """Ids des amis (et, pour @followers, des abonnés) de l'acteur."""
    ids = set()
    try:
        u = db.session.get(User, acteur_id)
        for ami in (u.friends if u else []):
            ids.add(ami.id)
    except Exception as e:
        print(f"DEBUG audience amis : {e}")
    if "followers" in mots:
        try:
            from models import Abonnement
            for (fid,) in (db.session.query(Abonnement.follower_id)
                           .filter(Abonnement.suivi_id == acteur_id).limit(limite).all()):
                ids.add(fid)
        except Exception as e:
            print(f"DEBUG audience followers : {e}")
    ids.discard(acteur_id)
    return sorted(ids)[:limite]


def notifier_mentions(contenu, acteur, *, pub_id, exclure_ids=(), comment_id=None):
    """Notifie les utilisateurs @mentionnés dans un texte (hors acteur et hors `exclure_ids`).

    • @pseudo     → la personne reçoit « X vous a mentionné … »
    • @followers  → tous les abonnés et amis de l'acteur sont notifiés
    • @amis       → tous les amis de l'acteur sont notifiés
    Dès que d'autres personnes sont mentionnées en même temps, le texte devient
    « X vous a mentionné sur une publication avec d'autres personnes. »
    """
    try:
        bruts = set(_RE_MENTION.findall(contenu or ""))
        if not bruts:
            return 0
        mots = {b.lower() for b in bruts if b.lower() in _MOTS_GROUPE}
        individuels = {b for b in bruts if b.lower() not in _MOTS_GROUPE}
        acteur_id = _id_acteur(acteur)
        deja = set(exclure_ids or ())
        deja.add(acteur_id)

        destinataires = []
        if individuels:
            for u in User.query.filter(User.username.in_(list(individuels))).all():
                if u.id not in deja and u.id not in destinataires:
                    destinataires.append(u.id)
        if mots and acteur_id:
            for uid in _ids_audience(acteur_id, mots):
                if uid not in deja and uid not in destinataires:
                    destinataires.append(uid)
        if not destinataires:
            return 0

        plusieurs = len(destinataires) > 1 or bool(mots)
        message = None
        if plusieurs:
            message = f"{_nom_acteur(acteur)} vous a mentionné sur une publication avec d'autres personnes."
        envoyes = 0
        for uid in destinataires:
            if notifier(uid, "mention", acteur, cible=("post", pub_id), message=message,
                        pub_id=pub_id, comment_id=comment_id):
                envoyes += 1
        return envoyes
    except Exception as e:
        print(f"DEBUG notifier_mentions : {e}")
        return 0