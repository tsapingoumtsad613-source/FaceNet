"""
marketplace_pro.py — Blueprint « marketplace_pro » : tout ce que marketplace.html et
marketplace_message.html appellent via url_for('marketplace_pro.…') ou via leurs fetch(),
plus le paiement sécurisé (séquestre) et les 3 routes de messagerie qui manquaient
(supprimer pour moi / pour tous / partager).

Cohérent avec TON application :
  * l'utilisateur connecté se lit comme dans ton routes.py : session['user_id'] ;
  * blocages = ton modèle BlockedUser, favoris = ton modèle MarketplaceFavori ;
  * temps réel = ton sockets.py (salle « user_<id> ») ;
  * paiement = ton module `fapshi`.
Rien de ce que tu as déjà n'est remplacé (voir BRANCHEMENT.md pour les 4 petits ajouts).
"""
import os
import re
import shutil
import unicodedata
import uuid
from datetime import datetime

from flask import Blueprint, current_app, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import and_, or_
from werkzeug.exceptions import HTTPException

import escrow_service as escrow
from escrow_service import ErreurMetier, fmt_prix
from extensions import db
from marketplace_models import (AnnonceInfo, MessageSuppression, MkConversation, MkMessage, MkSignalement,
                                MouvementPortefeuille, Transaction)
from models import Annonce, BlockedUser, DemandeAmitie, MarketplaceFavori, Message, User

marketplace_pro_bp = Blueprint('marketplace_pro', __name__)

STATUTS = {'disponible': 'Disponible', 'reserve': 'Réservé', 'vendu': 'Vendu'}
MOTIFS_SIGNALEMENT = ('fraude', 'paiement_suspect', 'article_interdit', 'annonce_trompeuse', 'harcelement', 'autre')


# =============================================================================
# Aides
# =============================================================================
def _moi():
    uid = session.get('user_id')
    return db.session.get(User, int(uid)) if uid else None


def _json(ok=True, status=200, **donnees):
    donnees['success'] = ok
    if not ok:
        donnees.setdefault('error', donnees.get('message', ''))
    return jsonify(donnees), status


def connecte(f):
    """Comme @login_required mais répond en JSON 401 (les templates testent le code 401)."""
    from functools import wraps

    @wraps(f)
    def enveloppe(*a, **k):
        if not session.get('user_id') or _moi() is None:
            return _json(False, 401, message='Connexion requise.')
        return f(*a, **k)
    return enveloppe


def _admin(user):
    return bool(getattr(user, 'is_pdg', False))


def _iso(dt):
    return dt.isoformat() + 'Z' if dt else ''


def _static_upload(nom, defaut):
    return url_for('static', filename='uploads/' + (nom or defaut))


def _resume_utilisateur(u):
    return {'id': u.id, 'nom': u.nom_complet or u.username, 'avatar': _static_upload(u.avatar, 'default_avatar.png')}


def _resume_annonce(a):
    if a is None:
        return {'id': 0, 'titre': 'Annonce supprimée', 'image': _static_upload(None, 'default_annonce.png'), 'prix_txt': '',
                'statut': 'vendu', 'statut_label': 'Indisponible', 'url': url_for('main.marketplace'), 'supprimee': True}
    return {'id': a.id, 'titre': a.titre, 'image': _static_upload(a.image, 'default_annonce.png'), 'prix_txt': fmt_prix(a.prix),
            'statut': a.statut, 'statut_label': STATUTS.get(a.statut, 'Disponible'),
            'url': url_for('main.item_detail', item_id=a.id), 'supprimee': False}


def _a_bloque(proprietaire_id, cible_id):
    return BlockedUser.query.filter_by(owner_id=proprietaire_id, blocked_id=cible_id).first() is not None


def _blocage_entre(a_id, b_id):
    return _a_bloque(a_id, b_id) or _a_bloque(b_id, a_id)


def _conversation_du_user(cid, moi):
    """Conversation dont `moi` est participant, sinon 404 (on ne révèle pas celles des autres)."""
    conv = db.session.get(MkConversation, cid)
    if not conv or not conv.est_participant(moi.id):
        raise ErreurMetier('Conversation introuvable.', 404)
    return conv


