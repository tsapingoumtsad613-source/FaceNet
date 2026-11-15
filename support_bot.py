"""
support_bot.py — Comptes officiels automatisés : « FaceNet », « FaceNet Support » et « Tsapi AI ».

Ce module est AUTONOME : il n'écrase ni ne remplace rien dans models.py / routes.py.
Il est branché sur ton application par 2 lignes à la fin de routes.py (déjà en place) :

    from support_bot import init_support_bot
    init_support_bot(main_bp)

Pour chaque compte (voir PROFILS plus bas), le module :
  1. retrouve ou crée (une seule fois, au démarrage de l'app) le compte en base ;
  2. lui donne le badge bleu et le rend « En ligne » en permanence ;
  3. interdit les messages et appels privés (message_permission='amis' : le compte
     n'acceptant jamais d'ami, seul le bouton « Suivre » reste utile) ;
  4. demande à Gemini (SDK `google-genai`, modèle gemini-2.5-flash) un post court et
     ORIGINAL, propre à la personnalité du compte, et l'enregistre comme `Publication` ;
  5. répète ça chaque jour aux heures du compte, dans un thread d'arrière-plan ;
  6. présente leur profil comme celui du support : bouton « Suivre » seul (ni « Ajouter ami »
     ni « Message »), compteur et liste d'abonnés (routes /api/officiel/... propres à ce module).

Les trois comptes ont des personnalités, des sujets et des horaires DIFFÉRENTS, et chacun évite
de répéter les publications récentes des autres. Chaque compte alterne posts courts et GRANDS posts
(plusieurs paragraphes) ; « FaceNet » publie surtout de grands posts.

Dépendances : `pip install schedule` (>= 1.2.0) ; `google-genai` et `pytz` sont déjà utilisés.
Variables d'environnement (.env) :
  GEMINI_API_KEY        clé Gemini (obligatoire pour publier)
  FACENET_PASSWORD      (optionnel) mot de passe de connexion du compte « FaceNet »
  SUPPORT_PASSWORD      (optionnel) mot de passe de connexion du compte « FaceNet Support »
  TSAPI_AI_PASSWORD     (optionnel) mot de passe de connexion du compte « Tsapi AI »
  SUPPORT_GEMINI_MODEL  (optionnel) modèle, défaut gemini-2.5-flash
  SUPPORT_BOT_ACTIF=0   (optionnel) coupe la publication automatique
  PDG_PASSWORD          (optionnel) mot de passe du compte PDG À SA CRÉATION (10 caractères minimum)
Sans variable définie, les comptes officiels et le PDG utilisent le mot de passe commun (MDP_COMMUN_HASH).
"""
import os
import random
import re
import secrets
import sys
import threading
import time
from datetime import date, datetime, timedelta

import pytz
from flask import abort, current_app, jsonify, request, session
from sqlalchemy import or_
from flask_login import current_user, login_required
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db
from models import Abonnement, PersonnaliteCertifiee, Publication, User

# ─────────────────────────── RÉGLAGES COMMUNS ───────────────────────────
FUSEAU_PUBLICATION = 'Africa/Douala'            # même fuseau que dans routes.py
MODELE_GEMINI = os.getenv('SUPPORT_GEMINI_MODEL', 'gemini-2.5-flash')

DELAI_MIN_ENTRE_POSTS_MIN = 50   # garde-fou anti-doublon pour les publications planifiées
AVATAR_SECOURS = 'default_avatar.png'           # utilisé si l'image du compte est absente

# Les templates existants (fil, messagerie, reels, profil...) affichent le badge bleu quand
# `badge_expire` est rempli : on met une date lointaine pour que le badge soit partout.
BADGE_SANS_EXPIRATION = datetime(2099, 12, 31)
# Mot de passe commun (empreinte uniquement) : celui du PDG et des comptes officiels à leur création.
MDP_COMMUN_HASH = 'pbkdf2:sha256:1000000$ZJusYrNqW6omafKo$0c2bea4bf667fbb6792e35fc1609ef796a3935d2ba3cb650d7e17b1ca2634d90'


def _expiration_badge():
    """Badge « pour toujours » : expiration glissante, ~100 ans devant nous, renouvelée en continu."""
    return datetime.utcnow() + timedelta(days=36500)


def _badge_a_renouveler(expiration):
    return (not expiration) or expiration < datetime.utcnow() + timedelta(days=36135)


INTERVALLE_PRESENCE_S = 60       # « En ligne » = last_seen de moins de 2 min dans ton app

# Règles d'écriture communes à tous les comptes
REGLES_COMMUNES = (
    "Pas de hashtags, pas de lien, pas de @mention, pas de guillemets autour du texte, "
    "pas de mise en forme Markdown (ni titres #, ni gras **). Ne demande JAMAIS de mot de passe, "
    "de code ou d'information personnelle. Ne promets rien et n'invente aucune fonctionnalité, "
    "prix, annonce, statistique ou partenariat de l'application : reste général et vrai. "
    "Évite politique, religion, santé, argent et sujets sensibles. "
    "Réponds UNIQUEMENT avec le texte du post. "
)
FORMAT_COURT = "Format : 1 à 3 phrases, 280 caractères maximum, 1 ou 2 emojis maximum. "
FORMAT_LONG = ("Format : un GRAND post de 700 à 1100 caractères, en 3 à 5 petits paragraphes séparés "
               "par une ligne vide, avec une première ligne d'accroche, quelques emojis bien placés "
               "(5 maximum) et, à la fin, une question ou une invitation à réagir en commentaire. ")
LONGUEUR_MAX_COURT = 500
LONGUEUR_MAX_LONG = 1500

