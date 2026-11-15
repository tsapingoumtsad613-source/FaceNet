# =====================================================================
# DÉBUT : Marketplace Pro – routes Flask (blueprint isolé)
# =====================================================================
# Fichier autonome : aucune route existante n'est modifiée.
#
# Branchement (une seule fois, dans ton app factory / app.py) :
#     from routes_marketplace import marketplace_pro
#     app.register_blueprint(marketplace_pro)
#
# Toutes les URLs commencent par /marketplace/ :
#     /marketplace/messages                (page marketplace_messages.html)
#     /marketplace/api/...                 (JSON)
# ---------------------------------------------------------------------
from datetime import datetime
from functools import wraps
from urllib.parse import quote

from flask import (Blueprint, current_app, jsonify, render_template,
                   request, url_for)
from flask_login import current_user
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError

# db, User et Annonce : adapte cette ligne si tes modèles vivent ailleurs.
# (si ta classe s'appelle Produit :  from models import Produit as Annonce)
from models import (db, User, Annonce,
                    MarketplaceFavori, MarketplaceConversation, MarketplaceMessage,
                    MarketplaceBlock, MarketplaceReport)

marketplace_pro = Blueprint('marketplace_pro', __name__, url_prefix='/marketplace')

STATUTS = {'disponible': 'Disponible', 'reserve': 'Réservé', 'vendu': 'Vendu'}

MOTIFS = {
    'fraude': 'Fraude ou arnaque',
    'paiement_suspect': 'Demande de paiement suspecte',
    'article_interdit': 'Article interdit ou contrefait',
    'annonce_trompeuse': 'Annonce trompeuse (faux prix, fausses photos)',
    'harcelement': 'Harcèlement ou comportement inapproprié',
    'autre': 'Autre',
}

MAX_MESSAGE = 2000


# ---------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------
def _err(message, code=400):
    return jsonify(success=False, message=message), code


def api_login_required(f):
    """Comme @login_required, mais renvoie du JSON (401) pour les appels fetch()."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated:
            if request.path.startswith('/marketplace/api/'):
                return _err('Connexion requise.', 401)
            return current_app.login_manager.unauthorized()
        return f(*args, **kwargs)
    return wrapper


def _nom(u):
    if not u:
        return 'Utilisateur'
    return getattr(u, 'nom_complet', None) or getattr(u, 'username', None) or 'Utilisateur'


def _avatar_url(u):
    av = getattr(u, 'avatar', None) if u else None
    if av:
        return url_for('static', filename='uploads/' + av)
    return ('https://ui-avatars.com/api/?name=' + quote(_nom(u)) +
            '&background=E7F3FF&color=0866FF&size=128')


def _image_annonce(a):
    img = getattr(a, 'image', None) if a else None
    return url_for('static', filename='uploads/' + (img or 'default_annonce.png'))


def _statut_effectif(a):
    """Compatible avec l'ancien booléen `vendue` : s'il est vrai, l'article est « vendu »."""
    if getattr(a, 'vendue', False):
        return 'vendu'
    st = getattr(a, 'statut', None)
    return st if st in STATUTS else 'disponible'


def _vendeur_id(a):
    return getattr(a, 'proprietaire_id', None)


def _resume_annonce(a):
    if not a:
        return {'id': None, 'titre': 'Annonce supprimée', 'prix': 0, 'prix_txt': '',
                'image': url_for('static', filename='uploads/default_annonce.png'),
                'statut': 'disponible', 'statut_label': STATUTS['disponible'],
                'localisation': '', 'url': '#', 'supprimee': True}
    prix = getattr(a, 'prix', 0) or 0
    st = _statut_effectif(a)
    try:
        prix_txt = '{:,}'.format(int(prix)).replace(',', ' ') + ' FCFA'
    except (TypeError, ValueError):
        prix_txt = str(prix)
    try:
        url = url_for('main.item_detail', item_id=a.id)
    except Exception:
        url = '#'
    return {'id': a.id, 'titre': a.titre, 'prix': prix, 'prix_txt': prix_txt,
            'image': _image_annonce(a), 'statut': st, 'statut_label': STATUTS[st],
            'localisation': getattr(a, 'localisation', '') or '', 'url': url,
            'supprimee': False}