def _messages_visibles(conv, moi_id):
    q = conv.messages
    limite = conv.efface_a_pour(moi_id)
    if limite:
        q = q.filter(MkMessage.date_envoi > limite)
    return q.order_by(MkMessage.date_envoi.asc(), MkMessage.id.asc()).all()


def _message_json(m, moi_id):
    moi = (m.expediteur_id == moi_id) and not m.systeme    # un message système s'affiche « reçu » pour les deux
    return {'id': m.id, 'contenu': m.contenu, 'sent_by_me': moi, 'lu': bool(m.lu), 'timestamp': _iso(m.date_envoi),
            'systeme': bool(m.systeme)}


def _transaction_active(annonce_id):
    return Transaction.query.filter(Transaction.annonce_id == annonce_id, Transaction.statut.in_(escrow.TX_ACTIVES)).first()


# =============================================================================
# Gestion d'erreurs propre à ce blueprint (n'affecte pas le reste de l'application)
# =============================================================================
@marketplace_pro_bp.errorhandler(ErreurMetier)
def _erreur_metier(e):
    db.session.rollback()
    return _json(False, e.code, message=e.message)


@marketplace_pro_bp.errorhandler(Exception)
def _erreur_inattendue(e):
    if isinstance(e, HTTPException):
        return e
    db.session.rollback()
    current_app.logger.exception('Erreur marketplace_pro')
    if request.path.startswith(('/marketplace/api/', '/api/paiement', '/api/portefeuille', '/message/')):
        return _json(False, 500, message='Erreur interne du serveur.')
    raise e


# =============================================================================
# Protège tes routes EXISTANTES (prix / vendre / republier) pendant un paiement,
# sans modifier ton routes.py : un acheteur a engagé de l'argent sur cet article.
# =============================================================================
_RE_ANNONCE_ACTION = re.compile(r'^/api/annonce/(\d+)/(prix|vendre|republier)$')


@marketplace_pro_bp.before_app_request
def _verrou_pendant_paiement():
    if request.method != 'POST':
        return None
    m = _RE_ANNONCE_ACTION.match(request.path)
    if m and _transaction_active(int(m.group(1))):
        return _json(False, 409, message='Un paiement est en cours sur cet article : modification impossible pour le moment.')
    return None


# =============================================================================
# main.item_detail (manquait dans ton routes.py : marketplace.html l'appelle pour chaque carte)
# =============================================================================
def brancher_sur_main(main_bp):
    """À appeler dans app.py AVANT app.register_blueprint(main_bp). Ajoute main.item_detail."""
    def item_detail(item_id):
        a = db.session.get(Annonce, item_id)
        if not a:
            return redirect(url_for('main.marketplace'))
        moi = _moi()
        if not moi or moi.id != a.user_id:
            info = a.info or AnnonceInfo(annonce_id=a.id, statut='disponible', nb_vues=0)
            info.nb_vues = (info.nb_vues or 0) + 1
            db.session.add(info)
            db.session.commit()
        return redirect(url_for('marketplace_detail.page', annonce_id=item_id))

    main_bp.add_url_rule('/annonce/<int:item_id>', endpoint='item_detail', view_func=item_detail)


# =============================================================================
# Page « Messages Marketplace »
# =============================================================================
@marketplace_pro_bp.route('/marketplace/messages')
def messages():
    """marketplace_message.html. Accepte ?conversation_id=N  ou  ?seller_id=S&product_id=P
    (bouton « Discuter avec le vendeur » de la grille)."""
    moi = _moi()
    if not moi:
        return redirect(url_for('main.login'))
    erreur, active = None, None
    cid = request.args.get('conversation_id', type=int)
    if cid:
        conv = db.session.get(MkConversation, cid)
        if conv and conv.est_participant(moi.id):
            active = conv.id
        else:
            erreur = 'Conversation introuvable.'
    elif request.args.get('product_id'):
        annonce = db.session.get(Annonce, request.args.get('product_id', type=int) or 0)
        if not annonce:
            erreur = "Cette annonce n'existe plus."
        elif request.args.get('seller_id', type=int) != annonce.user_id:
            erreur = 'Vendeur incorrect pour cette annonce.'          # empêche de falsifier le lien
        elif annonce.user_id == moi.id:
            erreur = 'Vous ne pouvez pas vous écrire à vous-même.'
        elif _blocage_entre(moi.id, annonce.user_id):
            erreur = 'Vous ne pouvez plus échanger avec ce vendeur.'
        else:
            conv = escrow.conversation_pour(annonce, moi.id)
            conv.masquee_acheteur = False
            db.session.commit()
            return redirect(url_for('marketplace_pro.messages', conversation_id=conv.id))
    return render_template('marketplace_message.html', conversation_active_id=active, erreur=erreur)


