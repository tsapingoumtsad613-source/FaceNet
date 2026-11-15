"""
escrow_service.py — Séquestre (escrow) du Marketplace.

    en_attente ──(paiement vérifié chez Fapshi)──▶ sous_sequestre
        │                                            │   │
        └─(échec / expiration)─▶ echouee             │   └─(litige)─▶ en_litige ─┬─▶ validee    (admin : libérer)
                                                     │                           └─▶ remboursee (admin : rembourser)
                                                     └─(acheteur confirme la remise, ou délai écoulé)─▶ validee

Règles de sécurité :
  * le montant vient TOUJOURS de l'annonce (côté serveur), jamais du navigateur ;
  * un paiement n'est « confirmé » qu'après interrogation de Fapshi (module `fapshi` de ton projet,
    avec ta clé secrète) : un faux webhook ne peut rien débloquer ;
  * chaque transition relit la transaction avec un verrou et vérifie son statut de départ :
    rejouer un webhook ou double-cliquer ne crédite JAMAIS deux fois ;
  * chaque mouvement d'argent est écrit dans le journal MouvementPortefeuille.
"""
import logging
import os
import uuid
from datetime import datetime, timedelta

from flask import url_for
from sqlalchemy import select

from extensions import db
from marketplace_models import (MkConversation, MkMessage, MouvementPortefeuille, PortefeuilleUtilisateur,
                                Transaction, MkSignalement)
from models import Annonce, User

log = logging.getLogger(__name__)

# ---- Réglages (modifiables par variables d'environnement / fichier .env, que tu charges déjà) ----
PRIX_MIN = 100
COMMISSION_POURCENT = float(os.environ.get('MK_COMMISSION_POURCENT', '0'))        # 0 = aucune commission
EXPIRATION_PAIEMENT_MIN = int(os.environ.get('MK_EXPIRATION_PAIEMENT_MIN', '30'))
LIBERATION_AUTO_JOURS = int(os.environ.get('MK_LIBERATION_AUTO_JOURS', '7'))
SIMULATION = os.environ.get('MK_PAIEMENT_SIMULATION') == '1'                      # JAMAIS en production

TX_EN_ATTENTE, TX_SOUS_SEQUESTRE, TX_VALIDEE = 'en_attente', 'sous_sequestre', 'validee'
TX_EN_LITIGE, TX_REMBOURSEE, TX_ECHOUEE = 'en_litige', 'remboursee', 'echouee'
TX_ACTIVES = (TX_EN_ATTENTE, TX_SOUS_SEQUESTRE, TX_EN_LITIGE)
MOTIFS_LITIGE = ('non_recu', 'non_conforme', 'fraude', 'autre')


class ErreurMetier(Exception):
    def __init__(self, message, code=400):
        super().__init__(message)
        self.message, self.code = message, code


def fmt_prix(n):
    return '{:,}'.format(int(n or 0)).replace(',', ' ') + ' FCFA'


def _iso(dt):
    return dt.isoformat() + 'Z' if dt else ''


# --------------------------------------------------------------------------- temps réel (ton sockets.py)
def emettre(user_id, evenement, charge):
    """Pousse un événement dans la salle `user_<id>` de ton sockets.py. N'échoue jamais."""
    try:
        from sockets import socketio
        socketio.emit(evenement, charge, to='user_%s' % user_id)
    except Exception:
        log.exception('Émission Socket.IO impossible')


# --------------------------------------------------------------------------- conversations
def conversation_pour(annonce, acheteur_id, creer=True):
    conv = MkConversation.query.filter_by(annonce_id=annonce.id, acheteur_id=acheteur_id).first()
    if not conv and creer:
        conv = MkConversation(annonce_id=annonce.id, acheteur_id=acheteur_id, vendeur_id=annonce.user_id)
        db.session.add(conv)
        db.session.flush()
    return conv