def _resume_utilisateur(u):
    return {'id': u.id if u else None, 'nom': _nom(u), 'avatar': _avatar_url(u),
            'url_profil': ('/profil/%s' % u.id) if u else '#'}


def _iso(dt):
    return (dt.isoformat() + 'Z') if dt else None


def _bloque(a_id, b_id):
    """True si l'un des deux a bloqué l'autre (dans la messagerie Marketplace)."""
    return db.session.query(MarketplaceBlock.id).filter(
        or_(
            (MarketplaceBlock.blocker_id == a_id) & (MarketplaceBlock.blocked_id == b_id),
            (MarketplaceBlock.blocker_id == b_id) & (MarketplaceBlock.blocked_id == a_id),
        )
    ).first() is not None


def _bloque_par(blocker_id, blocked_id):
    return db.session.query(MarketplaceBlock.id).filter_by(
        blocker_id=blocker_id, blocked_id=blocked_id).first() is not None


def _conversation_du_participant(cid):
    conv = db.session.get(MarketplaceConversation, cid)
    if not conv or not conv.a_pour_participant(current_user.id):
        return None
    return conv


def _obtenir_ou_creer_conversation(annonce, acheteur_id):
    """Retourne (conversation, message_erreur, code_http)."""
    vendeur_id = _vendeur_id(annonce)
    if not vendeur_id:
        return None, "Le vendeur de cette annonce est introuvable.", 404
    if vendeur_id == acheteur_id:
        return None, "C'est votre propre annonce : vous ne pouvez pas vous écrire à vous-même.", 400
    if _bloque(vendeur_id, acheteur_id):
        return None, "Vous ne pouvez pas contacter cet utilisateur.", 403

    conv = MarketplaceConversation.query.filter_by(
        annonce_id=annonce.id, buyer_id=acheteur_id).first()
    if conv:
        if conv.cleared_at_buyer:            # l'acheteur rouvre volontairement la discussion
            conv.cleared_at_buyer = None
            db.session.commit()
        return conv, None, 200

    conv = MarketplaceConversation(annonce_id=annonce.id, seller_id=vendeur_id,
                                   buyer_id=acheteur_id)
    db.session.add(conv)
    try:
        db.session.commit()
    except IntegrityError:               # double clic / deux onglets : on récupère l'existante
        db.session.rollback()
        conv = MarketplaceConversation.query.filter_by(
            annonce_id=annonce.id, buyer_id=acheteur_id).first()
    return conv, None, 200


# ---------------------------------------------------------------------
# A) MARKETPLACE : filtre par ville, statut, favoris
# ---------------------------------------------------------------------
@marketplace_pro.route('/api/filtrer')
def api_filtrer():
    """GET /marketplace/api/filtrer?ville=Bafoussam&categorie=Mode&q=iphone&statut=disponible"""
    ville = (request.args.get('ville') or '').strip()
    categorie = (request.args.get('categorie') or '').strip()
    q = (request.args.get('q') or '').strip()
    statut = (request.args.get('statut') or '').strip()

    requete = Annonce.query
    if ville:
        requete = requete.filter(Annonce.localisation.ilike('%' + ville + '%'))
    if categorie and hasattr(Annonce, 'categorie'):
        requete = requete.filter(Annonce.categorie == categorie)
    if q:
        requete = requete.filter(Annonce.titre.ilike('%' + q + '%'))
    if statut in STATUTS:
        if statut == 'vendu' and hasattr(Annonce, 'vendue'):
            requete = requete.filter(or_(Annonce.statut == 'vendu', Annonce.vendue.is_(True)))
        elif statut == 'disponible' and hasattr(Annonce, 'vendue'):
            requete = requete.filter(Annonce.statut == 'disponible', Annonce.vendue.isnot(True))
        else:
            requete = requete.filter(Annonce.statut == statut)

    annonces = requete.order_by(Annonce.id.desc()).limit(100).all()
    return jsonify(success=True, total=len(annonces),
                   annonces=[_resume_annonce(a) for a in annonces])