# =============================================================================
# Compteur, favoris, statut
# =============================================================================
@marketplace_pro_bp.route('/marketplace/api/non_lus')
@connecte
def api_non_lus():
    moi = _moi()
    total = 0
    convs = MkConversation.query.filter(or_(MkConversation.acheteur_id == moi.id, MkConversation.vendeur_id == moi.id)).all()
    for c in convs:
        if c.masquee_pour(moi.id):
            continue
        q = MkMessage.query.filter(MkMessage.conversation_id == c.id, MkMessage.expediteur_id != moi.id,
                                   MkMessage.lu.is_(False), MkMessage.systeme.is_(False))
        limite = c.efface_a_pour(moi.id)
        if limite:
            q = q.filter(MkMessage.date_envoi > limite)
        total += q.count()
    return _json(count=total)


@marketplace_pro_bp.route('/marketplace/api/favoris/ids')
@connecte
def api_favoris_ids():
    return _json(ids=[f.annonce_id for f in MarketplaceFavori.query.filter_by(user_id=_moi().id)])


@marketplace_pro_bp.route('/marketplace/api/annonce/<int:annonce_id>/favori', methods=['POST'])
@connecte
def api_favori(annonce_id):
    """Bascule le favori ; si le corps contient {"etat": true|false}, impose cet état (idempotent)."""
    moi = _moi()
    if not db.session.get(Annonce, annonce_id):
        raise ErreurMetier('Annonce introuvable.', 404)
    existant = MarketplaceFavori.query.filter_by(user_id=moi.id, annonce_id=annonce_id).first()
    voulu = (request.get_json(silent=True) or {}).get('etat')
    voulu = (not existant) if voulu is None else bool(voulu)
    if voulu and not existant:
        db.session.add(MarketplaceFavori(user_id=moi.id, annonce_id=annonce_id))
    elif not voulu and existant:
        db.session.delete(existant)
    db.session.commit()
    return _json(favori=voulu)


@marketplace_pro_bp.route('/marketplace/api/annonce/<int:annonce_id>/statut', methods=['POST'])
@connecte
def api_changer_statut(annonce_id):
    moi = _moi()
    annonce = db.session.get(Annonce, annonce_id)
    if not annonce:
        raise ErreurMetier('Annonce introuvable.', 404)
    if annonce.user_id != moi.id:
        raise ErreurMetier('Seul le vendeur peut changer le statut.', 403)
    statut = (request.get_json(silent=True) or {}).get('statut')
    if statut not in STATUTS:
        raise ErreurMetier('Statut invalide.')
    if _transaction_active(annonce.id):
        raise ErreurMetier('Un paiement est en cours : le statut suit automatiquement la transaction.', 409)
    ancien = annonce.statut
    annonce.statut = statut
    db.session.commit()
    if statut != ancien:
        from marketplace_detail import notifier_alertes
        notifier_alertes(annonce, '« %s » est maintenant : %s' % (annonce.titre, STATUTS[statut]), moi.id)
    return _json(statut=statut, statut_label=STATUTS[statut])


# =============================================================================
# Discussions Marketplace
# =============================================================================
@marketplace_pro_bp.route('/marketplace/api/conversations')
@connecte
def api_conversations():
    moi = _moi()
    role = request.args.get('role', 'tous')
    convs = (MkConversation.query.filter(or_(MkConversation.acheteur_id == moi.id, MkConversation.vendeur_id == moi.id))
             .order_by(MkConversation.dernier_message_at.desc()).all())
    sortie = []
    for c in convs:
        if c.masquee_pour(moi.id):
            continue
        suis_vendeur = c.vendeur_id == moi.id
        if (role == 'ventes' and not suis_vendeur) or (role == 'achats' and suis_vendeur):
            continue
        visibles = _messages_visibles(c, moi.id)
        dernier = visibles[-1] if visibles else None
        non_lus = sum(1 for m in visibles if m.expediteur_id != moi.id and not m.lu and not m.systeme)
        autre = db.session.get(User, c.autre_id(moi.id))
        sortie.append({'id': c.id, 'role': 'vendeur' if suis_vendeur else 'acheteur', 'non_lus': non_lus,
                       'dernier_message': (dernier.contenu or '')[:120] if dernier else '',
                       'dernier_message_at': _iso(dernier.date_envoi if dernier else c.dernier_message_at),
                       'annonce': _resume_annonce(c.annonce), 'autre': _resume_utilisateur(autre)})
    return _json(conversations=sortie)