def poster_message(conv, expediteur_id, contenu, systeme=False):
    """Ajoute un message, fait réapparaître la discussion chez les deux participants, prévient en direct."""
    m = MkMessage(conversation_id=conv.id, expediteur_id=expediteur_id, contenu=contenu.strip(), systeme=systeme,
                  lu=bool(systeme))
    conv.masquee_acheteur = conv.masquee_vendeur = False
    conv.dernier_message_at = datetime.utcnow()
    db.session.add(m)
    db.session.commit()
    for uid in (conv.acheteur_id, conv.vendeur_id):
        emettre(uid, 'mk:message', {'conversation_id': conv.id, 'message_id': m.id})
    return m


def _notifier(tx, texte):
    """Message système dans la discussion + événement temps réel aux deux parties."""
    annonce = db.session.get(Annonce, tx.annonce_id)
    conv = conversation_pour(annonce, tx.acheteur_id)
    tx.conversation_id = conv.id
    db.session.commit()
    poster_message(conv, tx.acheteur_id, '💳 ' + texte, systeme=True)
    for uid in (tx.acheteur_id, tx.vendeur_id):
        emettre(uid, 'mk:transaction', serialiser(tx, uid))


def serialiser(tx, pour_user_id=None):
    return {
        'id': tx.id, 'reference': tx.reference, 'statut': tx.statut, 'annonce_id': tx.annonce_id,
        'conversation_id': tx.conversation_id, 'montant': tx.montant, 'montant_txt': fmt_prix(tx.montant),
        'frais': tx.frais, 'montant_net': tx.montant_net, 'passerelle': tx.passerelle,
        'role': None if pour_user_id is None else ('acheteur' if pour_user_id == tx.acheteur_id else 'vendeur'),
        'date_creation': _iso(tx.date_creation), 'date_paiement': _iso(tx.date_paiement),
        'date_preparation': _iso(tx.date_preparation), 'liberation_auto_le': _iso(tx.liberation_auto_le),
        'date_validation': _iso(tx.date_validation), 'motif_litige': tx.motif_litige,
    }


# --------------------------------------------------------------------------- portefeuille
def solde_de(user_id):
    w = db.session.get(PortefeuilleUtilisateur, user_id)
    return int(w.solde) if w else 0


def _crediter(user_id, montant, type_, tx):
    w = db.session.get(PortefeuilleUtilisateur, user_id)
    if not w:
        w = PortefeuilleUtilisateur(user_id=user_id, solde=0)
        db.session.add(w)
        db.session.flush()
    w.solde = int(w.solde) + int(montant)
    db.session.add(MouvementPortefeuille(user_id=user_id, transaction_id=tx.id, type=type_, montant=montant, solde_apres=w.solde))


def _verrouiller(tx_id):
    """Relit la transaction avec verrou de ligne (effectif sur PostgreSQL/MySQL ; SQLite sérialise déjà les écritures)."""
    tx = db.session.execute(select(Transaction).where(Transaction.id == tx_id).with_for_update()).scalar_one_or_none()
    if not tx:
        raise ErreurMetier('Transaction introuvable.', 404)
    return tx


# --------------------------------------------------------------------------- passerelle Fapshi (module de ton projet)
def _fapshi_initier(tx, acheteur, url_retour):
    """Utilise TON module `fapshi` (le même que pour les forfaits) : initiate_pay -> {statusCode, transId, link}."""
    import fapshi
    reponse = fapshi.initiate_pay({
        'amount': int(tx.montant),
        'email': acheteur.email or 'user%s@facenet.cm' % acheteur.id,
        'userId': str(acheteur.id),
        'externalId': tx.reference,
        'redirectUrl': url_retour,
        'message': 'Achat Marketplace FaceNet #%s' % tx.annonce_id,
    })
    if reponse.get('statusCode') != 200 or not reponse.get('transId') or not reponse.get('link'):
        log.error('Fapshi initiate_pay refusé : %s', reponse)
        raise ErreurMetier("Le service de paiement est momentanément indisponible.", 502)
    return reponse['transId'], reponse['link']