@marketplace_pro.route('/api/annonce/<int:annonce_id>/statut', methods=['POST'])
@api_login_required
def api_changer_statut(annonce_id):
    annonce = db.session.get(Annonce, annonce_id)
    if not annonce:
        return _err('Annonce introuvable.', 404)
    if _vendeur_id(annonce) != current_user.id:
        return _err("Seul le vendeur peut modifier le statut de l'article.", 403)

    data = request.get_json(silent=True) or request.form
    statut = (data.get('statut') or '').strip().lower()
    if statut not in STATUTS:
        return _err('Statut invalide.', 400)

    annonce.statut = statut
    annonce.statut_modifie_le = datetime.utcnow()
    if hasattr(annonce, 'vendue'):          # garde l'ancien booléen synchronisé
        annonce.vendue = (statut == 'vendu')
    db.session.commit()
    return jsonify(success=True, statut=statut, statut_label=STATUTS[statut])


@marketplace_pro.route('/api/annonce/<int:annonce_id>/favori', methods=['POST'])
@api_login_required
def api_toggle_favori(annonce_id):
    """Bascule le favori. Corps JSON optionnel {"etat": true|false} pour forcer ajout/retrait."""
    annonce = db.session.get(Annonce, annonce_id)
    if not annonce:
        return _err('Annonce introuvable.', 404)

    data = request.get_json(silent=True) or {}
    existant = MarketplaceFavori.query.filter_by(
        user_id=current_user.id, annonce_id=annonce_id).first()
    voulu = data.get('etat') if isinstance(data.get('etat'), bool) else (existant is None)

    if voulu and not existant:
        db.session.add(MarketplaceFavori(user_id=current_user.id, annonce_id=annonce_id))
    elif not voulu and existant:
        db.session.delete(existant)
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
    return jsonify(success=True, favori=bool(voulu))


@marketplace_pro.route('/api/favoris/ids')
@api_login_required
def api_favoris_ids():
    ids = [r[0] for r in db.session.query(MarketplaceFavori.annonce_id)
           .filter_by(user_id=current_user.id).all()]
    return jsonify(success=True, ids=ids)


@marketplace_pro.route('/api/favoris')
@api_login_required
def api_favoris():
    favoris = (MarketplaceFavori.query.filter_by(user_id=current_user.id)
               .order_by(MarketplaceFavori.created_at.desc()).all())
    return jsonify(success=True, annonces=[_resume_annonce(f.annonce) for f in favoris])


# ---------------------------------------------------------------------
# B) MESSAGERIE MARKETPLACE
# ---------------------------------------------------------------------
@marketplace_pro.route('/messages')
@api_login_required
def marketplace_messages():
    """Page marketplace_messages.html.
    /marketplace/messages?seller_id=XXX&product_id=YYY  → ouvre (ou crée) la discussion liée à l'article."""
    product_id = request.args.get('product_id', type=int)
    conversation_id = request.args.get('conversation_id', type=int)
    erreur = None

    if product_id:
        annonce = db.session.get(Annonce, product_id)
        if not annonce:
            erreur = "Cette annonce n'existe plus."
        else:
            # Le vendeur réel est celui de l'annonce : on ignore un seller_id falsifié.
            conv, erreur, _ = _obtenir_ou_creer_conversation(annonce, current_user.id)
            if conv:
                conversation_id = conv.id

    return render_template('marketplace_messages.html',
                           conversation_active_id=conversation_id, erreur=erreur)


@marketplace_pro.route('/api/conversation/ouvrir', methods=['POST'])
@api_login_required
def api_ouvrir_conversation():
    data = request.get_json(silent=True) or request.form
    try:
        product_id = int(data.get('product_id'))
    except (TypeError, ValueError):
        return _err('product_id manquant.', 400)
    annonce = db.session.get(Annonce, product_id)
    if not annonce:
        return _err("Cette annonce n'existe plus.", 404)
    conv, erreur, code = _obtenir_ou_creer_conversation(annonce, current_user.id)
    if not conv:
        return _err(erreur, code)
    return jsonify(success=True, conversation_id=conv.id)