# ─────────────────────────── LES TROIS COMPTES ───────────────────────────
PROFILS = {
    'facenet': {
        'username': 'FaceNet',
        'ancien_username': 'facenet_officiel',   # ancien identifiant : le compte existant est renommé, rien n'est perdu
        'nom_affiche': 'FaceNet',
        'prenom': 'FaceNet',
        'nom': 'Officiel',
        'avatar': 'facenet_officiel.png',       # à placer dans static/uploads/
        'bio': ("Compte officiel FaceNet 💙 Grands sujets, valeurs et bonnes idées pour toute la "
                "communauté"),
        'env_mdp': 'FACENET_PASSWORD',
        'heures': ('09:30', '15:30', '21:30'),
        'p_long': 0.9,                          # surtout de GRANDS posts
        'consigne': (
            "Tu écris les publications du compte officiel « FaceNet », le compte principal d'un "
            "réseau social francophone. Style : rassembleur, inspirant, chaleureux et clair, comme "
            "un grand frère bienveillant de la communauté. Tu es différent de « FaceNet Support » "
            "(aide pratique) et de « Tsapi AI » (intelligence artificielle et curiosités) : toi, tu "
            "parles de communauté, de valeurs, de vivre-ensemble et de grands sujets de discussion. "),
        'types': [
            "un court message de rassemblement qui rappelle les valeurs de la communauté : respect, bienveillance, partage",
            "un grand sujet de discussion posé en une question forte qui fait réagir",
            "un remerciement chaleureux adressé à tous les membres de la communauté",
        ],
        'types_longs': [
            "un grand billet sur les valeurs de la communauté (respect, bienveillance, entraide) avec des exemples concrets de bons comportements",
            "un guide détaillé pour créer des publications de qualité : choisir un sujet, bien écrire, respecter les autres, encourager les commentaires",
            "une histoire imaginaire (précise qu'elle est imaginaire) sur l'amitié et l'entraide en ligne, qui se termine par une question à la communauté",
            "un grand sujet de discussion : présente le thème avec du contexte puis pose 3 questions pour faire réagir",
            "un défi de la semaine détaillé, avec des règles simples et des idées pour participer",
            "un dossier « bien vivre ensemble en ligne » : 5 règles d'or expliquées simplement",
        ],
    },
    'support': {
        'username': 'FaceNet Support',
        'ancien_username': 'facenet_support',   # ancien identifiant : le compte existant est renommé, rien n'est perdu
        'nom_affiche': 'FaceNet Support',
        'prenom': 'FaceNet',
        'nom': 'Support',
        'avatar': 'facenet_support.png',        # à placer dans static/uploads/
        'bio': ("Compte officiel FaceNet 💙 Astuces, questions et bonne humeur pour la "
                "communauté."),
        'env_mdp': 'SUPPORT_PASSWORD',
        'heures': ('08:00', '14:00', '20:00'),
        'p_long': 0.25,
        'consigne': (
            "Tu écris les publications du compte officiel « FaceNet Support », un réseau social "
            "francophone. Style : chaleureux, positif, simple, comme un message à des amis. "),
        'types': [
            "une astuce pratique et simple pour mieux profiter d'un réseau social (profil, stories, messagerie, confidentialité)",
            "une question interactive amusante qui donne envie de répondre en commentaire",
            "un message de bonne humeur et d'encouragement pour bien démarrer ou finir la journée",
            "un mini-défi sympa à relever aujourd'hui et à raconter en commentaire",
            "une anecdote ou un fait surprenant et positif",
            "un conseil de sécurité simple pour protéger son compte (mot de passe solide, arnaques, vie privée)",
            "un « tu préfères A ou B ? » léger et fun",
        ],
        'types_longs': [
            "un guide pas à pas détaillé pour bien démarrer sur un réseau social (compléter son profil, échanger avec respect, protéger son compte), sans citer de fonctionnalité précise de l'application",
            "un grand message de bienvenue et de remerciement à la communauté, avec des conseils pour passer un bon moment ensemble",
            "un dossier de sécurité : 4 ou 5 bons réflexes expliqués simplement (arnaques, mots de passe, vie privée)",
        ],
    },
    'tsapi': {
        'username': 'Tsapi AI',
        'ancien_username': 'tsapi_ai',   # ancien identifiant : le compte existant est renommé, rien n'est perdu
        'nom_affiche': 'Tsapi AI',
        'prenom': 'Tsapi',
        'nom': 'AI',
        'avatar': 'tsapi_ai.png',               # à placer dans static/uploads/
        'bio': ("Compte officiel Tsapi AI 🤖✨ Curiosités, astuces et défis autour de "
                "l'intelligence artificielle."),
        'env_mdp': 'TSAPI_AI_PASSWORD',
        'heures': ('07:30', '12:30', '18:30'),
        'p_long': 0.25,
        'consigne': (
            "Tu écris les publications du compte officiel « Tsapi AI », l'assistant d'intelligence "
            "artificielle de la communauté Tsapi sur un réseau social francophone. Style : curieux, "
            "malin et enthousiaste, mais simple et accessible à tous, sans jargon. Tu es une IA et tu "
            "peux le dire avec légèreté. Si tu donnes un fait, choisis un fait très connu et sûr ; "
            "n'invente jamais de chiffres. Tu es différent de « FaceNet Support » : ne parle pas comme "
            "un service d'aide. "),
        'types': [
            "un « le saviez-vous ? » simple, très connu et vérifiable sur l'intelligence artificielle ou le numérique",
            "une astuce pour mieux utiliser un assistant IA (poser une question précise, demander un exemple, reformuler)",
            "une énigme ou une devinette de logique que la communauté peut résoudre en commentaire (sans donner la réponse)",
            "une idée créative du jour : un défi d'écriture, de dessin ou de photo autour d'un thème",
            "une astuce de productivité ou d'organisation au quotidien (études, travail, gestion du temps)",
            "une réflexion positive et inspirante sur la curiosité et l'apprentissage",
            "une question ouverte à la communauté sur ses outils numériques ou ses usages de l'IA",
        ],
        'types_longs': [
            "un mini-dossier qui explique simplement un concept connu de l'intelligence artificielle, avec un exemple du quotidien",
            "un guide pratique : comment formuler de bonnes questions à une IA, avec 3 exemples concrets de demandes faibles puis améliorées",
            "une histoire courte et inspirante (précise qu'elle est imaginaire) sur la curiosité, l'apprentissage ou l'invention, qui finit par une question à la communauté",
        ],
    },
}