@marketplace_pro_bp.route('/marketplace/api/conversations/<int:cid>/messages')
@connecte
def api_messages(cid):
    moi = _moi()
    conv = _conversation_du_user(cid, moi)
    visibles = _messages_visibles(conv, moi.id)
    modifie = False
    for m in visibles:                                    # ouvrir la discussion = lire
        if m.expediteur_id != moi.id and not m.lu:
            m.lu, modifie = True, True
    if modifie:
        db.session.commit()
        escrow.emettre(conv.autre_id(moi.id), 'mk:lu', {'conversation_id': conv.id})
    autre = db.session.get(User, conv.autre_id(moi.id))
    return _json(messages=[_message_json(m, moi.id) for m in visibles],
                 conversation={'id': conv.id, 'role': 'vendeur' if conv.vendeur_id == moi.id else 'acheteur',
                               'annonce': _resume_annonce(conv.annonce),
                               'autre': dict(_resume_utilisateur(autre), url_profil='/profil/%d' % autre.id),
                               'bloque_par_moi': _a_bloque(moi.id, autre.id), 'bloque_par_lui': _a_bloque(autre.id, moi.id)})


@marketplace_pro_bp.route('/marketplace/api/conversations/<int:cid>/envoyer', methods=['POST'])
@connecte
def api_envoyer(cid):
    moi = _moi()
    conv = _conversation_du_user(cid, moi)
    texte = ((request.get_json(silent=True) or {}).get('contenu') or '').strip()
    if not texte:
        raise ErreurMetier('Message vide.')
    if len(texte) > 2000:
        raise ErreurMetier('Message trop long (2000 caractères maximum).')
    if _blocage_entre(moi.id, conv.autre_id(moi.id)):
        raise ErreurMetier('Vous ne pouvez plus échanger avec cet utilisateur.', 403)
    m = escrow.poster_message(conv, moi.id, texte)
    return _json(message=_message_json(m, moi.id))


@marketplace_pro_bp.route('/marketplace/api/conversations/<int:cid>/supprimer', methods=['POST'])
@connecte
def api_supprimer_conversation(cid):
    """La conversation disparaît de MA liste ; l'autre personne la garde. Un nouveau message la fait réapparaître."""
    moi = _moi()
    conv = _conversation_du_user(cid, moi)
    maintenant = datetime.utcnow()
    if moi.id == conv.acheteur_id:
        conv.masquee_acheteur, conv.efface_acheteur_a = True, maintenant
    else:
        conv.masquee_vendeur, conv.efface_vendeur_a = True, maintenant
    db.session.commit()
    return _json()


@marketplace_pro_bp.route('/marketplace/api/utilisateurs/<int:uid>/bloquer', methods=['POST'])
@connecte
def api_bloquer(uid):
    moi = _moi()
    if uid == moi.id or not db.session.get(User, uid):
        raise ErreurMetier('Utilisateur introuvable.', 404)
    if not _a_bloque(moi.id, uid):
        db.session.add(BlockedUser(owner_id=moi.id, blocked_id=uid))
        db.session.commit()
    return _json()


@marketplace_pro_bp.route('/marketplace/api/utilisateurs/<int:uid>/debloquer', methods=['POST'])
@connecte
def api_debloquer(uid):
    BlockedUser.query.filter_by(owner_id=_moi().id, blocked_id=uid).delete()
    db.session.commit()
    return _json()


# =============================================================================
# Bouclier FaceNet : analyse anti-arnaque d'une discussion (privée, acheteur uniquement)
# Appelé par marketplace_message.html : url_for('marketplace_pro.api_bouclier', cid=...)
# =============================================================================
def _norm(txt):
    """Minuscules sans accents, pour comparer sans se soucier de la façon d'écrire."""
    txt = unicodedata.normalize('NFD', (txt or '').lower())
    return ''.join(c for c in txt if unicodedata.category(c) != 'Mn')


