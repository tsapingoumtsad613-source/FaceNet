# ============================================================================
# PROPOSITION DE ROUTES — à COPIER dans ton fichier de routes existant
# (celui où se trouve déjà @main_bp.route('/payer/<forfait_type>'))
# ============================================================================
#
# ⚠️ IMPORTANT — LIS CECI AVANT D'INTÉGRER :
#
# Je n'ai pas accès à ton vrai fichier de routes, ni à ton modèle User, ni à ta
# base de données, ni à un quelconque prestataire de paiement (Mobile Money,
# carte bancaire, PayPal). Ce fichier est donc un POINT DE DÉPART propre et
# sécurisé sur les points que je maîtrise (validation des champs, ordre des
# opérations, badge posé seulement après paiement confirmé) — mais il contient
# des `TODO` que TOI (ou ton développeur backend) dois compléter avec les
# vrais noms de tes objets (db, User, blueprint, etc.).
#
# LE POINT LE PLUS IMPORTANT DE TOUT CE FICHIER :
# Sans brancher une vraie API de paiement (CinetPay, PayDunya, Orange Money API,
# MTN MoMo API, Stripe pour les cartes, PayPal SDK...), il est IMPOSSIBLE de
# vérifier informatiquement qu'un paiement a réellement eu lieu. Tant que la
# fonction `confirmer_paiement_aupres_du_prestataire()` plus bas n'est pas
# branchée à ton vrai prestataire, personne ne peut garantir qu'un montant a
# vraiment été débité — même si ce fichier refuse maintenant les paiements
# incomplets ou mal formés. C'est la différence entre "empêcher les erreurs
# évidentes" (ce que ce fichier fait déjà) et "garantir qu'un vrai paiement a
# eu lieu" (ce qui nécessite ton prestataire).
#
# ============================================================================

from datetime import datetime, timedelta
from flask import request, jsonify
from flask_login import login_required, current_user

# TODO : adapte ces imports à ton projet réel
# from app import db, main_bp
# from app.models import User, Paiement  # Paiement = nouvelle table recommandée (voir plus bas)


# ----------------------------------------------------------------------------
# 1) VALIDATION DES CHAMPS DE PAIEMENT
#    -> c'est ici qu'on corrige le problème que tu as repéré : le formulaire
#       n'exigeait pas vraiment un numéro de compte/téléphone valide.
# ----------------------------------------------------------------------------
def valider_champs_paiement(method, phone, card_number, card_billing, paypal_email):
    """Retourne (True, None) si les champs sont cohérents, sinon (False, message_erreur)."""
    if method == 'momo':
        phone = (phone or '').strip()
        if not phone or not phone.isdigit() or len(phone) < 8:
            return False, "Numéro Mobile Money invalide."
    elif method == 'card':
        card_number = (card_number or '').replace(' ', '')
        if not card_number.isdigit() or len(card_number) not in (15, 16):
            return False, "Numéro de carte invalide."
        if not (card_billing or '').strip():
            return False, "Pays de résidence requis pour le paiement par carte."
    elif method == 'paypal':
        paypal_email = (paypal_email or '').strip()
        if '@' not in paypal_email or '.' not in paypal_email.split('@')[-1]:
            return False, "Email PayPal invalide."
    else:
        return False, "Méthode de paiement inconnue."
    return True, None


# ----------------------------------------------------------------------------
# 2) CONFIRMATION RÉELLE AUPRÈS DU PRESTATAIRE — À BRANCHER
# ----------------------------------------------------------------------------
def confirmer_paiement_aupres_du_prestataire(method, amount, phone=None, card_number=None,
                                              card_billing=None, paypal_email=None):
    """
    TODO CRITIQUE : appelle ici l'API réelle de ton prestataire de paiement et
    attends sa confirmation (souvent via un statut de transaction ou un webhook).
    Tant que cette fonction renvoie simplement True, AUCUNE vérification réelle
    n'est faite — c'est un espace réservé, pas une intégration fonctionnelle.

    Exemples de ce qu'il faudrait faire ici selon ton prestataire :
      - Mobile Money (CinetPay / PayDunya / API Orange/MTN) : initier la
        transaction, puis interroger le statut jusqu'à confirmation ou échec.
      - Carte bancaire (Stripe...) : créer un PaymentIntent côté serveur et
        vérifier son statut 'succeeded' — ne jamais faire confiance à un simple
        numéro de carte envoyé tel quel sans passerelle de paiement certifiée
        PCI-DSS (Tsapi ne doit normalement jamais recevoir de numéro de carte
        brut : il faut passer par un champ tokenisé fourni par le prestataire).
      - PayPal : vérifier la capture du paiement via l'API PayPal.
    """
    raise NotImplementedError(
        "Branche ici ton vrai prestataire de paiement avant mise en production. "
        "Sans cela, le badge ne doit jamais être activé automatiquement."
    )