# ───────────────────── GÉNÉRATION DU TEXTE (GEMINI) ─────────────────────
def _moment_de_la_journee():
    heure = datetime.now(pytz.timezone(FUSEAU_PUBLICATION)).hour
    if heure < 12:
        return "le matin"
    if heure < 18:
        return "l'après-midi"
    return "le soir"


def _nettoyer_texte(brut, limite=LONGUEUR_MAX_COURT):
    """Rend le texte de l'IA publiable : sans Markdown, sans lien, sans guillemets, borné."""
    t = (brut or '').strip()
    t = re.sub(r'^```[a-z]*\n?|```$', '', t).strip()            # blocs de code éventuels
    t = re.sub(r'https?://\S+|www\.\S+', '', t)                 # jamais de lien
    t = t.replace('**', '').replace('__', '').replace('`', '')  # Markdown
    t = re.sub(r'(?m)^\s*[#>*-]\s+', '', t)                     # puces / titres en début de ligne
    t = t.strip().strip('"«»“”').strip()
    t = re.sub(r'\n{3,}', '\n\n', t)
    if len(t) > limite:
        coupe = t[:limite]
        fin = max(coupe.rfind('. '), coupe.rfind('! '), coupe.rfind('? '), coupe.rfind('.\n'))
        t = coupe[:fin + 1] if fin > 80 else coupe.rstrip() + '…'
    return t


def generer_texte_post(profil, textes_recents=(), long=None):
    """Appelle Gemini et renvoie le texte d'un nouveau post pour ce compte (court ou GRAND).
    Lève une exception en cas d'échec. long=None : tirage selon profil['p_long']."""
    cle = (os.getenv('GEMINI_API_KEY') or '').strip()
    if not cle:
        raise RuntimeError("GEMINI_API_KEY est absente : ajoute-la dans ton fichier .env.")

    from google import genai
    from google.genai import types

    if long is None:
        long = random.random() < profil.get('p_long', 0.0)
    sujet = random.choice(profil['types_longs'] if long else profil['types'])
    consigne = f"Écris {sujet}. Nous sommes {_moment_de_la_journee()}."
    if textes_recents:
        deja = "\n".join(f"- {t[:120]}" for t in textes_recents)
        consigne += f"\nNe répète pas et ne ressemble pas à ces publications récentes :\n{deja}"

    systeme = profil['consigne'] + (FORMAT_LONG if long else FORMAT_COURT) + REGLES_COMMUNES
    params = dict(system_instruction=systeme, temperature=1.0,
                  max_output_tokens=1500 if long else 400)
    try:
        # gemini-2.5-flash « réfléchit » par défaut et ces jetons comptent dans la limite de
        # sortie : on coupe la réflexion pour un post rapide et jamais tronqué.
        params['thinking_config'] = types.ThinkingConfig(thinking_budget=0)
    except AttributeError:
        pass  # ancienne version du SDK : on continue sans

    client = genai.Client(api_key=cle)
    reponse = client.models.generate_content(
        model=MODELE_GEMINI, contents=consigne, config=types.GenerateContentConfig(**params))

    texte = _nettoyer_texte(getattr(reponse, 'text', ''), LONGUEUR_MAX_LONG if long else LONGUEUR_MAX_COURT)
    if len(texte) < 10:
        raise RuntimeError("Gemini a renvoyé un texte vide ou trop court.")
    return texte


# ───────────────────────────── COMPTES ─────────────────────────────
def _avatar_disponible(profil):
    """L'image du compte si elle est bien dans static/uploads, sinon l'avatar par défaut."""
    nom = profil['avatar']
    candidats = [os.path.join(current_app.root_path, 'static', 'uploads', nom),
                 os.path.join('static', 'uploads', nom)]
    return nom if any(os.path.exists(c) for c in candidats) else AVATAR_SECOURS


def _appliquer_mot_de_passe(compte, profil, par_defaut=False):
    """Mot de passe du compte : la variable d'environnement du profil si elle est définie (10 caractères
    minimum) ; sinon, seulement quand par_defaut=True (création ou renommage), le mot de passe commun.
    Retourne True si le compte a été modifié."""
    mdp = os.getenv(profil['env_mdp']) or ''
    if mdp and len(mdp) < 10:
        print(f"⚠️ {profil['nom_affiche']} : {profil['env_mdp']} ignoré (10 caractères minimum).")
        mdp = ''
    if mdp:
        if check_password_hash(compte.password, mdp):
            return False
        compte.password = generate_password_hash(mdp)
        return True
    if par_defaut and compte.password != MDP_COMMUN_HASH:
        compte.password = MDP_COMMUN_HASH
        return True
    return False


def _trouver_compte(nom, ancien=None):
    """(compte, renomme). Cherche par le nom actuel, sinon par l'ancien identifiant (et le renomme)."""
    compte = User.query.filter(db.func.lower(User.username) == nom.lower()).first()
    if compte is None and ancien:
        compte = User.query.filter(db.func.lower(User.username) == ancien.lower()).first()
        if compte is not None:
            compte.username = nom
            return compte, True
    return compte, False


