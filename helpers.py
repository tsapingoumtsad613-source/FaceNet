from datetime import datetime

# Liste ORDONNÉE des 12 avantages possibles. L'ordre ici est aussi l'ordre d'affichage
# dans le tableau comparatif de la page "Avantages du badge".
# Chaque avantage cumule sur le forfait précédent (ex: Premium = tout Standard + 2 nouveaux).
AVANTAGES_INFO = [
    {'cle': 'badge',                'icone': '✔️', 'label': 'Badge Vérifié affiché sur votre profil'},
    {'cle': 'protection',           'icone': '🛡️', 'label': "Protection anti-usurpation d'identité"},
    {'cle': 'stickers',             'icone': '🎨', 'label': 'Stickers et badges exclusifs'},
    {'cle': 'assistance',           'icone': '💬', 'label': 'Assistance client standard'},
    {'cle': 'signalement_prioritaire', 'icone': '🚩', 'label': 'Traitement prioritaire de vos signalements'},
    {'cle': 'profil_mis_en_avant',  'icone': '🚀', 'label': 'Profil mis en avant dans les recherches'},
    {'cle': 'statistiques',         'icone': '📊', 'label': 'Statistiques de profil avancées'},
    {'cle': 'monetisation',         'icone': '💰', 'label': 'Monétisation de votre contenu'},
    {'cle': 'marketplace',          'icone': '🛒', 'label': 'Accès à la Marketplace'},
    {'cle': 'support_5min',         'icone': '⚡', 'label': 'Support VIP sous 5 minutes'},
    {'cle': 'badge_animation',      'icone': '✨', 'label': 'Badge animé premium exclusif'},
    {'cle': 'compte_dedie',         'icone': '🎯', 'label': 'Gestionnaire de compte dédié'},
]

# Dictionnaire des avantages par forfait (cumulatif : standard=5, premium=7, max=9, max_plus=12)
# Cela te permet de modifier facilement les avantages sans toucher au code principal
FORFAIT_AVANTAGES = {
    'standard': [a['cle'] for a in AVANTAGES_INFO[0:5]],
    'premium': [a['cle'] for a in AVANTAGES_INFO[0:7]],
    'max': [a['cle'] for a in AVANTAGES_INFO[0:9]],
    'max_plus': [a['cle'] for a in AVANTAGES_INFO[0:12]],
}

FORFAIT_NOMS = {'standard': 'Standard', 'premium': 'Premium', 'max': 'Max', 'max_plus': 'Max Plus'}
FORFAIT_MONTANTS = {'standard': '4 500', 'premium': '12 000', 'max': '68 000', 'max_plus': '112 000'}

def a_acces(user, avantage):
    """
    Vérifie si l'utilisateur a un forfait actif et s'il possède l'avantage demandé.
    """
    # 1. Vérifier si l'utilisateur est connecté et si son badge n'a pas expiré
    if not user or not user.badge_expire or user.badge_expire < datetime.utcnow():
        return False
    
    # 2. Vérifier si le forfait de l'utilisateur possède l'avantage
    forfait = user.forfait_type
    if forfait in FORFAIT_AVANTAGES and avantage in FORFAIT_AVANTAGES[forfait]:
        return True
        
    return False


def get_comparatif_avantages(forfait_actuel=None):
    """
    Construit les données prêtes à afficher pour la page "Avantages du badge" :
    - la liste ordonnée des 12 avantages avec, pour chacun, quels forfaits l'incluent
    - de quoi afficher une coche ✔ ou une croix ✗ par forfait, dans le bon ordre
    """
    ordre_forfaits = ['standard', 'premium', 'max', 'max_plus']
    lignes = []
    for info in AVANTAGES_INFO:
        lignes.append({
            'icone': info['icone'],
            'label': info['label'],
            'inclus': {f: (info['cle'] in FORFAIT_AVANTAGES[f]) for f in ordre_forfaits},
        })
    return {
        'ordre_forfaits': ordre_forfaits,
        'noms': FORFAIT_NOMS,
        'montants': FORFAIT_MONTANTS,
        'lignes': lignes,
        'forfait_actuel': forfait_actuel,
    }