def _verifier_passerelle(tx):
    """Retourne ('succes'|'echec'|'attente', montant_confirme_ou_None)."""
    if tx.passerelle == 'simulation':
        return ('succes', None) if SIMULATION else ('echec', None)
    import fapshi
    try:
        ev = fapshi.payment_status(tx.reference_passerelle)
    except Exception:
        log.exception('Fapshi injoignable (vérification)')
        return 'attente', None
    if ev.get('statusCode') != 200:
        return 'attente', None
    statut = ev.get('status')
    if statut == 'SUCCESSFUL':
        return 'succes', ev.get('amount')
    if statut in ('FAILED', 'EXPIRED'):
        return 'echec', ev.get('amount')
    return 'attente', ev.get('amount')


# --------------------------------------------------------------------------- 1. initiation
def initier_paiement(acheteur, annonce_id, passerelle='fapshi'):
    annonce = db.session.get(Annonce, annonce_id)
    if not annonce:
        raise ErreurMetier('Annonce introuvable.', 404)
    if annonce.user_id == acheteur.id:
        raise ErreurMetier('Vous ne pouvez pas acheter votre propre annonce.')
    if annonce.statut == 'vendu':
        raise ErreurMetier('Cet article est déjà vendu.', 409)
    if (annonce.prix or 0) < PRIX_MIN:
        raise ErreurMetier('Montant inférieur au minimum de paiement.')
    if passerelle in ('mobile_money', 'orange_money', 'mtn', 'fapshi', None):
        passerelle = 'fapshi'      # Orange / MTN Cameroun passent par la page hébergée Fapshi
    elif passerelle == 'simulation':
        if not SIMULATION:
            raise ErreurMetier('Passerelle de simulation désactivée.')
    elif passerelle == 'notchpay':
        raise ErreurMetier("Notch Pay n'est pas encore branché sur le séquestre.", 501)
    elif passerelle == 'paypal':
        raise ErreurMetier("PayPal n'est pas disponible. Utilisez Mobile Money ou Orange Money.", 501)
    else:
        raise ErreurMetier('Passerelle de paiement inconnue.')

    limite = datetime.utcnow() - timedelta(minutes=EXPIRATION_PAIEMENT_MIN)
    for t in Transaction.query.filter(Transaction.annonce_id == annonce.id, Transaction.statut.in_(TX_ACTIVES)).all():
        if t.statut == TX_EN_ATTENTE and t.date_creation < limite:
            verifier_et_appliquer(t)           # périmé : dernière vérification, puis clôture
            db.session.refresh(t)
            if t.statut == TX_EN_ATTENTE:
                _echouer(t.id)
            continue
        if t.statut == TX_EN_ATTENTE and t.acheteur_id == acheteur.id and t.lien_paiement:
            return t, t.lien_paiement          # même acheteur : on réutilise son lien (pas de doublon)
        raise ErreurMetier('Un paiement est déjà en cours pour cet article.', 409)

    frais = int(round(annonce.prix * COMMISSION_POURCENT / 100.0))
    tx = Transaction(reference='mk_' + uuid.uuid4().hex[:20], acheteur_id=acheteur.id, vendeur_id=annonce.user_id,
                     annonce_id=annonce.id, montant=annonce.prix, frais=frais, montant_net=annonce.prix - frais,
                     statut=TX_EN_ATTENTE, passerelle=passerelle)
    db.session.add(tx)
    db.session.flush()
    url_retour = url_for('marketplace_pro.paiement_retour', ref=tx.reference, _external=True)
    try:
        if passerelle == 'simulation':
            tx.reference_passerelle, tx.lien_paiement = 'SIM-' + tx.reference, url_retour
        else:
            tx.reference_passerelle, tx.lien_paiement = _fapshi_initier(tx, acheteur, url_retour)
    except Exception:
        db.session.rollback()                  # rien n'est conservé si la passerelle refuse
        raise
    db.session.commit()
    return tx, tx.lien_paiement


# --------------------------------------------------------------------------- 2. confirmation (webhook / retour / planifié)
def verifier_et_appliquer(tx):
    """Interroge la passerelle et applique le résultat. Idempotent."""
    if tx.statut != TX_EN_ATTENTE or not tx.reference_passerelle:
        return tx.statut
    resultat, montant = _verifier_passerelle(tx)
    if resultat == 'succes':
        _confirmer_paiement(tx.id, montant)
    elif resultat == 'echec':
        _echouer(tx.id)
    db.session.refresh(tx)
    return tx.statut