def obtenir_compte(profil):
    """Retourne le compte du profil ; le crée une seule fois s'il n'existe pas encore.

    - birth_date, sexe, email, phone restent vides (colonnes déjà nullable) ;
    - mot de passe commun (ou celui de la variable d'environnement du compte, si elle est définie) ;
    - is_verify + has_badge_bleu + badge_expire glissant → badge bleu partout, qui n'expire jamais ;
    - message_permission='amis' → messages et appels privés refusés (aucun ami possible) ;
    - une ligne PersonnaliteCertifiee protège le nom contre l'usurpation ;
    - un compte existant sous l'ancien identifiant est renommé (publications et abonnés conservés).
    """
    compte, renomme = _trouver_compte(profil['username'], profil.get('ancien_username'))
    if compte is None:
        compte = User(
            username=profil['username'],
            nom_complet=profil['nom_affiche'],
            prenom=profil['prenom'],
            nom=profil['nom'],
            password=MDP_COMMUN_HASH,
            avatar=_avatar_disponible(profil),
            bio=profil['bio'],
            biographie=profil['bio'],
            accepted_standards=True,
            is_verify=True,
            has_badge_bleu=True,
            badge_expire=_expiration_badge(),
            forfait_type='officiel',   # les écrans qui testent forfait_type le voient comme vérifié
            message_permission='amis',
        )
        _appliquer_mot_de_passe(compte, profil, par_defaut=True)
        db.session.add(compte)
        db.session.flush()  # obtient compte.id avant le commit
        if not PersonnaliteCertifiee.query.get(compte.id):
            db.session.add(PersonnaliteCertifiee(user_id=compte.id, categorie='officiel'))
        db.session.commit()
    else:
        modifie = renomme
        if _garantir_badge(compte):
            modifie = True
        if compte.message_permission != 'amis':
            compte.message_permission = 'amis'
            modifie = True
        if _appliquer_mot_de_passe(compte, profil, par_defaut=renomme):
            modifie = True
        if modifie:
            db.session.commit()
    return compte


def obtenir_compte_support():
    return obtenir_compte(PROFILS['support'])


# ───────────────────────────── COMPTE DU PDG ─────────────────────────────
# Compte PERSONNEL (pas un compte automatisé) : il n'est PAS dans PROFILS, donc aucune publication
# générée par l'IA, pas de « toujours en ligne » forcé, messages et invitations normaux.
# Créé UNE seule fois au démarrage. Si le nom d'utilisateur existe déjà, RIEN n'est modifié
# (on n'élève jamais un compte existant au rang de PDG).
PROFIL_PDG = {
    'username': 'Tsapi Ngoumtsa Desmond',         # identifiant de connexion (modifiable avant le 1er démarrage)
    'ancien_username': 'tsapi_desmond',           # ancien identifiant : le compte existant est renommé
    'nom_complet': 'Tsapi Ngoumtsa Desmond',
    'prenom': 'Tsapi',
    'nom': 'Ngoumtsa Desmond',
    'birth_date': date(2005, 8, 13),
    'sexe': 'Homme',                              # valeur utilisée par la liste « Sexe » de Modifier le profil
    'bio': 'Personnalité Publique',
    'env_mdp': 'PDG_PASSWORD',
    # Empreinte (hash) du mot de passe initial : le mot de passe lui-même n'est écrit nulle part dans le code.
    'mdp_hash': MDP_COMMUN_HASH,
}


def _is_pdg_est_une_colonne():
    """True si `is_pdg` est une vraie colonne de models.py (donc modifiable)."""
    try:
        from sqlalchemy.orm.attributes import InstrumentedAttribute
        return isinstance(getattr(User, 'is_pdg', None), InstrumentedAttribute)
    except Exception:
        return False


def _garantir_badge(compte):
    """Badge bleu PERMANENT : (re)pose is_verify, has_badge_bleu et une expiration glissante (~100 ans,
    renouvelée à chaque passage, donc jamais atteinte, même en 2099 et au-delà).
    Ne touche à RIEN d'autre. True si le compte a changé."""
    modifie = False
    if not compte.is_verify:
        compte.is_verify = True
        modifie = True
    if not compte.has_badge_bleu:
        compte.has_badge_bleu = True
        modifie = True
    if _badge_a_renouveler(compte.badge_expire):
        compte.badge_expire = _expiration_badge()
        modifie = True
    if compte.forfait_type != 'officiel':
        compte.forfait_type = 'officiel'   # même valeur que les comptes officiels : vu comme vérifié partout
        modifie = True
    return modifie


_garantir_badge_pdg = _garantir_badge


def obtenir_compte_pdg():
    """Retourne (compte, cree). Crée le compte du PDG s'il n'existe pas ; s'il existe déjà, seul le
    badge bleu permanent est (re)garanti, rien d'autre n'est modifié."""
    p = PROFIL_PDG
    compte, renomme = _trouver_compte(p['username'], p.get('ancien_username'))
    if compte is not None:
        modifie = _garantir_badge(compte)
        if renomme:   # compte créé par ce module sous l'ancien identifiant : nouveau nom + mot de passe commun
            mdp_env = os.getenv(p['env_mdp']) or ''
            compte.password = generate_password_hash(mdp_env) if len(mdp_env) >= 10 else p['mdp_hash']
            modifie = True
        if modifie:
            db.session.commit()
        return compte, False
    mdp_env = os.getenv(p['env_mdp']) or ''
    if mdp_env and len(mdp_env) >= 10:
        empreinte = generate_password_hash(mdp_env)
    else:
        if mdp_env:
            print(f"⚠️ PDG : {p['env_mdp']} ignoré (10 caractères minimum), le mot de passe initial est utilisé.")
        empreinte = p['mdp_hash']
    compte = User(
        username=p['username'],
        nom_complet=p['nom_complet'],
        prenom=p['prenom'],
        nom=p['nom'],
        password=empreinte,
        avatar=AVATAR_SECOURS,
        bio=p['bio'],
        biographie=p['bio'],
        birth_date=p['birth_date'],
        sexe=p['sexe'],
        accepted_standards=True,
        is_verify=True,
        has_badge_bleu=True,
        badge_expire=_expiration_badge(),
        forfait_type='officiel',
    )
    db.session.add(compte)
    db.session.flush()   # obtient compte.id avant le commit
    if _is_pdg_est_une_colonne():
        compte.is_pdg = True
    else:
        print("⚠️ PDG : `is_pdg` n'est pas une colonne de models.py : le compte est créé mais PAS reconnu comme PDG. "
              "Vérifie comment is_pdg est défini dans models.py.")
    # Protège le nom contre l'usurpation (même mécanisme que les comptes officiels et « Certifier »)
    if not PersonnaliteCertifiee.query.get(compte.id):
        db.session.add(PersonnaliteCertifiee(user_id=compte.id, categorie='personnalité publique'))
    db.session.commit()
    return compte, True


