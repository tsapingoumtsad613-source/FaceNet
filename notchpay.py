# notchpay.py
import hashlib
import hmac
import os
import re
import requests

# Clés officielles Notch Pay (Mode Live)
NOTCHPAY_PUBLIC_KEY = os.environ.get("NOTCHPAY_PUBLIC_KEY", "pk.JJndjBAWGqpSxZ6XI0RnE36wP1U7mIGMmuowfSrtb7Nmwo28uSwV819LIaDhuel8BEszHfaloGizKZQyZrrpw506JAKkXlP6JiS1a6Zz5rQdWqzosR0C8xAobo7Bq")
NOTCHPAY_PRIVATE_KEY = os.environ.get("NOTCHPAY_PRIVATE_KEY", "sk.eV37bjeww7wIzL7FiHqhsPMk9nswsQryXqa2P3qzytFawl3lqrtDkBYastl8pss7KhiwKJ9YlDD1gEOqQ8YsOw8Nc7iPTmT9Sxj3jinl3upIyehzzF3KXKkOUU1st")
NOTCHPAY_HASH_KEY = os.environ.get("NOTCHPAY_HASH_KEY", "hsk.k7iAAiloXSmHmLX3srWpAOIzjaUeNDdAg0391IALGoW8XPC71buFTeiHcTubdvidsspn5y4x0fiB4J24xU56Q4V26WEhSEFaG4RPrG7kpWG8YRgtwcbbMRDBzq1lh")

# Grille tarifaire officielle FaceNet
FORFAITS_FACENET = {
    "standard": {"nom": "Forfait Standard", "prix": 4500},
    "premium": {"nom": "Forfait Premium", "prix": 12000},
    "max": {"nom": "Forfait Max", "prix": 78000},
    "max_plus": {"nom": "Forfait Max Plus (Membre Ultra)", "prix": 100000},
}


def _entetes(ancien_format=False):
    """En-têtes API Notch Pay (clé publique, selon la documentation officielle).
    ancien_format=True : ancien format du projet, gardé en secours."""
    cle = f"N-PubKey {NOTCHPAY_PRIVATE_KEY}" if ancien_format else NOTCHPAY_PUBLIC_KEY
    return {
        "Authorization": cle,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def initier_paiement_notchpay(email, forfait_key, channel="card", phone="", callback=None, currency="XAF"):
    """Initie un paiement Notch Pay (Cartes bancaires & Mobile Money)."""
    if forfait_key not in FORFAITS_FACENET:
        return {"success": False, "error": "Forfait sélectionné invalide."}

    forfait_info = FORFAITS_FACENET[forfait_key]
    montant = forfait_info["prix"]
    nom_forfait = forfait_info["nom"]

    payload = {
        "email": email,
        "amount": montant,
        "currency": currency if currency in ("XAF", "XOF") else "XAF",
        "description": f"FaceNet : {nom_forfait}",
        "reference": f"FN-NP-{forfait_key}-{os.urandom(4).hex()}",
    }

    if callback:
        payload["callback"] = callback

    if channel != "card" and phone:
        payload["channel"] = channel
        payload["phone"] = phone

    headers = _entetes()

    try:
        response = requests.post(
            "https://api.notchpay.co/payments/initialize",
            json=payload,
            headers=headers,
            timeout=25,
        )
        if response.status_code in (401, 403):
            # Secours : ancien format d'authentification du projet
            response = requests.post(
                "https://api.notchpay.co/payments/initialize",
                json=payload,
                headers=_entetes(ancien_format=True),
                timeout=25,
            )
        res_data = response.json()

        if response.status_code in [200, 201] or res_data.get("status") in [
            "accepted",
            "success",
        ]:
            return {
                "success": True,
                "payment_url": res_data.get("authorization_url"),
                "reference": (res_data.get("transaction") or {}).get("reference")
                or res_data.get("reference")
                or payload["reference"],
                "montant": montant,
                "forfait": nom_forfait,
            }
        else:
            return {
                "success": False,
                "error": res_data.get(
                    "message", "Échec d'initialisation Notch Pay."
                ),
            }

    except Exception as e:
        return {"success": False, "error": f"Erreur de connexion : {str(e)}"}


def verifier_paiement_notchpay(reference):
    """Vérifie côté serveur le statut d'un paiement Notch Pay.
    Retourne {"success": bool, "status": str|None, "amount": nombre|None}.
    Le paiement est réussi quand status == "complete"."""
    if not reference or not re.match(r"^[A-Za-z0-9._-]{4,100}$", str(reference)):
        return {"success": False, "status": None, "amount": None}
    url = f"https://api.notchpay.co/payments/{reference}"
    try:
        r = requests.get(url, headers=_entetes(), timeout=25)
        if r.status_code in (401, 403):
            r = requests.get(url, headers=_entetes(ancien_format=True), timeout=25)
        data = r.json()
    except Exception:
        return {"success": False, "status": None, "amount": None}
    tx = data.get("transaction") or data.get("payment") or {}
    return {
        "success": r.status_code == 200,
        "status": tx.get("status"),
        "amount": tx.get("amount"),
    }


def verifier_signature_webhook(raw_body, signature_recue):
    """Vérifie la signature HMAC reçue lors du Webhook Notch Pay."""
    if not signature_recue or not NOTCHPAY_HASH_KEY:
        return False

    computed_signature = hmac.new(
        NOTCHPAY_HASH_KEY.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()

    return hmac.compare_digest(computed_signature, signature_recue)