def traiter_webhook_fapshi(trans_id):
    """Appelée par ton /fapshi-webhook existant : ignore silencieusement les paiements qui ne sont pas du Marketplace."""
    tx = Transaction.query.filter_by(reference_passerelle=trans_id).first()
    if tx:
        verifier_et_appliquer(tx)
    return tx is not None


def _confirmer_paiement(tx_id, montant_confirme):
    tx = _verrouiller(tx_id)
    if tx.statut != TX_EN_ATTENTE:
        return                                 # déjà traité (webhook rejoué)
    if montant_confirme is not None and int(montant_confirme) != int(tx.montant):
        log.error('Montant incohérent tx=%s attendu=%s reçu=%s : NON confirmé', tx.reference, tx.montant, montant_confirme)
        db.session.rollback()
        return
    annonce = db.session.get(Annonce, tx.annonce_id)
    autre = Transaction.query.filter(Transaction.annonce_id == tx.annonce_id, Transaction.id != tx.id,
                                     Transaction.statut.in_([TX_SOUS_SEQUESTRE, TX_VALIDEE, TX_EN_LITIGE])).first()
    tx.date_paiement = datetime.utcnow()
    if autre or annonce.statut == 'vendu':
        # Cas rare : article vendu entre-temps. L'argent est reçu : on le rend sur le portefeuille de l'acheteur.
        tx.statut = TX_REMBOURSEE
        tx.resolution_litige = 'Article indisponible au moment du paiement : remboursement automatique.'
        _crediter(tx.acheteur_id, tx.montant, 'remboursement', tx)
        db.session.commit()
        _notifier(tx, "Paiement reçu mais l'article n'est plus disponible : %s remboursés sur votre portefeuille." % fmt_prix(tx.montant))
        return
    tx.statut = TX_SOUS_SEQUESTRE
    annonce.statut = 'reserve'
    db.session.commit()
    _notifier(tx, "Paiement de %s reçu et placé sous séquestre. Le vendeur peut préparer l'article ; les fonds ne lui "
                  "seront versés qu'après votre confirmation de remise." % fmt_prix(tx.montant))


def _echouer(tx_id):
    tx = _verrouiller(tx_id)
    if tx.statut != TX_EN_ATTENTE:
        return
    tx.statut = TX_ECHOUEE
    db.session.commit()
    _notifier(tx, "Le paiement n'a pas abouti (refusé ou expiré). Aucun montant n'a été débité.")


# --------------------------------------------------------------------------- 3. préparation par le vendeur
def declarer_preparation(vendeur_id, tx_id):
    tx = _verrouiller(tx_id)
    if tx.vendeur_id != vendeur_id:
        raise ErreurMetier('Transaction introuvable.', 404)
    if tx.statut != TX_SOUS_SEQUESTRE:
        raise ErreurMetier("Le paiement n'est pas sous séquestre.", 409)
    if tx.date_preparation:
        return tx
    tx.date_preparation = datetime.utcnow()
    tx.liberation_auto_le = tx.date_preparation + timedelta(days=LIBERATION_AUTO_JOURS)
    db.session.commit()
    _notifier(tx, "Le vendeur a confirmé préparer l'article. Confirmez la réception dès que vous l'avez en main ; sans "
                  "action de votre part, les fonds seront libérés automatiquement le %s." % tx.liberation_auto_le.strftime('%d/%m/%Y'))
    return tx


# --------------------------------------------------------------------------- 4. libération
def liberer_fonds(user_id, tx_id, automatique=False, par_admin=False):
    tx = _verrouiller(tx_id)
    if not (automatique or par_admin or tx.acheteur_id == user_id):
        raise ErreurMetier("Seul l'acheteur peut confirmer la réception.", 403)
    if tx.statut == TX_EN_LITIGE and not par_admin:
        raise ErreurMetier('Un litige est ouvert : les fonds sont bloqués.', 409)
    if tx.statut != TX_SOUS_SEQUESTRE and not (par_admin and tx.statut == TX_EN_LITIGE):
        raise ErreurMetier('Ces fonds ne peuvent pas être libérés (statut : %s).' % tx.statut, 409)
    tx.statut = TX_VALIDEE
    tx.date_validation = datetime.utcnow()
    tx.liberation_auto_le = None
    _crediter(tx.vendeur_id, tx.montant_net, 'vente', tx)
    annonce = db.session.get(Annonce, tx.annonce_id)
    if annonce:
        annonce.statut = 'vendu'
    db.session.commit()
    _notifier(tx, 'Remise confirmée : %s ont été versés au vendeur. Transaction terminée.' % fmt_prix(tx.montant_net))
    return tx