# (identifiant, points, titre, motifs regex sur texte normalisé)
_SIGNAUX_BOUCLIER = (
    ('otp', 4, 'Demande d\'un code ou d\'un mot de passe',
     r'\b(code (de )?(verification|confirmation|secret|otp|sms)|otp|mot de passe|code pin|\bpin\b)'),
    ('paiement_externe', 3, 'Paiement en dehors de FaceNet',
     r'(orange ?money|mtn ?(momo|money)|\bmomo\b|western ?union|moneygram|paypal|bitcoin|crypto|virement|mandat|'
     r'envoie(z)? (moi )?l.?argent|transfert (d.?argent )?(sur|vers|au) (mon|ce) )'),
    ('frais_avance', 3, 'Frais demandés à l\'avance',
     r'(frais (de )?(douane|livraison|transport|dossier|deblocage)|avance|acompte|payer (d.?abord|avant))'),
    ('contact_externe', 2, 'Invitation à quitter la discussion FaceNet',
     r'(whats ?app|telegram|signal|messenger|mon numero|appelle[- ]moi|contacte[- ]moi (sur|au)|\bmail\b|@gmail|@yahoo)'),
    ('lien', 2, 'Lien externe',
     r'(https?://|www\.|bit\.ly|tinyurl)'),
    ('pression', 1, 'Pression pour aller vite',
     r'(urgent|vite|tout de suite|maintenant|aujourd.?hui seulement|dernier prix|plusieurs (personnes|acheteurs)|dernier jour)'),
)
_RE_TELEPHONE = re.compile(r'(\+?\d[\d .-]{7,}\d)')

_CONSEILS_BOUCLIER = {
    'otp': 'Ne communiquez jamais un code reçu par SMS ou un mot de passe, même à quelqu\'un qui semble de confiance.',
    'paiement_externe': 'Payez uniquement via le paiement sécurisé FaceNet : l\'argent n\'est libéré qu\'à la réception de l\'article.',
    'frais_avance': 'Méfiez-vous des frais demandés avant d\'avoir reçu l\'article : c\'est une technique d\'arnaque classique.',
    'contact_externe': 'Gardez la discussion ici : en dehors de FaceNet, nous ne pouvons plus vous protéger.',
    'lien': 'N\'ouvrez pas les liens inconnus et ne saisissez jamais vos informations de paiement sur une page externe.',
    'pression': 'Prenez votre temps : un vrai vendeur comprend que vous vouliez vérifier l\'article avant d\'acheter.',
}


def _analyser_discussion(messages, moi_id):
    """Analyse les messages de l'AUTRE personne et renvoie le dictionnaire `alerte` attendu par le HTML."""
    points, signaux, vus, suspects = 0, [], set(), []
    for m in messages:
        if m.expediteur_id == moi_id or m.systeme:
            continue
        texte = _norm(m.contenu)
        trouve = []
        for ident, pts, titre, motif in _SIGNAUX_BOUCLIER:
            if re.search(motif, texte):
                trouve.append((ident, pts, titre))
        if _RE_TELEPHONE.search(m.contenu or '') and not any(i == 'contact_externe' for i, _, _ in trouve):
            trouve.append(('contact_externe', 2, _SIGNAUX_BOUCLIER[3][2]))
        if not trouve:
            continue
        suspects.append(m.id)
        extrait = (m.contenu or '').strip().replace('\n', ' ')
        extrait = extrait[:70] + ('…' if len(extrait) > 70 else '')
        for ident, pts, titre in trouve:
            if ident not in vus:                      # chaque type de signal compte une seule fois
                vus.add(ident)
                points += pts
                signaux.append({'id': ident, 'titre': titre, 'detail': '« %s »' % extrait})

    if points >= 4:
        niveau, titre = 'danger', 'Cette discussion ressemble à une tentative d\'arnaque'
        resume = 'Plusieurs signaux inquiétants ont été repérés. Ne payez rien et ne partagez aucune information en dehors de FaceNet.'
    elif points >= 2:
        niveau, titre = 'prudence', 'Restez prudent dans cette discussion'
        resume = 'Quelques éléments méritent votre attention avant d\'aller plus loin.'
    else:
        return {'niveau': 'ok', 'titre': 'Aucun signal suspect', 'resume': '', 'signaux': [], 'conseils': [], 'ids_suspects': []}

    return {'niveau': niveau, 'titre': titre, 'resume': resume,
            'signaux': [{'titre': s['titre'], 'detail': s['detail']} for s in signaux],
            'conseils': [_CONSEILS_BOUCLIER[s['id']] for s in signaux],
            'ids_suspects': suspects}