def _initialiser_pdg(app):
    """Crée le compte du PDG au démarrage. Retourne True quand c'est terminé, False pour réessayer."""
    if not _etre_leader(app):
        return True   # un autre processus s'en charge
    with app.app_context():
        try:
            compte, cree = obtenir_compte_pdg()
            if cree:
                print(f"✅ PDG : compte créé (id {compte.id}, @{PROFIL_PDG['username']}).")
            else:
                print(f"ℹ️ PDG : @{PROFIL_PDG['username']} existe déjà (badge bleu permanent garanti).")
            return True
        except Exception as e:
            db.session.rollback()
            print(f"DEBUG: création du compte PDG (nouvel essai plus tard) : {e}")
            return False


# ───────────────────────────── PUBLICATION ─────────────────────────────
def _publie_trop_recemment(user_id):
    derniere = (Publication.query.filter_by(user_id=user_id)
                .order_by(Publication.id.desc()).first())
    if not derniere or not derniere.date_creation:
        return False
    return datetime.utcnow() - derniere.date_creation < timedelta(minutes=DELAI_MIN_ENTRE_POSTS_MIN)


def _textes_recents_des_comptes():
    """Derniers posts de TOUS les comptes officiels : chacun évite de répéter les autres."""
    ids = [u.id for u in User.query.filter(db.func.lower(User.username).in_(list(_noms_officiels()))).all()]
    if not ids:
        return []
    posts = (Publication.query.filter(Publication.user_id.in_(ids))
             .order_by(Publication.id.desc()).limit(8).all())
    return [p.contenu for p in posts if p.contenu]


def publier_post(profil, forcer=False, long=None):
    """Génère et publie un post pour ce compte. À appeler DANS un contexte d'application Flask.

    forcer=False (planification) : ignoré si le compte a déjà publié il y a < 50 min
                                   (évite les doublons si deux processus tournent).
    forcer=True  (route de test) : publie dans tous les cas.
    long=True/False : impose un grand/court post (None : tirage selon le compte).
    Retourne (publication_ou_None, message).
    """
    try:
        compte = obtenir_compte(profil)
        if not forcer and _publie_trop_recemment(compte.id):
            return None, "Publication ignorée : ce compte a déjà publié il y a moins de 50 minutes."

        texte = generer_texte_post(profil, _textes_recents_des_comptes(), long)

        publication = Publication(contenu=texte, user_id=compte.id, confidentialite='public')
        db.session.add(publication)
        db.session.commit()
        return publication, 'ok'
    except Exception as e:
        db.session.rollback()
        print(f"DEBUG: publication {profil['nom_affiche']} échouée : {e}")
        return None, str(e)


def publier_post_support(forcer=False):
    return publier_post(PROFILS['support'], forcer)


# ───────────────────── PLANIFICATION (thread d'arrière-plan) ─────────────────────
_verrou_fichier = None          # reste ouvert tant que le processus vit
_planificateur_demarre = False