@marketplace_pro.route('/api/conversations')
@api_login_required
def api_conversations():
    """?role=tous|achats|ventes"""
    role = request.args.get('role', 'tous')
    moi = current_user.id

    requete = MarketplaceConversation.query
    if role == 'achats':
        requete = requete.filter(MarketplaceConversation.buyer_id == moi)
    elif role == 'ventes':
        requete = requete.filter(MarketplaceConversation.seller_id == moi)
    else:
        requete = requete.filter(or_(MarketplaceConversation.buyer_id == moi,
                                     MarketplaceConversation.seller_id == moi))
    convs = requete.order_by(
        func.coalesce(MarketplaceConversation.last_message_at,
                      MarketplaceConversation.created_at).desc()).all()
    convs = [c for c in convs if c.est_visible_pour(moi)
             # le vendeur ne voit une discussion qu'à partir du 1er message de l'acheteur
             and not (moi == c.seller_id and c.last_message_at is None)]

    non_lus = {}
    if convs:
        lignes = (db.session.query(MarketplaceMessage.conversation_id, func.count(MarketplaceMessage.id))
                  .filter(MarketplaceMessage.conversation_id.in_([c.id for c in convs]),
                          MarketplaceMessage.sender_id != moi,
                          MarketplaceMessage.lu.is_(False))
                  .group_by(MarketplaceMessage.conversation_id).all())
        non_lus = {cid: n for cid, n in lignes}

    resultat = []
    for c in convs:
        autre = c.buyer if moi == c.seller_id else c.seller
        resultat.append({
            'id': c.id,
            'role': 'vendeur' if moi == c.seller_id else 'acheteur',
            'annonce': _resume_annonce(c.annonce),
            'autre': _resume_utilisateur(autre),
            'dernier_message': c.last_message_preview or '',
            'dernier_message_at': _iso(c.last_message_at or c.created_at),
            'non_lus': non_lus.get(c.id, 0),
        })
    return jsonify(success=True, conversations=resultat)


@marketplace_pro.route('/api/conversation/<int:cid>/messages')
@api_login_required
def api_messages(cid):
    conv = _conversation_du_participant(cid)
    if not conv:
        return _err('Conversation introuvable.', 404)
    moi = current_user.id
    autre = conv.buyer if moi == conv.seller_id else conv.seller

    requete = MarketplaceMessage.query.filter_by(conversation_id=conv.id)
    cleared = conv.cleared_at_pour(moi)
    if cleared:
        requete = requete.filter(MarketplaceMessage.created_at > cleared)
    messages = requete.order_by(MarketplaceMessage.created_at, MarketplaceMessage.id).all()

    # Marque comme lus les messages reçus
    maj = False
    for m in messages:
        if m.sender_id != moi and not m.lu:
            m.lu, m.lu_at, maj = True, datetime.utcnow(), True
    if maj:
        db.session.commit()

    return jsonify(
        success=True,
        conversation={
            'id': conv.id,
            'role': 'vendeur' if moi == conv.seller_id else 'acheteur',
            'annonce': _resume_annonce(conv.annonce),
            'autre': _resume_utilisateur(autre),
            'bloque_par_moi': _bloque_par(moi, autre.id),
            'bloque_par_lui': _bloque_par(autre.id, moi),
        },
        messages=[{
            'id': m.id,
            'contenu': m.contenu,
            'sent_by_me': m.sender_id == moi,
            'timestamp': _iso(m.created_at),
            'lu': bool(m.lu),
        } for m in messages],
    )


@marketplace_pro.route('/api/conversation/<int:cid>/envoyer', methods=['POST'])
@api_login_required
def api_envoyer(cid):
    conv = _conversation_du_participant(cid)
    if not conv:
        return _err('Conversation introuvable.', 404)
    moi = current_user.id
    autre_id = conv.autre_id(moi)

    if _bloque(moi, autre_id):
        return _err("Vous ne pouvez plus échanger avec cet utilisateur.", 403)

    data = request.get_json(silent=True) or request.form
    contenu = (data.get('contenu') or '').strip()
    if not contenu:
        return _err('Message vide.', 400)
    if len(contenu) > MAX_MESSAGE:
        return _err('Message trop long (%d caractères maximum).' % MAX_MESSAGE, 400)

    msg = MarketplaceMessage(conversation_id=conv.id, sender_id=moi, contenu=contenu)
    conv.last_message_at = datetime.utcnow()
    conv.last_message_preview = contenu[:200]
    db.session.add(msg)
    db.session.commit()

    return jsonify(success=True, message={
        'id': msg.id, 'contenu': msg.contenu, 'sent_by_me': True,
        'timestamp': _iso(msg.created_at), 'lu': False})