@marketplace_pro_bp.route('/marketplace/api/conversations/<int:cid>/bouclier')
@connecte
def api_bouclier(cid):
    moi = _moi()
    conv = _conversation_du_user(cid, moi)
    if conv.acheteur_id != moi.id:                    # le Bouclier protège l'acheteur : rien pour le vendeur
        return _json(alerte=None)
    return _json(alerte=_analyser_discussion(_messages_visibles(conv, moi.id), moi.id))


@marketplace_pro_bp.route('/marketplace/api/signalement', methods=['POST'])
@connecte
def api_signaler():
    """Corps envoyé par la modale : {type: annonce|utilisateur|message, conversation_id, message_id, motif, description}.
    La cible est déduite de la conversation côté serveur : on ne croit pas les identifiants du navigateur."""
    moi = _moi()
    d = request.get_json(silent=True) or {}
    if d.get('motif') not in MOTIFS_SIGNALEMENT:
        raise ErreurMetier('Motif invalide.')
    try:
        conv = _conversation_du_user(int(d.get('conversation_id') or 0), moi)
    except (TypeError, ValueError):
        raise ErreurMetier('Conversation invalide.')
    type_ = d.get('type')
    if type_ == 'annonce':
        if not conv.annonce_id:
            raise ErreurMetier('Annonce introuvable.', 404)
        cible_type, cible_id = 'annonce', conv.annonce_id
    elif type_ == 'message':
        m = db.session.get(MkMessage, int(d.get('message_id') or 0))
        if not m or m.conversation_id != conv.id or m.expediteur_id == moi.id or m.systeme:
            raise ErreurMetier('Message introuvable.', 404)
        cible_type, cible_id = 'message', m.id
    elif type_ in ('utilisateur', 'user'):
        cible_type, cible_id = 'user', conv.autre_id(moi.id)
    else:
        raise ErreurMetier('Type de signalement invalide.')
    deja = MkSignalement.query.filter_by(auteur_id=moi.id, cible_type=cible_type, cible_id=cible_id, motif=d['motif'], statut='ouvert').first()
    if not deja:
        db.session.add(MkSignalement(auteur_id=moi.id, cible_type=cible_type, cible_id=cible_id, motif=d['motif'],
                                     description=(d.get('description') or '').strip()[:500], conversation_id=conv.id))
        db.session.commit()
    return _json(message='Merci, votre signalement a été transmis à notre équipe.')


# =============================================================================
# Paiement sécurisé (séquestre)
# =============================================================================
def _corps():
    return request.get_json(silent=True) or request.form or {}


def _tx_id():
    try:
        return int(_corps().get('transaction_id'))
    except (TypeError, ValueError):
        raise ErreurMetier('transaction_id manquant ou invalide.')


@marketplace_pro_bp.route('/api/paiement/initier', methods=['POST'])
@connecte
def paiement_initier():
    c = _corps()
    try:
        annonce_id = int(c.get('annonce_id'))
    except (TypeError, ValueError):
        raise ErreurMetier('annonce_id manquant ou invalide.')
    tx, lien = escrow.initier_paiement(_moi(), annonce_id, (c.get('passerelle') or 'fapshi').lower())
    return _json(transaction=escrow.serialiser(tx, _moi().id), lien_paiement=lien)


@marketplace_pro_bp.route('/api/paiement/webhook', methods=['POST'])
def paiement_webhook():
    """Webhook générique. Fapshi appelle déjà TON /fapshi-webhook (voir BRANCHEMENT.md) ; cette route sert si tu
    configures une URL dédiée. Le contenu n'est jamais cru : on re-vérifie chez la passerelle."""
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return _json(False, 400, message='Corps JSON attendu.')
    trans_id = payload.get('transId')
    if isinstance(trans_id, str) and trans_id:
        try:
            escrow.traiter_webhook_fapshi(trans_id)
        except Exception:
            current_app.logger.exception('Webhook séquestre')
            return _json(False, 500, message='Erreur de traitement.')      # la passerelle réessaiera
    return _json()                                                          # 200 même si inconnu : pas d'oracle