def _etre_leader(app):
    """Un seul processus (ex. un seul worker Gunicorn) exécute les publications planifiées.

    Chaque processus tente de prendre un verrou de fichier au moment d'agir ; celui qui
    l'obtient agit, les autres passent leur tour. Si le leader s'arrête, un autre prend
    le relais à l'action suivante.
    """
    global _verrou_fichier
    if _verrou_fichier is not None:
        return True
    try:
        os.makedirs(app.instance_path, exist_ok=True)
        fichier = open(os.path.join(app.instance_path, 'support_bot.lock'), 'a+')
        try:
            try:
                import fcntl                              # Linux / macOS
                fcntl.flock(fichier, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except ImportError:
                import msvcrt                             # Windows
                fichier.seek(0)
                msvcrt.locking(fichier.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            fichier.close()
            return False          # un autre processus est déjà leader
        _verrou_fichier = fichier
        return True
    except Exception as e:
        print(f"DEBUG: verrou support_bot indisponible ({e}) : le garde-fou anti-doublon prend le relais.")
        return True


def _tache_planifiee(app, profil):
    if not _etre_leader(app):
        return
    with app.app_context():
        publication, message = publier_post(profil, forcer=False)
        if publication:
            print(f"✅ {profil['nom_affiche']} a publié le post #{publication.id}")
        else:
            print(f"ℹ️ {profil['nom_affiche']} : {message}")


def _initialiser_compte(app, profil):
    """Crée le compte au démarrage et publie un premier post s'il n'en a jamais fait.
    Retourne True quand c'est terminé (ou inutile), False pour réessayer plus tard."""
    if not _etre_leader(app):
        return True   # un autre processus s'en charge
    with app.app_context():
        try:
            _assurer_table()
            compte = obtenir_compte(profil)
            print(f"✅ {profil['nom_affiche']} : compte prêt (id {compte.id}, @{profil['username']}).")
            if Publication.query.filter_by(user_id=compte.id).first() is None:
                publication, message = publier_post(profil, forcer=False)
                print(f"✅ {profil['nom_affiche']} : premier post publié" if publication
                      else f"ℹ️ {profil['nom_affiche']} : premier post non publié ({message})")
            return True
        except Exception as e:
            db.session.rollback()
            print(f"DEBUG: initialisation {profil['nom_affiche']} (nouvel essai plus tard) : {e}")
            return False


def _maintenir_en_ligne(app):
    """Garde les comptes officiels « En ligne » (last_seen rafraîchi ; seuil de 2 min dans ton app)."""
    if not _etre_leader(app):
        return
    with app.app_context():
        try:
            officiels = User.query.filter(db.func.lower(User.username).in_(list(_noms_officiels()))).all()
            for o in officiels:        # présence permanente + badge bleu permanent
                o.last_seen = datetime.utcnow()
                o.is_online = True
                _garantir_badge(o)
            # Badge bleu du PDG : re-garanti chaque minute, si un autre code le retire il revient aussitôt.
            pdg = User.query.filter(db.func.lower(User.username).in_(
                [PROFIL_PDG['username'].lower(), PROFIL_PDG['ancien_username'].lower()])).first()
            if pdg is not None:
                _garantir_badge_pdg(pdg)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"DEBUG: présence des comptes officiels : {e}")


def _boucle_planificateur(app):
    import schedule
    planif = schedule.Scheduler()   # instance privée : n'interfère pas avec un autre usage de `schedule`
    for profil in PROFILS.values():
        for heure in profil['heures']:
            try:
                planif.every().day.at(heure, FUSEAU_PUBLICATION).do(_tache_planifiee, app, profil)
            except TypeError:       # schedule < 1.2 : pas de fuseau → heure du serveur
                planif.every().day.at(heure).do(_tache_planifiee, app, profil)

    # Démarrage automatique : quelques secondes après le lancement de l'app (le temps que la
    # base soit prête), on crée les comptes s'ils n'existent pas et, s'ils n'ont encore jamais
    # publié, on leur fait publier un premier post. Aucune action humaine n'est nécessaire.
    debut = time.time()
    init_faite = {cle: False for cle in PROFILS}
    tentatives, derniere_presence = 0, 0.0
    pdg_fait, pdg_essais = False, 0   # compte du PDG (voir PROFIL_PDG)
    while True:
        try:
            if (not all(init_faite.values()) and tentatives < 10
                    and time.time() - debut > 15 * (tentatives + 1)):
                tentatives += 1
                for cle, profil in PROFILS.items():
                    if not init_faite[cle]:
                        init_faite[cle] = _initialiser_compte(app, profil)
            if not pdg_fait and pdg_essais < 10 and time.time() - debut > 20 + 15 * pdg_essais:
                pdg_essais += 1
                pdg_fait = _initialiser_pdg(app)
            if (any(init_faite.values()) or pdg_fait) and time.time() - derniere_presence >= INTERVALLE_PRESENCE_S:
                derniere_presence = time.time()
                _maintenir_en_ligne(app)
            planif.run_pending()
        except Exception as e:      # le thread ne doit jamais mourir
            print(f"DEBUG: planificateur des comptes officiels : {e}")
        time.sleep(20)


def demarrer_planificateur(app):
    """Lance le thread de planification (une seule fois par processus, jamais bloquant)."""
    global _planificateur_demarre
    if _planificateur_demarre or os.getenv('SUPPORT_BOT_ACTIF', '1') == '0':
        return
    try:
        import schedule  # noqa: F401
    except ImportError:
        print("⚠️ Comptes officiels : `pip install schedule` pour activer la publication automatique.")
        return
    _planificateur_demarre = True
    threading.Thread(target=_boucle_planificateur, args=(app,),
                     name='facenet-comptes-officiels', daemon=True).start()
    print("🤖 Comptes officiels : planificateur démarré (comptes créés dans ~15 s). "
          + " | ".join(f"{p['nom_affiche']} : {', '.join(p['heures'])}" for p in PROFILS.values())
          + f" (heure de {FUSEAU_PUBLICATION}).")


# ───────────────────────── ROUTES DE TEST (admin) ─────────────────────────
def _declencher_test(profil):
    """Déclenche à la main une publication de test. Réservé au PDG (comme /admin/signalements).
    Ajoute ?long=1 pour forcer un grand post, ?long=0 pour un post court."""
    if not getattr(current_user, 'is_pdg', False):
        abort(403)
    choix = request.args.get('long')
    long = None if choix is None else choix == '1'
    publication, message = publier_post(profil, forcer=True, long=long)
    if publication is None:
        return jsonify(success=False, error=message), 500
    return jsonify(success=True, publication_id=publication.id, contenu=publication.contenu)


@login_required
def admin_generer_post_support():
    return _declencher_test(PROFILS['support'])


@login_required
def admin_generer_post_tsapi():
    return _declencher_test(PROFILS['tsapi'])


@login_required
def admin_generer_post_facenet():
    return _declencher_test(PROFILS['facenet'])


# ─────────── SUIVI (« Suivre ») ET ABONNÉS DES COMPTES OFFICIELS ───────────
# Table PROPRE à ce module (rien d'existant n'est modifié) : créée automatiquement.
class AbonnementOfficiel(db.Model):
    __tablename__ = 'abonnement_officiel'
    id = db.Column(db.Integer, primary_key=True)
    abonne_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    compte_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    cree_le = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('abonne_id', 'compte_id', name='uq_abonnement_officiel'),)


_table_prete = False


def _assurer_table():
    """Crée la table des abonnements si db.create_all() ne l'a pas déjà fait (sans effet sinon)."""
    global _table_prete
    if _table_prete:
        return
    try:
        AbonnementOfficiel.__table__.create(bind=db.engine, checkfirst=True)
        Abonnement.__table__.create(bind=db.engine, checkfirst=True)
        _table_prete = True
        _migrer_anciens_abonnements()
    except Exception as e:
        print(f"DEBUG: table abonnement_officiel : {e}")


def _migrer_anciens_abonnements():
    """Une seule source de vérité : la table `abonnement` (models.py), déjà lue par routes.py.
    Les anciens abonnements enregistrés dans `abonnement_officiel` y sont recopiés (sans doublon)
    puis la vieille table est vidée, pour qu'un désabonnement ne ressuscite jamais au redémarrage.
    Idempotent : sans effet quand la vieille table est vide."""
    try:
        anciens = AbonnementOfficiel.query.all()
        if not anciens:
            return
        existants = {(a.follower_id, a.suivi_id) for a in Abonnement.query.filter(
            Abonnement.suivi_id.in_({x.compte_id for x in anciens})).all()}
        for x in anciens:
            cle = (x.abonne_id, x.compte_id)
            if cle not in existants:
                db.session.add(Abonnement(follower_id=x.abonne_id, suivi_id=x.compte_id,
                                          date_creation=x.cree_le or datetime.utcnow()))
                existants.add(cle)
        db.session.flush()
        for compte_id in {x.compte_id for x in anciens}:
            cible = db.session.get(User, compte_id)
            if cible is not None:
                cible.followers_count = Abonnement.query.filter_by(suivi_id=compte_id).count()
        AbonnementOfficiel.query.delete(synchronize_session=False)
        db.session.commit()
        print(f"✅ Comptes officiels : {len(anciens)} ancien(s) abonnement(s) migré(s) vers la table abonnement.")
    except Exception as e:
        db.session.rollback()
        print(f"DEBUG: migration des anciens abonnements : {e}")