@marketplace_pro.route('/api/conversation/<int:cid>/supprimer', methods=['POST'])
@api_login_required
def api_supprimer_conversation(cid):
    conv = _conversation_du_participant(cid)
    if not conv:
        return _err('Conversation introuvable.', 404)
    maintenant = datetime.utcnow()
    if current_user.id == conv.seller_id:
        conv.cleared_at_seller = maintenant
    else:
        conv.cleared_at_buyer = maintenant
    db.session.commit()
    return jsonify(success=True)


@marketplace_pro.route('/api/utilisateur/<int:uid>/bloquer', methods=['POST'])
@api_login_required
def api_bloquer(uid):
    if uid == current_user.id:
        return _err('Vous ne pouvez pas vous bloquer vous-même.', 400)
    if not db.session.get(User, uid):
        return _err('Utilisateur introuvable.', 404)
    if not _bloque_par(current_user.id, uid):
        db.session.add(MarketplaceBlock(blocker_id=current_user.id, blocked_id=uid))
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
    return jsonify(success=True, bloque=True)


@marketplace_pro.route('/api/utilisateur/<int:uid>/debloquer', methods=['POST'])
@api_login_required
def api_debloquer(uid):
    MarketplaceBlock.query.filter_by(blocker_id=current_user.id, blocked_id=uid).delete()
    db.session.commit()
    return jsonify(success=True, bloque=False)


@marketplace_pro.route('/api/signaler', methods=['POST'])
@api_login_required
def api_signaler():
    """Corps JSON : {type: 'annonce'|'utilisateur'|'message', motif, description?,
                     annonce_id?, user_id?, conversation_id?, message_id?}"""
    data = request.get_json(silent=True) or {}
    cible = (data.get('type') or '').strip()
    motif = (data.get('motif') or '').strip()
    description = (data.get('description') or '').strip()[:500] or None
    moi = current_user.id

    if cible not in ('annonce', 'utilisateur', 'message'):
        return _err('Type de signalement invalide.', 400)
    if motif not in MOTIFS:
        return _err('Veuillez choisir un motif.', 400)

    rapport = MarketplaceReport(reporter_id=moi, cible_type=cible, motif=motif,
                                description=description)

    if cible == 'annonce':
        annonce = db.session.get(Annonce, data.get('annonce_id') or 0)
        if not annonce:
            return _err('Annonce introuvable.', 404)
        if _vendeur_id(annonce) == moi:
            return _err('Vous ne pouvez pas signaler votre propre annonce.', 400)
        rapport.annonce_id = annonce.id
        rapport.reported_user_id = _vendeur_id(annonce)

    else:  # 'utilisateur' ou 'message' → il faut une conversation dont on est participant
        conv = _conversation_du_participant(data.get('conversation_id') or 0)
        if not conv:
            return _err('Conversation introuvable.', 404)
        rapport.conversation_id = conv.id
        rapport.annonce_id = conv.annonce_id
        rapport.reported_user_id = conv.autre_id(moi)

        if cible == 'message':
            msg = db.session.get(MarketplaceMessage, data.get('message_id') or 0)
            if not msg or msg.conversation_id != conv.id or msg.sender_id == moi:
                return _err('Message introuvable.', 404)
            rapport.message_id = msg.id
            rapport.extrait_message = msg.contenu[:1000]
            rapport.reported_user_id = msg.sender_id

    # Anti-doublon : un signalement en attente identique n'est pas recréé (réponse identique pour l'utilisateur)
    doublon = MarketplaceReport.query.filter_by(
        reporter_id=moi, cible_type=cible, statut='en_attente',
        annonce_id=rapport.annonce_id, reported_user_id=rapport.reported_user_id,
        message_id=rapport.message_id).first()
    if not doublon:
        db.session.add(rapport)
        db.session.commit()

    return jsonify(success=True,
                   message="Merci. Votre signalement a été transmis à l'équipe de modération. "
                           "La personne signalée ne saura pas que c'est vous.")


@marketplace_pro.route('/api/non_lus')
@api_login_required
def api_non_lus():
    """Nombre total de messages Marketplace non lus (pour le badge dans messagerie.html)."""
    moi = current_user.id
    total = (db.session.query(func.count(MarketplaceMessage.id))
             .join(MarketplaceConversation,
                   MarketplaceMessage.conversation_id == MarketplaceConversation.id)
             .filter(or_(MarketplaceConversation.buyer_id == moi,
                         MarketplaceConversation.seller_id == moi),
                     MarketplaceMessage.sender_id != moi,
                     MarketplaceMessage.lu.is_(False))
             .scalar()) or 0
    return jsonify(success=True, count=total)