@marketplace_pro_bp.route('/marketplace/paiement/retour')
def paiement_retour():
    """Retour de l'acheteur après la page de paiement : vérification immédiate, puis retour dans la discussion."""
    tx = Transaction.query.filter_by(reference=request.args.get('ref', '')).first()
    if not tx:
        return redirect(url_for('main.marketplace'))
    try:
        escrow.verifier_et_appliquer(tx)
    except Exception:
        current_app.logger.exception('Retour paiement')
    db.session.refresh(tx)
    if tx.conversation_id:
        return redirect(url_for('marketplace_pro.messages', conversation_id=tx.conversation_id))
    return redirect(url_for('main.marketplace'))


@marketplace_pro_bp.route('/api/paiement/confirmer-preparation', methods=['POST'])
@connecte
def paiement_preparation():
    tx = escrow.declarer_preparation(_moi().id, _tx_id())
    return _json(transaction=escrow.serialiser(tx, _moi().id))


@marketplace_pro_bp.route('/api/paiement/valider-reception', methods=['POST'])
@connecte
def paiement_valider_reception():
    tx = escrow.liberer_fonds(_moi().id, _tx_id())
    return _json(transaction=escrow.serialiser(tx, _moi().id))


@marketplace_pro_bp.route('/api/paiement/litige', methods=['POST'])
@connecte
def paiement_litige():
    c = _corps()
    tx = escrow.ouvrir_litige(_moi().id, _tx_id(), c.get('motif'), c.get('description', ''))
    return _json(transaction=escrow.serialiser(tx, _moi().id))


@marketplace_pro_bp.route('/api/paiement/litige/<int:tx_id>/resoudre', methods=['POST'])
@connecte
def paiement_resoudre_litige(tx_id):
    moi = _moi()
    if not _admin(moi):
        return _json(False, 403, message='Accès réservé aux administrateurs.')
    c = _corps()
    tx = escrow.resoudre_litige(moi.id, tx_id, c.get('decision'), c.get('note', ''))
    return _json(transaction=escrow.serialiser(tx, moi.id))


@marketplace_pro_bp.route('/api/paiement/transactions')
@connecte
def paiement_transactions():
    moi = _moi()
    q = Transaction.query.filter(or_(Transaction.acheteur_id == moi.id, Transaction.vendeur_id == moi.id))
    if request.args.get('annonce_id', type=int):
        q = q.filter(Transaction.annonce_id == request.args.get('annonce_id', type=int))
    return _json(transactions=[escrow.serialiser(t, moi.id) for t in q.order_by(Transaction.date_creation.desc()).limit(100)])


@marketplace_pro_bp.route('/api/portefeuille')
@connecte
def portefeuille():
    moi = _moi()
    mouvements = MouvementPortefeuille.query.filter_by(user_id=moi.id).order_by(MouvementPortefeuille.id.desc()).limit(50).all()
    return _json(solde=escrow.solde_de(moi.id), devise='XAF',
                 mouvements=[{'type': m.type, 'montant': m.montant, 'solde_apres': m.solde_apres,
                              'transaction_id': m.transaction_id, 'date': _iso(m.date)} for m in mouvements])


# =============================================================================
# Messagerie privée : routes appelées par messagerie.html mais absentes de routes.py
# =============================================================================
def ids_messages_caches_pour(user_id):
    """IDs de messages à cacher à `user_id` : supprimés « pour moi » par lui + supprimés « pour tous » dans ses échanges.
    (Remplace le corps de ta fonction _ids_messages_caches_pour qui renvoyait set().)"""
    lignes = (db.session.query(MessageSuppression.message_id)
              .join(Message, Message.id == MessageSuppression.message_id)
              .filter(or_(and_(MessageSuppression.pour_tous.is_(False), MessageSuppression.user_id == user_id),
                          and_(MessageSuppression.pour_tous.is_(True),
                               or_(Message.expediteur_id == user_id, Message.destinataire_id == user_id)))).all())
    return {r[0] for r in lignes}