# ----------------------------------------------------------------------------
# 3) ROUTE DE PAIEMENT — le badge n'est posé qu'après confirmation
# ----------------------------------------------------------------------------
@main_bp.route('/paiement/traiter', methods=['POST'])  # TODO: renomme si besoin pour matcher main.process_payment
@login_required
def process_payment():
    amount = request.form.get('amount', '').strip()
    method = request.form.get('method', '').strip()
    phone = request.form.get('phone', '').strip()
    card_number = request.form.get('card_number', '').strip()
    card_billing = request.form.get('card_billing', '').strip()
    paypal_email = request.form.get('paypal_email', '').strip()

    montants_valides = {'4500', '12000', '68000', '112000'}
    if amount not in montants_valides:
        return jsonify(success=False, error="Montant invalide."), 400

    ok, erreur = valider_champs_paiement(method, phone, card_number, card_billing, paypal_email)
    if not ok:
        return jsonify(success=False, error=erreur), 400

    # ⚠️ Le badge n'est posé QUE si cette étape confirme réellement le paiement.
    try:
        paiement_confirme = confirmer_paiement_aupres_du_prestataire(
            method, amount, phone=phone, card_number=card_number,
            card_billing=card_billing, paypal_email=paypal_email
        )
    except NotImplementedError as e:
        # Tant que le prestataire n'est pas branché, on refuse explicitement
        # plutôt que d'activer un badge non payé.
        return jsonify(success=False, error="Le paiement n'a pas pu être confirmé pour le moment."), 502

    if not paiement_confirme:
        return jsonify(success=False, error="Paiement refusé ou non confirmé par le prestataire."), 402

    # ---- À ce stade seulement : paiement réellement confirmé ----
    forfait_par_montant = {'4500': 'standard', '12000': 'premium', '68000': 'max', '112000': 'max_plus'}
    current_user.forfait_type = forfait_par_montant[amount]
    current_user.badge_expire = datetime.utcnow() + timedelta(days=30)

    # Recommandé : conserver une trace du moyen de paiement utilisé (PAS le numéro de
    # carte complet ni les identifiants sensibles — seulement de quoi identifier
    # l'utilisateur en cas de litige, ex. les 4 derniers chiffres, le numéro momo).
    if method == 'momo':
        current_user.dernier_moyen_paiement = f"MoMo •••{phone[-4:]}"
    elif method == 'card':
        current_user.dernier_moyen_paiement = f"Carte •••{card_number[-4:]}"
    elif method == 'paypal':
        current_user.dernier_moyen_paiement = f"PayPal ({paypal_email})"

    db.session.commit()
    return jsonify(success=True)


# ----------------------------------------------------------------------------
# 4) ROUTE PIÈCE D'IDENTITÉ — mise à jour pour accepter recto + verso
# ----------------------------------------------------------------------------
@main_bp.route('/verification/piece-identite', methods=['POST'])  # adapte le blueprint si différent
@login_required
def verification_piece_identite():
    type_piece = request.form.get('type_piece', '')
    # 'document' = ancien champ (recto seul, gardé pour compatibilité) ;
    # 'document_recto' / 'document_verso' = nouveaux champs envoyés par le wizard mis à jour.
    fichier_recto = request.files.get('document_recto') or request.files.get('document')
    fichier_verso = request.files.get('document_verso')

    if not fichier_recto or not fichier_verso:
        return jsonify(success=False, error="Le recto et le verso de la pièce sont tous les deux requis."), 400

    # TODO : sauvegarder les deux fichiers (ex. dans un dossier privé, PAS dans /static/uploads
    # public, car ce sont des pièces d'identité) et lancer ton éventuel contrôle
    # anti-fraude / OCR ici. Exemple :
    # chemin_recto = sauvegarder_document_prive(fichier_recto, current_user.id, 'recto')
    # chemin_verso = sauvegarder_document_prive(fichier_verso, current_user.id, 'verso')
    # current_user.piece_identite_recto = chemin_recto
    # current_user.piece_identite_verso = chemin_verso
    # current_user.piece_identite_type = type_piece
    # db.session.commit()

    return jsonify(success=True)