# --------------------------------------------------------------------------- 5. litige
def ouvrir_litige(user_id, tx_id, motif, description=''):
    if motif not in MOTIFS_LITIGE:
        raise ErreurMetier('Motif de litige invalide.')
    tx = _verrouiller(tx_id)
    if user_id not in (tx.acheteur_id, tx.vendeur_id):
        raise ErreurMetier('Transaction introuvable.', 404)
    if tx.statut != TX_SOUS_SEQUESTRE:
        raise ErreurMetier('Un litige ne peut être ouvert que sur des fonds sous séquestre.', 409)
    tx.statut = TX_EN_LITIGE
    tx.date_litige = datetime.utcnow()
    tx.litige_ouvert_par_id = user_id
    tx.motif_litige = motif
    tx.description_litige = (description or '').strip()[:1000]
    tx.liberation_auto_le = None               # bloque la libération automatique
    if motif == 'fraude':                      # alimente aussi la file de modération
        db.session.add(MkSignalement(auteur_id=user_id, cible_type='annonce', cible_id=tx.annonce_id, motif='fraude',
                                     description='Litige transaction %s' % tx.reference, conversation_id=tx.conversation_id))
    db.session.commit()
    _notifier(tx, "Litige ouvert (%s). Les fonds restent bloqués jusqu'à décision de l'équipe FaceNet." % motif.replace('_', ' '))
    return tx


def resoudre_litige(admin_id, tx_id, decision, note=''):
    """decision = 'liberer' (vendeur payé) ou 'rembourser' (acheteur recrédité sur son portefeuille)."""
    if decision not in ('liberer', 'rembourser'):
        raise ErreurMetier('Décision invalide.')
    tx = _verrouiller(tx_id)
    if tx.statut != TX_EN_LITIGE:
        raise ErreurMetier("Cette transaction n'est pas en litige.", 409)
    tx.resolution_litige = (note or '').strip()[:1000]
    if decision == 'liberer':
        db.session.commit()
        return liberer_fonds(admin_id, tx_id, par_admin=True)
    tx.statut = TX_REMBOURSEE
    _crediter(tx.acheteur_id, tx.montant, 'remboursement', tx)
    annonce = db.session.get(Annonce, tx.annonce_id)
    if annonce and annonce.statut == 'reserve':
        annonce.statut = 'disponible'
    db.session.commit()
    _notifier(tx, 'Litige tranché en faveur de l\'acheteur : %s remboursés sur son portefeuille.' % fmt_prix(tx.montant))
    return tx


# --------------------------------------------------------------------------- 6. tâche périodique
def traiter_transactions_planifiees():
    """Clôt les paiements périmés et libère les séquestres dont le délai est écoulé.
    Appelée toutes les 60 s par ton `verifier_expirations_periodiquement` (app.py)."""
    stats = {'verifies': 0, 'expires': 0, 'liberes': 0}
    limite = datetime.utcnow() - timedelta(minutes=EXPIRATION_PAIEMENT_MIN)
    for tx in Transaction.query.filter(Transaction.statut == TX_EN_ATTENTE).all():
        statut = verifier_et_appliquer(tx)
        stats['verifies'] += 1
        if statut == TX_EN_ATTENTE and tx.date_creation < limite:
            _echouer(tx.id)
            stats['expires'] += 1
    for tx in Transaction.query.filter(Transaction.statut == TX_SOUS_SEQUESTRE, Transaction.liberation_auto_le.isnot(None),
                                       Transaction.liberation_auto_le <= datetime.utcnow()).all():
        liberer_fonds(None, tx.id, automatique=True)
        stats['liberes'] += 1
    return stats