def _message_de_la_conversation(mid, moi):
    m = db.session.get(Message, mid)
    if not m or moi.id not in (m.expediteur_id, m.destinataire_id) or m.id in ids_messages_caches_pour(moi.id):
        raise ErreurMetier('Message introuvable.', 404)
    return m


@marketplace_pro_bp.route('/message/<int:mid>/supprimer-pour-moi', methods=['POST'])
@connecte
def message_supprimer_pour_moi(mid):
    moi = _moi()
    m = _message_de_la_conversation(mid, moi)
    if not MessageSuppression.query.filter_by(message_id=m.id, user_id=moi.id).first():
        db.session.add(MessageSuppression(message_id=m.id, user_id=moi.id, pour_tous=False))
        db.session.commit()
    return _json()


@marketplace_pro_bp.route('/message/<int:mid>/supprimer-pour-tous', methods=['POST'])
@connecte
def message_supprimer_pour_tous(mid):
    moi = _moi()
    m = _message_de_la_conversation(mid, moi)
    if m.expediteur_id != moi.id:
        raise ErreurMetier("Seul l'expéditeur peut supprimer ce message pour tous.", 403)
    fichier = m.media_url
    existante = MessageSuppression.query.filter_by(message_id=m.id, user_id=moi.id).first()
    if existante:
        existante.pour_tous = True
    else:
        db.session.add(MessageSuppression(message_id=m.id, user_id=moi.id, pour_tous=True))
    m.contenu, m.media_url = None, None       # le contenu disparaît vraiment de la base
    db.session.commit()
    if fichier:
        chemin = os.path.join(current_app.root_path, 'static', 'uploads', 'messages', fichier)
        if os.path.isfile(chemin):
            try:
                os.remove(chemin)
            except OSError:
                pass
    escrow.emettre(m.destinataire_id, 'message:deleted', {'message_id': m.id})
    return _json()


def _peut_ecrire(moi, dest):
    """Mêmes règles que ton envoyer_message : blocage dans les deux sens + réglage « amis uniquement »."""
    if _blocage_entre(moi.id, dest.id):
        return False
    if dest.message_permission == 'amis':
        return DemandeAmitie.query.filter(DemandeAmitie.statut == 'acceptee', or_(
            and_(DemandeAmitie.emetteur_id == moi.id, DemandeAmitie.recepteur_id == dest.id),
            and_(DemandeAmitie.emetteur_id == dest.id, DemandeAmitie.recepteur_id == moi.id))).first() is not None
    return True


@marketplace_pro_bp.route('/message/<int:mid>/partager', methods=['POST'])
@connecte
def message_partager(mid):
    """Transfère un message (et son fichier, copié) à jusqu'à 20 contacts : {destinataires: [id, …]}."""
    moi = _moi()
    m = _message_de_la_conversation(mid, moi)
    ids = (request.get_json(silent=True) or {}).get('destinataires') or []
    if not isinstance(ids, list) or not ids:
        raise ErreurMetier('Aucun destinataire.')
    dossier = os.path.join(current_app.root_path, 'static', 'uploads', 'messages')
    envoyes = 0
    for uid in {int(i) for i in ids[:20] if str(i).isdigit()}:
        dest = db.session.get(User, uid)
        if not dest or dest.id == moi.id or not _peut_ecrire(moi, dest):
            continue                          # bloqué / « amis uniquement » : on saute sans interrompre les autres
        nouveau_fichier = None
        if m.media_url:
            source = os.path.join(dossier, m.media_url)
            if not os.path.isfile(source):
                continue
            nouveau_fichier = '%s_%s' % (uuid.uuid4().hex, m.media_filename or 'fichier')
            shutil.copyfile(source, os.path.join(dossier, nouveau_fichier))   # chaque message a SON fichier
        db.session.add(Message(expediteur_id=moi.id, destinataire_id=dest.id, contenu=m.contenu, media_url=nouveau_fichier,
                               media_type=m.media_type, media_filename=m.media_filename))
        envoyes += 1
    if not envoyes:
        raise ErreurMetier("Le message n'a pu être transmis à aucun contact.", 403)
    db.session.commit()
    return _json(nb_envoyes=envoyes)