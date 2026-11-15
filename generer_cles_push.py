"""Génère les clés VAPID pour les notifications push d'appel.
Usage :  pip install cryptography pywebpush   puis   python generer_cles_push.py
Copiez les 3 lignes affichées dans votre fichier .env (jamais dans le code, jamais sur GitHub)."""
import base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

def b64(b): return base64.urlsafe_b64encode(b).rstrip(b'=').decode()

cle = ec.generate_private_key(ec.SECP256R1())
prive = cle.private_numbers().private_value.to_bytes(32, 'big')
public = cle.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
print("VAPID_PUBLIC_KEY=" + b64(public))
print("VAPID_PRIVATE_KEY=" + b64(prive))
print("VAPID_SUBJECT=mailto:votre-adresse@exemple.com")