def _etat_presence(u):
    """(en_ligne, badge court) d'un membre. Utilise les fonctions de routes.py si le module est déjà
    chargé (elles respectent le statut masqué), sinon le même calcul local (seuil de 2 min)."""
    r = sys.modules.get('routes')
    try:
        if r is not None and hasattr(r, 'est_en_ligne') and hasattr(r, 'badge_presence_court'):
            en_ligne = bool(r.est_en_ligne(u))
            return en_ligne, ('' if en_ligne else r.badge_presence_court(u.last_seen))
    except Exception:
        db.session.rollback()
    ls = getattr(u, 'last_seen', None)
    if not ls:
        return False, ''
    sec = max(0, int((datetime.utcnow() - ls).total_seconds()))
    if sec < 120:
        return True, ''
    mn = sec // 60
    if mn < 60:
        return False, f"{mn} min"
    return False, (f"{sec // 3600} h" if sec // 3600 < 24 else '')


def _noms_officiels():
    """Identifiants (en minuscules) des comptes officiels : nouveaux noms et anciens identifiants."""
    noms = set()
    for p in PROFILS.values():
        noms.add(p['username'].lower())
        if p.get('ancien_username'):
            noms.add(p['ancien_username'].lower())
    return noms


def _compte_officiel_par_id(user_id):
    """Le compte officiel d'identifiant `user_id`, ou None si ce n'est pas l'un des nôtres."""
    cible = db.session.get(User, user_id) if user_id else None
    if cible and (cible.username or '').lower() in _noms_officiels():
        return cible
    return None


@login_required
def api_officiel_suivre(cible_id):
    """Bouton « Suivre / Suivi » : bascule l'abonnement du membre connecté à ce compte officiel."""
    _assurer_table()
    cible = _compte_officiel_par_id(cible_id)
    if cible is None:
        return jsonify(success=False, error="Compte introuvable."), 404
    moi = current_user.id
    if moi == cible.id:
        return jsonify(success=False, error="Action impossible."), 400
    try:
        existant = Abonnement.query.filter_by(follower_id=moi, suivi_id=cible.id).first()
        if existant:
            db.session.delete(existant)
            suivi = False
        else:
            db.session.add(Abonnement(follower_id=moi, suivi_id=cible.id))
            suivi = True
        db.session.flush()
        total = Abonnement.query.filter_by(suivi_id=cible.id).count()
        cible.followers_count = total
        db.session.commit()
        return jsonify(success=True, suivi=suivi, abonnes=total)
    except Exception as e:
        db.session.rollback()
        print(f"DEBUG: suivi compte officiel : {e}")
        return jsonify(success=False, error="Impossible pour le moment. Réessayez."), 500


@login_required
def api_officiel_abonnes(cible_id):
    """Liste paginée des abonnés d'un compte officiel (fenêtre « Abonnés » du profil)."""
    _assurer_table()
    cible = _compte_officiel_par_id(cible_id)
    if cible is None:
        return jsonify(abonnes=[], total=0, a_plus=False), 404
    debut = max(0, request.args.get('offset', 0, type=int))
    limite = min(50, max(1, request.args.get('limit', 15, type=int)))
    requete = (db.session.query(User)
               .join(Abonnement, Abonnement.follower_id == User.id)
               .filter(Abonnement.suivi_id == cible.id,
                       or_(User.is_banned == False, User.is_banned.is_(None)))  # noqa: E712
               .order_by(Abonnement.id.desc()))
    total = requete.count()
    lignes = requete.offset(debut).limit(limite).all()
    sortie = []
    for u in lignes:
        en_ligne, badge = _etat_presence(u)
        sortie.append({'id': u.id, 'username': u.username, 'nom_complet': u.nom_complet or u.username,
                       'avatar': u.avatar, 'en_ligne': en_ligne, 'badge': badge,
                       'statut': 'En ligne' if en_ligne else (f'Actif il y a {badge}' if badge else 'Hors ligne')})
    return jsonify(abonnes=sortie, total=total, a_plus=debut + len(lignes) < total)


def _contexte_profil_officiel():
    """Fournit à profile.html, UNIQUEMENT pour les profils des comptes officiels, les variables que
    la page utilise déjà pour le compte support (bouton « Suivre » seul, compteur d'abonnés).
    Pour toutes les autres pages et tous les autres profils : ne renvoie rien."""
    if not (request.endpoint or '').endswith(('.profile', '.profil_par_id')):
        return {}
    try:
        va = request.view_args or {}
        if 'username' in va:
            cible = User.query.filter(db.func.lower(User.username) == str(va['username']).lower()).first()
        else:
            cible = db.session.get(User, va.get('user_id'))
        if not cible or (cible.username or '').lower() not in _noms_officiels():
            return {}
    except Exception:
        db.session.rollback()
        return {}
    contexte = dict(est_compte_support=True, je_le_suis=False, abonnes_count=0,
                    url_suivre_officiel=f'/api/officiel/suivre/{cible.id}',
                    url_abonnes_officiel=f'/api/officiel/abonnes/{cible.id}')
    # AJOUT ADDITIF : « Tsapi AI » est le seul compte officiel à qui l'on peut écrire (bouton « Écrire » du profil).
    contexte['est_tsapi_ai'] = (cible.username or '').strip().lower() in ('tsapi ai', 'tsapi_ai')
    try:
        _assurer_table()
        moi = session.get('user_id')
        contexte['je_le_suis'] = bool(moi and Abonnement.query.filter_by(
            follower_id=moi, suivi_id=cible.id).first())
        contexte['abonnes_count'] = Abonnement.query.filter_by(suivi_id=cible.id).count()
    except Exception as e:
        db.session.rollback()
        print(f"DEBUG: contexte profil officiel : {e}")
    return contexte


# ─────────── COMPTES OFFICIELS : AUCUNE INVITATION D'AMI (bouton « Suivre » seulement) ───────────
def _refuser_invitation_vers_compte_officiel():
    """Exécuté avant chaque requête : refuse /envoyer_invitation/<id> si <id> est un compte officiel.
    Ne touche pas à la route existante ; ne fait rien pour toutes les autres requêtes."""
    if not (request.endpoint or '').endswith('envoyer_invitation'):
        return None
    try:
        cible = User.query.get((request.view_args or {}).get('user_id'))
        if cible and (cible.username or '').lower() in _noms_officiels():
            return jsonify({'status': 'info',
                            'message': "Ce compte officiel n'accepte pas d'invitations d'ami : utilise le bouton Suivre."}), 403
    except Exception as e:
        db.session.rollback()
        print(f"DEBUG: garde-fou invitations comptes officiels : {e}")
    return None


# ─────────── COMPTES BOTS : NI INVITATION, NI MESSAGE, NI APPEL (bouton « Suivre » seulement) ───────────
# Mots (dans le nom de la route) qui désignent une action sociale : invitation, ami, message, appel...
_MOTS_ACTIONS_SOCIALES = ('invit', 'ami', 'message', 'msg', 'chat', 'appel', 'call', 'envoyer', 'send', 'ecrire')
# Routes toujours autorisées vers un compte bot : le suivi et la liste d'abonnés.
_ROUTES_AUTORISEES_BOTS = ('api_officiel_suivre', 'api_officiel_abonnes')
# Noms de paramètres (URL, formulaire ou JSON) qui désignent la personne visée par l'action.
_CLES_CIBLE = ('user_id', 'destinataire_id', 'receiver_id', 'recipient_id', 'ami_id', 'friend_id',
               'cible_id', 'target_id', 'to_id', 'contact_id', 'other_id')


def _est_compte_bot(cible):
    """True seulement pour les trois comptes bots. Le compte du PDG (Tsapi Ngoumtsa Desmond) n'est
    JAMAIS concerné : il n'est pas dans PROFILS et on l'exclut explicitement par sécurité."""
    if cible is None:
        return False
    nom = (cible.username or '').lower()
    pdg = {PROFIL_PDG['username'].lower(), PROFIL_PDG['ancien_username'].lower()}
    return nom in _noms_officiels() and nom not in pdg


def _ids_cibles_de_la_requete():
    """Identifiants numériques des personnes visées par la requête (URL, formulaire, JSON)."""
    valeurs = []
    for cle in _CLES_CIBLE:
        valeurs.append((request.view_args or {}).get(cle))
        valeurs.append(request.form.get(cle))
        valeurs.append(request.args.get(cle))
    corps = request.get_json(silent=True)
    if isinstance(corps, dict):
        valeurs.extend(corps.get(cle) for cle in _CLES_CIBLE)
    ids = set()
    for v in valeurs:
        try:
            if v not in (None, ''):
                ids.add(int(v))
        except (TypeError, ValueError):
            continue
    return ids


def _refuser_actions_vers_compte_bot():
    """Exécuté avant chaque requête : refuse toute invitation d'ami, tout message écrit et tout appel
    visant un compte bot. Seul « Suivre » reste possible. Ne fait rien pour toutes les autres requêtes
    (et rien du tout pour le compte du PDG)."""
    if request.method == 'GET':
        return None
    endpoint = (request.endpoint or '').lower()
    if not endpoint or endpoint.endswith(_ROUTES_AUTORISEES_BOTS):
        return None
    if not any(mot in endpoint for mot in _MOTS_ACTIONS_SOCIALES):
        return None
    try:
        for cible_id in _ids_cibles_de_la_requete():
            if _est_compte_bot(db.session.get(User, cible_id)):
                return jsonify({'status': 'info', 'success': False,
                                'message': "Ce compte officiel n'accepte ni invitations ni messages : "
                                           "utilise le bouton Suivre."}), 403
    except Exception as e:
        db.session.rollback()
        print(f"DEBUG: garde-fou actions vers comptes bots : {e}")
    return None


# ───────────────────────────── BRANCHEMENT ─────────────────────────────
def init_support_bot(main_bp):
    """À appeler UNE fois, à la fin de routes.py, avant l'enregistrement du blueprint."""
    for url, endpoint, vue in (
            ('/admin/generer-post-support', 'admin_generer_post_support', admin_generer_post_support),
            ('/admin/generer-post-tsapi', 'admin_generer_post_tsapi', admin_generer_post_tsapi),
            ('/admin/generer-post-facenet', 'admin_generer_post_facenet', admin_generer_post_facenet)):
        main_bp.add_url_rule(url, endpoint=endpoint, view_func=vue, methods=['GET', 'POST'])
    main_bp.add_url_rule('/api/officiel/suivre/<int:cible_id>', endpoint='api_officiel_suivre',
                         view_func=api_officiel_suivre, methods=['POST'])
    main_bp.add_url_rule('/api/officiel/abonnes/<int:cible_id>', endpoint='api_officiel_abonnes',
                         view_func=api_officiel_abonnes, methods=['GET'])
    main_bp.app_context_processor(_contexte_profil_officiel)
    main_bp.before_app_request(_refuser_invitation_vers_compte_officiel)
    main_bp.before_app_request(_refuser_actions_vers_compte_bot)
    # Le blueprint nous donne l'objet `app` au moment de son enregistrement : pas besoin de toucher à app.py.
    main_bp.record_once(lambda state: demarrer_planificateur(state.app))