# ---------------------------------------------------------------------
# C) BOUCLIER FACENET : IA anti-arnaque, DISCRÈTE et réservée à l'acheteur
# ---------------------------------------------------------------------
def _jours_depuis(dt):
    try:
        return max(0, (datetime.utcnow() - dt).days) if dt else None
    except Exception:
        return None


def _contexte_bouclier(conv):
    """Ce que l'IA sait de l'acheteur, du vendeur et de l'annonce (aucune donnée privée :
    ni e-mail, ni téléphone, ni mot de passe)."""
    acheteur, vendeur, annonce = conv.buyer, conv.seller, conv.annonce
    nb_conv_acheteur = MarketplaceConversation.query.filter_by(buyer_id=conv.buyer_id).count()
    ctx = {
        'acheteur': {
            'prenom': (getattr(acheteur, 'prenom', None) or _nom(acheteur).split(' ')[0] or '').strip(),
            'anciennete_jours': _jours_depuis(getattr(acheteur, 'created_at', None)),
            'discussions_marketplace': nb_conv_acheteur,
            'experience': 'debutant' if nb_conv_acheteur < 3 else 'habitue',
        },
        'vendeur': {
            'nom': _nom(vendeur),
            'anciennete_jours': _jours_depuis(getattr(vendeur, 'created_at', None)),
            'verifie': bool(getattr(vendeur, 'is_verify', False) or getattr(vendeur, 'has_badge_bleu', False)),
            'abonnes': getattr(vendeur, 'followers_count', 0) or 0,
            'ville': getattr(vendeur, 'ville', None) or getattr(vendeur, 'localisation', None),
            'annonces_publiees': Annonce.query.filter_by(user_id=conv.seller_id).count(),
            'signalements_recus': MarketplaceReport.query.filter_by(reported_user_id=conv.seller_id).count(),
            'blocages_recus': MarketplaceBlock.query.filter_by(blocked_id=conv.seller_id).count(),
        },
        'annonce': None,
    }
    if annonce:
        ctx['annonce'] = {
            'titre': annonce.titre,
            'prix_fcfa': getattr(annonce, 'prix', None),
            'categorie': getattr(annonce, 'categorie', None),
            'localisation': getattr(annonce, 'localisation', None),
            'statut': _statut_effectif(annonce),
            'publiee_depuis_jours': _jours_depuis(getattr(annonce, 'date_creation', None)),
        }
    return ctx


@marketplace_pro.route('/api/conversation/<int:cid>/bouclier')
@api_login_required
def api_bouclier(cid):
    """Analyse IA de la discussion. RÉSERVÉE à l'acheteur : si c'est le vendeur qui appelle,
    la réponse est vide. Rien n'est écrit dans la discussion : le vendeur ne saura jamais."""
    conv = _conversation_du_participant(cid)
    if not conv:
        return _err('Conversation introuvable.', 404)
    if current_user.id != conv.buyer_id:
        return jsonify(success=True, alerte=None)
    try:
        import marketplace_ia

        requete = MarketplaceMessage.query.filter_by(conversation_id=conv.id)
        cleared = conv.cleared_at_pour(current_user.id)
        if cleared:
            requete = requete.filter(MarketplaceMessage.created_at > cleared)
        lignes = requete.order_by(MarketplaceMessage.created_at, MarketplaceMessage.id).all()
        messages = [{'id': m.id,
                     'auteur': 'acheteur' if m.sender_id == conv.buyer_id else 'vendeur',
                     'contenu': m.contenu} for m in lignes]

        alerte = marketplace_ia.analyser(conv.id, messages, _contexte_bouclier(conv))
        return jsonify(success=True, alerte=alerte)
    except Exception:
        # Le bouclier ne doit JAMAIS gêner la messagerie : en cas de souci, on ne montre rien.
        current_app.logger.exception('Bouclier FaceNet : analyse impossible')
        return jsonify(success=True, alerte=None)


# =====================================================================
# FIN : Marketplace Pro – routes Flask
# =====================================================================