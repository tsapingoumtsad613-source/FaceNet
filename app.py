# ==========================================================================
# ====  AJOUT : redémarrage automatique quand un fichier .py est modifié  ===
# ==========================================================================
# Lancer simplement :  python app.py
# Un petit "surveillant" démarre le vrai serveur, surveille tes fichiers .py
# et relance le serveur tout seul à chaque sauvegarde (dans le même terminal).
# Sans ça (ex : "flask run", "flask db migrate") ce bloc ne fait RIEN.
# Pour le désactiver : définir la variable d'environnement FACENET_SANS_AUTO_RELOAD=1
import os
import sys


def _lancer_avec_redemarrage_auto():
    import subprocess
    import time

    racine = os.path.abspath(os.path.dirname(__file__))
    ignores = {'__pycache__', 'instance', 'static', 'uploads', 'certs', 'migrations',
               'node_modules', 'site-packages', 'venv', 'env', '.venv'}

    def instantane():
        etat = {}
        for dossier, sous_dossiers, fichiers in os.walk(racine):
            sous_dossiers[:] = [
                d for d in sous_dossiers
                if d not in ignores and not d.startswith('.')
                and not os.path.exists(os.path.join(dossier, d, 'pyvenv.cfg'))
            ]
            for nom in fichiers:
                if nom.endswith('.py'):
                    chemin = os.path.join(dossier, nom)
                    try:
                        etat[chemin] = os.stat(chemin).st_mtime
                    except OSError:
                        pass
        return etat

    def arreter(proc):
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except Exception:
                proc.kill()

    env = dict(os.environ)
    env['FACENET_ENFANT'] = '1'
    env['PYTHONUNBUFFERED'] = '1'   # AJOUT : les print()/erreurs s'affichent tout de suite dans le terminal
    commande = [sys.executable, os.path.abspath(__file__)] + sys.argv[1:]
    enfant = None
    try:
        while True:
            etat = instantane()
            print("--- [auto-reload] Démarrage du serveur (surveillance des fichiers .py) ---", flush=True)
            enfant = subprocess.Popen(commande, env=env)
            fichier_modifie = None
            while fichier_modifie is None:
                time.sleep(1)
                nouvel_etat = instantane()
                if nouvel_etat != etat:
                    changes = [p for p in set(nouvel_etat) | set(etat) if nouvel_etat.get(p) != etat.get(p)]
                    fichier_modifie = os.path.basename(changes[0]) if changes else 'fichier'
                elif enfant.poll() is not None:
                    if enfant.returncode == 0:
                        return
                    print(f"--- [auto-reload] Le serveur s'est arrêté (code {enfant.returncode}, erreur ci-dessus). "
                          "En attente d'une modification de fichier pour relancer... ---", flush=True)
                    while instantane() == etat:
                        time.sleep(1)
                    fichier_modifie = 'fichier'
            arreter(enfant)
            print(f"--- [auto-reload] Modification détectée ({fichier_modifie}) → redémarrage ---", flush=True)
            time.sleep(0.5)  # laisse l'éditeur finir d'enregistrer
    except KeyboardInterrupt:
        pass
    finally:
        arreter(enfant)


if (__name__ == '__main__'
        and os.environ.get('FACENET_ENFANT') != '1'
        and os.environ.get('FACENET_SANS_AUTO_RELOAD') != '1'):
    _lancer_avec_redemarrage_auto()
    sys.exit(0)
# ==========================================================================


from flask import Flask, session, g, render_template_string, request
from extensions import db, login_manager
from models import User
from routes import main_bp, groupe_bp, reels_bp, telemetry_bp
from flask_migrate import Migrate
from flask_bcrypt import Bcrypt
from datetime import timedelta, datetime
from sqlalchemy import event, inspect, text
from sqlalchemy.engine import Engine

# ← AJOUT 1 : import de SocketIO pour les appels
from sockets import socketio, init_socketio

app = Flask(__name__)
from anniversaires import anniv_bp
app.register_blueprint(anniv_bp)

from karaoke_search import karaoke_search_bp
app.register_blueprint(karaoke_search_bp, url_prefix='/karaoke')


# ==========================================================================
# ====  AJOUT ROBUSTESSE : les erreurs s'affichent TOUJOURS dans le terminal =
# ==========================================================================
# CAUSE du problème constaté (ce n'était pas le SSL) : routes.py (console développeur)
# attache un gestionnaire de journal "en mémoire" à la racine de logging. Flask ne
# branche alors plus son affichage terminal par défaut (il croit qu'un gestionnaire
# existe déjà) : les erreurs partaient dans la mémoire et rien ne s'écrivait à l'écran.
# Ici on ajoute UN gestionnaire qui écrit dans le terminal ; celui de la console
# développeur n'est pas retiré, donc rien ne change de ce côté.
import logging
import threading
import traceback

for _flux in (sys.stdout, sys.stderr):      # affichage immédiat, et un caractère exotique ne fait plus planter print()
    try:
        _flux.reconfigure(line_buffering=True, errors='replace')
    except Exception:
        pass


class _FormatJournalConsole(logging.Formatter):
    def format(self, record):
        if record.name == 'werkzeug' and not record.exc_info:
            return record.getMessage()          # lignes de requêtes HTTP comme d'habitude
        return super().format(record)


class _FiltreJournalConsole(logging.Filter):
    def filter(self, record):
        if record.name.startswith(('socketio', 'engineio')):
            return False                        # ces deux-là s'affichent déjà seuls (évite les doublons)
        if record.levelno >= logging.WARNING:
            return True                         # avertissements et erreurs : toujours visibles
        return record.name == 'werkzeug' or record.name.startswith('facenet')


def _configurer_journal_console():
    racine = logging.getLogger()
    if any(getattr(h, '_facenet_console', False) for h in racine.handlers):
        return
    logging.disable(logging.NOTSET)             # au cas où un module aurait coupé les journaux
    gestionnaire = logging.StreamHandler(sys.stderr)
    gestionnaire.setLevel(logging.INFO)
    gestionnaire.setFormatter(_FormatJournalConsole('%(asctime)s [%(levelname)s] %(name)s : %(message)s', '%H:%M:%S'))
    gestionnaire.addFilter(_FiltreJournalConsole())
    gestionnaire._facenet_console = True
    racine.addHandler(gestionnaire)
    if racine.level == logging.NOTSET or racine.level > logging.INFO:
        racine.setLevel(logging.INFO)
    # Bibliothèques bavardes : routes.py met la racine en INFO, ce qui faisait journaliser
    # chaque requête SQL (lent et inutile). Elles restent à WARNING sauf réglage explicite.
    for nom in ('sqlalchemy.engine', 'sqlalchemy.pool', 'alembic', 'urllib3', 'PIL', 'asyncio', 'charset_normalizer'):
        journal = logging.getLogger(nom)
        if journal.level == logging.NOTSET:
            journal.setLevel(logging.WARNING)
    for nom in ('socketio.server', 'engineio.server'):
        logging.getLogger(nom).disabled = False
    if os.environ.get('FACENET_LOG_REQUETES') == '0':
        logging.getLogger('werkzeug').setLevel(logging.WARNING)   # masque seulement les lignes "GET /feed 200"


_configurer_journal_console()

# Erreurs survenues dans un thread (tâche de fond, timer...) : signalées clairement.
_HOOK_THREAD_DEFAUT = threading.excepthook


def _hook_erreur_thread(args):
    try:
        print(f"[ERREUR thread '{getattr(args.thread, 'name', '?')}'] "
              f"{args.exc_type.__name__}: {args.exc_value}", file=sys.stderr, flush=True)
    except Exception:
        pass
    _HOOK_THREAD_DEFAUT(args)


threading.excepthook = _hook_erreur_thread
# ==========================================================================

# --- Configuration propre pour le dossier 'instance' ---
basedir = os.path.abspath(os.path.dirname(__file__))
instance_path = os.path.join(basedir, 'instance')
os.makedirs(instance_path, exist_ok=True)

# AJOUT ROBUSTESSE : dossiers d'envoi créés dès le chargement, avec un chemin absolu
# (avant : créés seulement au lancement et relatifs au dossier courant du terminal).
for _sous_dossier in ('static/uploads', 'static/uploads/vocaux'):
    try:
        os.makedirs(os.path.join(basedir, *_sous_dossier.split('/')), exist_ok=True)
    except OSError as _e_dossier:
        print(f"[dossiers] Impossible de créer {_sous_dossier} : {_e_dossier}")


# ==========================================================================
# ====  AJOUT : HTTPS local (certificat auto-signé généré une seule fois)  ==
# ==========================================================================
def _adresses_locales():
    import socket
    ips = {'127.0.0.1'}
    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            ips.add(ip)
    except Exception:
        pass
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(('8.8.8.8', 80))   # n'envoie aucun paquet : sert juste à connaître ton IP réseau
        ips.add(sock.getsockname()[0])
        sock.close()
    except Exception:
        pass
    return sorted(ips)


def _preparer_certificat():
    """Retourne (fichier_certificat, fichier_cle) ou None si HTTPS impossible."""
    try:
        import ipaddress
        from cryptography import x509
        from cryptography.x509.oid import NameOID
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
    except ImportError:
        print("--- [HTTPS] Module 'cryptography' introuvable -> le serveur reste en HTTP. "
              "Installe-le avec :  pip install cryptography ---")
        return None
    try:
        dossier = os.path.join(basedir, 'certs')
        os.makedirs(dossier, exist_ok=True)
        cert_path = os.path.join(dossier, 'facenet-cert.pem')
        key_path = os.path.join(dossier, 'facenet-key.pem')
        ips_path = os.path.join(dossier, 'facenet-ips.txt')
        ips = _adresses_locales()

        # On réutilise le même certificat tant que tes adresses réseau n'ont pas changé
        if os.path.exists(cert_path) and os.path.exists(key_path) and os.path.exists(ips_path):
            with open(ips_path, 'r', encoding='utf-8') as f:
                if f.read().split() == ips:
                    return cert_path, key_path

        cle = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        nom = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'FaceNet local')])
        alt = [x509.DNSName('localhost')] + [x509.IPAddress(ipaddress.ip_address(ip)) for ip in ips]
        certificat = (
            x509.CertificateBuilder()
            .subject_name(nom)
            .issuer_name(nom)
            .public_key(cle.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.utcnow() - timedelta(days=1))
            .not_valid_after(datetime.utcnow() + timedelta(days=825))
            .add_extension(x509.SubjectAlternativeName(alt), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(cle, hashes.SHA256())
        )
        with open(key_path, 'wb') as f:
            f.write(cle.private_bytes(serialization.Encoding.PEM,
                                      serialization.PrivateFormat.TraditionalOpenSSL,
                                      serialization.NoEncryption()))
        with open(cert_path, 'wb') as f:
            f.write(certificat.public_bytes(serialization.Encoding.PEM))
        with open(ips_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(ips))
        print(f"--- [HTTPS] Certificat local créé pour : {', '.join(ips)} ---")
        return cert_path, key_path
    except Exception as e:
        print(f"--- [HTTPS] Impossible de créer le certificat ({e}) -> le serveur reste en HTTP ---")
        return None


# MODIFIÉ : le serveur tourne maintenant en HTTPS par défaut.
# Pour revenir en HTTP simple, définir FACENET_HTTPS=0 (ou FACENET_HTTP=1).
# Si le certificat ne peut pas être créé (ex : module 'cryptography' absent), le serveur
# reste automatiquement en HTTP et les cookies Secure sont désactivés : rien ne casse.
_CERTIFICAT = None
if (__name__ == '__main__'
        and os.environ.get('FACENET_HTTPS') != '0'
        and os.environ.get('FACENET_HTTP') != '1'):
    _CERTIFICAT = _preparer_certificat()
UTILISER_HTTPS = _CERTIFICAT is not None

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(instance_path, 'facenet.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# AJOUT : la clé peut venir d'une variable d'environnement (FACENET_SECRET_KEY) ; sans elle, la valeur d'avant est utilisée (rien ne change).
app.config['SECRET_KEY'] = os.environ.get('FACENET_SECRET_KEY', 'votre_cle_secrete_discrete_facenet')

# --- Rendre la connexion de l'utilisateur robuste et durable ---
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=14)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_REFRESH_EACH_REQUEST'] = True
# AJOUT : noms de cookies propres à FaceNet. Les cookies ne sont pas isolés par port : un autre
# projet Flask lancé sur la même adresse (localhost / même IP) écrasait le cookie "session"
# et FaceNet perdait la connexion juste après le login.
app.config['SESSION_COOKIE_NAME'] = 'facenet_session'
app.config['REMEMBER_COOKIE_NAME'] = 'facenet_remember'
# IMPORTANT : le serveur tourne actuellement en HTTP simple (voir socketio.run
# plus bas, sans ssl_context). Un cookie "Secure" n'est JAMAIS accepté par le
# navigateur sur une connexion non chiffrée : il était donc systématiquement
# rejeté, ce qui vidait la session entre deux requêtes (ex : le code SMS
# disparaissait avant /check-code). Remettre à True le jour où l'app tourne
# réellement en HTTPS (certificat valide ou ssl_context='adhoc').
# Ajusté automatiquement : True seulement si le serveur tourne réellement en HTTPS.
app.config['SESSION_COOKIE_SECURE'] = UTILISER_HTTPS

app.config['REMEMBER_COOKIE_DURATION'] = timedelta(days=14)
app.config['REMEMBER_COOKIE_HTTPONLY'] = True
app.config['REMEMBER_COOKIE_SECURE'] = UTILISER_HTTPS
app.config['TEMPLATES_AUTO_RELOAD'] = True
# AJOUT ROBUSTESSE : taille maximale d'une requête (évite qu'un envoi énorme sature la mémoire).
# 512 Mo par défaut, largement au-dessus d'un reel ; réglable avec FACENET_MAX_UPLOAD_MB.
# setdefault : si une valeur est déjà posée ailleurs, elle est respectée.
try:
    app.config.setdefault('MAX_CONTENT_LENGTH', int(os.environ.get('FACENET_MAX_UPLOAD_MB', '512')) * 1024 * 1024)
except ValueError:
    app.config.setdefault('MAX_CONTENT_LENGTH', 512 * 1024 * 1024)

# --- AJOUT : envoi d'e-mails (codes à 6 chiffres) via Flask-Mail ---
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USE_SSL'] = False
app.config['MAIL_USERNAME'] = 'tsapingoumtsad613@gmail.com'
app.config['MAIL_PASSWORD'] = os.environ.get('FACENET_MAIL_PASSWORD', '')  # Configure le secret via l'environnement.
app.config['MAIL_DEFAULT_SENDER'] = ('FaceNet', 'tsapingoumtsad613@gmail.com')

app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'pool_pre_ping': True}

# --- AJOUT VITESSE : réglages SQLite (lectures/écritures simultanées bien plus fluides) ---
@event.listens_for(Engine, "connect")
def _reglages_sqlite(dbapi_connection, connection_record):
    if dbapi_connection.__class__.__module__.startswith('sqlite3'):
        try:
            curseur = dbapi_connection.cursor()
            curseur.execute("PRAGMA journal_mode=WAL")
            curseur.execute("PRAGMA synchronous=NORMAL")
            curseur.execute("PRAGMA busy_timeout=10000")
            curseur.execute("PRAGMA cache_size=-65536")     # ~64 Mo de cache en memoire
            curseur.execute("PRAGMA temp_store=MEMORY")     # tris/index temporaires en RAM
            curseur.execute("PRAGMA mmap_size=268435456")   # lecture memoire-mappee (256 Mo)
            curseur.close()
        except Exception as e:
            print(f"[sqlite] Réglages de performance non appliqués : {e}")


# --- AJOUT VITESSE : compression des pages/JSON si Flask-Compress est installé (facultatif) ---
try:
    from flask_compress import Compress
    Compress(app)
except ImportError:
    pass

db.init_app(app)
login_manager.init_app(app)
login_manager.login_view = 'main.login'

# AJOUT i18n : traduction de l'interface côté serveur (voir i18n.py). Réutilise la langue déjà
# enregistrée (compte > cookie > session) ; ne touche jamais au contenu de la base.
from i18n import init_i18n
from routes import _langue_courante
init_i18n(app, _langue_courante)

@login_manager.user_loader
def load_user(user_id):
    # AJOUT : un identifiant de session invalide (vide, texte, cookie abîmé) ne fait plus planter la
    # requête : l'utilisateur est simplement considéré comme non connecté.
    # Une vraie erreur de base de données, elle, reste remontée comme avant (jamais "déconnecté" à tort).
    try:
        identifiant = int(user_id)
    except (TypeError, ValueError):
        return None
    return db.session.get(User, identifiant)


def _id_utilisateur_connecte():
    """AJOUT : id de l'utilisateur connecté, où que soit stocké son identifiant.
    L'application utilise session['user_id'] ; Flask-Login utilise session['_user_id'] (c'est la seule
    clé présente quand la connexion est rétablie par le cookie "se souvenir de moi")."""
    try:
        valeur = session.get('user_id')
        if valeur is None:
            valeur = session.get('_user_id')
        return int(valeur) if valeur is not None else None
    except (TypeError, ValueError, RuntimeError):
        return None

@app.before_request
def rendre_session_permanente():
    session.permanent = True


# AJOUT DIAGNOSTIC (lecture seule, à supprimer une fois le problème réglé) :
# affiche si le navigateur renvoie bien le cookie de session sur /feed, /login et l'inscription.
@app.before_request
def diagnostic_session_connexion():
    try:
        if request.path in ('/feed', '/login', '/signup-process'):
            print(f"[diag-session] {request.method} {request.path} | cookies reçus : {list(request.cookies.keys())} | user_id en session : {'user_id' in session} | https : {request.is_secure}", flush=True)
    except Exception:
        pass


# ==========================================================================
# ============  AJOUT ADDITIF : maintenance automatique  =================
# ==========================================================================
_derniere_verif_expirations = None


def _desactiver_abonnements_expires():
    try:
        maintenant = datetime.utcnow()
        User.query.filter(
            User.has_badge_bleu == True,          # noqa: E712
            User.badge_expire.isnot(None),
            User.badge_expire <= maintenant
        ).update(
            {User.has_badge_bleu: False},
            synchronize_session=False
        )
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[maintenance] Erreur désactivation abonnements expirés : {e}")


def _desactiver_boosts_expires():
    try:
        from models import PostBoost
        maintenant = datetime.utcnow()
        if hasattr(PostBoost, 'date_fin'):
            PostBoost.query.filter(
                PostBoost.status == 'active',
                PostBoost.date_fin.isnot(None),
                PostBoost.date_fin <= maintenant
            ).update(
                {PostBoost.status: 'expired'},
                synchronize_session=False
            )
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[maintenance] Erreur désactivation boosts expirés : {e}")


@app.before_request
def verifier_expirations_periodiquement():
    global _derniere_verif_expirations
    try:
        maintenant = datetime.utcnow()
        if (_derniere_verif_expirations is None
                or (maintenant - _derniere_verif_expirations).total_seconds() > 60):
            _derniere_verif_expirations = maintenant
            _desactiver_abonnements_expires()
            _desactiver_boosts_expires()
            try:
                from escrow_service import traiter_transactions_planifiees
                traiter_transactions_planifiees()
            except Exception as e:
                db.session.rollback()
                print(f"[maintenance] Erreur séquestre : {e}")
    except Exception as e:
        print(f"[maintenance] Erreur vérification périodique des expirations : {e}")


@app.before_request
def mettre_a_jour_last_seen():
    try:
        # Les fichiers statiques (images, css, js...) n'ont pas besoin de toucher la base
        if request.path.startswith('/static/'):
            return
        user_id = _id_utilisateur_connecte()     # MODIFIÉ : reconnaît aussi la clé Flask-Login (_user_id)
        if not user_id:
            return
        # VITESSE : on retient en session l'heure de la dernière mise à jour. Pendant 10 s on ne
        # touche plus du tout à la base (avant : une requête SQL à chaque appel, même pour un simple JSON).
        import time as _time
        agora = _time.time()
        dernier_ts = session.get('_ls_ts')
        if dernier_ts and 0 <= agora - dernier_ts < 10:
            return
        utilisateur = db.session.get(User, int(user_id))
        if utilisateur is not None:
            maintenant = datetime.utcnow()
            # Écrit en base au plus toutes les 10 secondes (au lieu de chaque requête)
            if (utilisateur.last_seen is None
                    or (maintenant - utilisateur.last_seen).total_seconds() >= 10):
                utilisateur.last_seen = maintenant
                db.session.commit()
            session['_ls_ts'] = agora
    except Exception as e:
        db.session.rollback()
        print(f"[maintenance] Erreur mise à jour last_seen : {e}")


migrate = Migrate(app, db)
bcrypt = Bcrypt(app)

# --- AJOUT : Marketplace Pro (séquestre, messagerie Marketplace) ---
import marketplace_pro
marketplace_pro.brancher_sur_main(main_bp)      # ajoute main.item_detail ; DOIT être avant register_blueprint(main_bp)

# --- AJOUT : Cercle familial (table lien_familial créée par db.create_all, routes /settings/famille et /famille/...) ---
import famille
famille.brancher_sur_main(main_bp)                # DOIT être avant register_blueprint(main_bp)

app.register_blueprint(main_bp)

# --- AJOUT : Contrôle parental par invitation (le parent invite un ami enfant ; l'enfant doit accepter ; blocage programmé) ---
# Protégé : si ce module a un problème, le reste de l'application démarre normalement. Les tables sont créées par db.create_all() plus bas.
try:
    import controle_parental_invitations
    controle_parental_invitations.brancher(app)
except Exception as _e_pinv:
    print(f"--- [contrôle parental par invitation] non chargé : {_e_pinv} ---")

app.register_blueprint(marketplace_pro.marketplace_pro_bp)
import marketplace_detail                         # AJOUT : page détail d'une annonce (tables créées par db.create_all plus bas)
app.register_blueprint(marketplace_detail.marketplace_detail_bp)
import marketplace_vous                          # AJOUT : pages « Vous » du Marketplace (enregistrement direct, erreurs visibles)
app.register_blueprint(marketplace_vous.marketplace_vous_bp)
_mkv = sorted(r.rule for r in app.url_map.iter_rules() if r.endpoint.startswith('marketplace_vous.'))
print("OK marketplace_vous : %d routes chargées (/marketplace/vous présent : %s)" % (len(_mkv), '/marketplace/vous' in _mkv))
app.register_blueprint(groupe_bp)
app.register_blueprint(reels_bp)
app.register_blueprint(telemetry_bp)

# --- AJOUT : Pack Sécurité Présidentielle (nouveau blueprint, aucune route existante modifiée) ---
from pack_securite import pack_securite_bp
app.register_blueprint(pack_securite_bp)

# --- AJOUT : e-mails OTP + réinitialisation du mot de passe par code ---
# Protégé : si Flask-Mail n'est pas installé, le reste de l'application démarre normalement.
try:
    from email_otp import mail, otp_bp
    mail.init_app(app)
    app.register_blueprint(otp_bp)
except ImportError as _e_mail:
    print(f"--- [E-MAIL] Module indisponible ({_e_mail}) -> installe-le avec :  pip install Flask-Mail ---")

# ← AJOUT 2 : initialisation de SocketIO (après les blueprints)
init_socketio(app)

# ==========================================================================
# ====  AJOUT ROBUSTESSE : colonnes de models.py absentes de la base  ======
# ==========================================================================
# db.create_all() crée les tables manquantes mais ne touche JAMAIS aux tables existantes :
# toute colonne ajoutée plus tard dans models.py provoquait « no such column » (erreur 500)
# sur une base créée avant. Ce bloc compare chaque modèle à la base et AJOUTE uniquement les
# colonnes manquantes (ALTER TABLE ... ADD COLUMN). Il ne supprime, ne renomme et ne modifie rien.
# Idempotent : une fois la base à jour, il ne fait plus rien.
import re as _re_migration


def _defaut_sql_colonne(col, dialecte):
    """Valeur par défaut SQL constante (seule forme acceptée par SQLite pour ADD COLUMN), sinon None."""
    def litteral(v):
        if isinstance(v, bool):
            return '1' if v else '0'
        if isinstance(v, (int, float)):
            return repr(v)
        if isinstance(v, str):
            return "'" + v.replace("'", "''") + "'"
        return None
    try:
        sd = col.server_default
        if sd is not None:
            arg = getattr(sd, 'arg', None)
            if isinstance(arg, str):
                return litteral(arg)
            if arg is not None:
                texte = str(arg.compile(dialect=dialecte, compile_kwargs={'literal_binds': True})).strip()
                if _re_migration.fullmatch(r"-?\d+(\.\d+)?|'(?:[^']|'')*'", texte):
                    return texte
        defaut = col.default
        if defaut is not None and getattr(defaut, 'is_scalar', False):
            return litteral(defaut.arg)
    except Exception:
        pass
    return None


def _ajouter_colonnes_manquantes():
    try:
        dialecte = db.engine.dialect
        if dialecte.name != 'sqlite':
            return
        prep = dialecte.identifier_preparer
        inspecteur = inspect(db.engine)
        tables_base = set(inspecteur.get_table_names())
        ajoutees = []
        for table in db.metadata.sorted_tables:
            if table.name not in tables_base:
                continue          # table absente : db.create_all() vient de la créer complète
            existantes = {c['name'] for c in inspecteur.get_columns(table.name)}
            for col in table.columns:
                if col.name in existantes or col.primary_key:
                    continue
                try:
                    sql = (f"ALTER TABLE {prep.quote(table.name)} ADD COLUMN "
                           f"{prep.quote(col.name)} {col.type.compile(dialect=dialecte)}")
                    defaut = _defaut_sql_colonne(col, dialecte)
                    if defaut is not None:
                        sql += f" DEFAULT {defaut}"
                    with db.engine.begin() as connexion:
                        connexion.execute(text(sql))
                    ajoutees.append(f"{table.name}.{col.name}")
                except Exception as e:
                    print(f"[schema] Colonne {table.name}.{col.name} non ajoutée : {e}")
        if ajoutees:
            print(f"--- Schéma mis à jour : {len(ajoutees)} colonne(s) ajoutée(s) -> {', '.join(ajoutees)} ---")
        else:
            print("--- Schéma complet : toutes les colonnes de models.py existent dans la base. ---")
    except Exception as e:
        print(f"[schema] Vérification des colonnes non appliquée : {e}")


# --- Initialisation du contexte pour créer les tables ---
with app.app_context():
    from models import User, Publication, Group, Message
    db.create_all()

    # Migration additive et idempotente : db.create_all() ne modifie pas les
    # tables existantes. On ajoute uniquement les deux colonnes IA manquantes.
    try:
        colonnes_pub = {c['name'] for c in inspect(db.engine).get_columns('publication')}
        with db.engine.begin() as connexion:
            if 'mention_ia' not in colonnes_pub:
                connexion.execute(text(
                    'ALTER TABLE publication ADD COLUMN mention_ia BOOLEAN NOT NULL DEFAULT 0'
                ))
            if 'mention_ia_type' not in colonnes_pub:
                connexion.execute(text(
                    'ALTER TABLE publication ADD COLUMN mention_ia_type VARCHAR(30)'
                ))
        print("--- Schéma IA vérifié (migration additive). ---")
    except Exception as e:
        print(f"[schema] Migration IA non appliquée : {e}")

    _ajouter_colonnes_manquantes()      # AJOUT : complète les colonnes manquantes (voir plus haut)
    print("--- Base de données initialisée avec succès dans 'instance/facenet.db' ! ---")


# Worker persistant : il tourne côté serveur, indépendamment des visites des
# utilisateurs. Les UPDATE conditionnels dans routes.py empêchent les doublons
# lorsque plusieurs workers/processus démarrent simultanément.
def _boucle_publications_programmees():
    while True:
        try:
            with app.app_context():
                from routes import traiter_publications_programmees
                nombre = traiter_publications_programmees(limite=20)
                if nombre:
                    print(f"[programmation] {nombre} publication(s) exécutée(s).", flush=True)
        except Exception as e:
            try:
                db.session.rollback()
            except Exception:
                pass
            print(f"[programmation] Worker en attente après erreur : {e}", flush=True)
        try:
            socketio.sleep(10)
        except Exception:
            import time as _scheduler_time
            _scheduler_time.sleep(10)


if os.environ.get('FACENET_DISABLE_SCHEDULER') != '1':
    try:
        socketio.start_background_task(_boucle_publications_programmees)
        print("--- [programmation] Service de publication automatique démarré (vérification toutes les 10 s). ---")
    except Exception as e:
        print(f"--- [programmation] Worker non démarré : {e} ---")

@app.context_processor
def utility_processor():
    def get_user_by_id(id):
        return db.session.get(User, id)

    def get_user(user_id):
        if not user_id:
            return None
        try:
            return db.session.get(User, int(user_id))
        except (TypeError, ValueError):
            return None

    return dict(get_user_by_id=get_user_by_id, get_user=get_user)


@app.context_processor
def injecter_current_user_global():
    try:
        user_id = session.get('user_id')
        if not user_id:
            return {}
        utilisateur = db.session.get(User, int(user_id))
        if utilisateur is None:
            return {}
        return dict(current_user=utilisateur)
    except Exception as e:
        print(f"[context_processor] Erreur chargement current_user global : {e}")
        return {}


# --- AJOUT ROBUSTESSE : les appels JavaScript (fetch / API) reçoivent du JSON, pas une page HTML ---
# Avant : un fetch qui tombait sur une 404/500 recevait du HTML et plantait au res.json().
# Les pages normales du navigateur sont strictement inchangées.
from flask import jsonify as _jsonify


def _requete_attend_json():
    try:
        if request.path.startswith('/api/') or request.is_json:
            return True
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return True
        meilleur = request.accept_mimetypes.best_match(['application/json', 'text/html'])
        return (meilleur == 'application/json'
                and request.accept_mimetypes['application/json'] > request.accept_mimetypes['text/html'])
    except Exception:
        return False


# --- AJOUT ADDITIF : pages d'erreur propres (404 / 500) ---
@app.errorhandler(404)
def page_introuvable(erreur):
    if _requete_attend_json():
        return _jsonify({'success': False, 'error': 'Ressource introuvable.'}), 404
    html = """
    <!DOCTYPE html>
    <html lang="fr"><head><meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Page introuvable — FaceNet</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background:#f0f2f5;
               display:flex; align-items:center; justify-content:center; min-height:100vh; margin:0; color:#050505; }
        .box { text-align:center; background:#fff; padding:40px 30px; border-radius:12px; box-shadow:0 2px 10px rgba(0,0,0,.08); max-width:380px; }
        h1 { font-size:56px; margin:0; color:#1877f2; }
        p { color:#65676b; margin:12px 0 20px; }
        a { background:#1877f2; color:#fff; text-decoration:none; padding:10px 22px; border-radius:8px; font-weight:600; }
    </style></head>
    <body><div class="box">
        <h1>404</h1>
        <p>Cette page n'existe pas ou a été déplacée.</p>
        <a href="/feed">Retour à l'accueil</a>
    </div></body></html>
    """
    return render_template_string(html), 404


@app.errorhandler(500)
def erreur_serveur(erreur):
    try:
        db.session.rollback()
    except Exception:
        pass
    # AJOUT : une ligne claire dans le terminal (le détail complet est écrit juste au-dessus par Flask)
    try:
        origine = getattr(erreur, 'original_exception', None) or erreur
        uid = _id_utilisateur_connecte()
        qui = 'non connecté'
        if uid:
            qui = f'utilisateur #{uid}'
            try:
                u = db.session.get(User, uid)
                if u is not None and getattr(u, 'username', None):
                    qui += f' (@{u.username})'
            except Exception:
                db.session.rollback()
        endroit = ''
        if getattr(origine, '__traceback__', None):
            dernier = traceback.extract_tb(origine.__traceback__)[-1]
            endroit = f' | {os.path.basename(dernier.filename)}:{dernier.lineno} dans {dernier.name}()'
        print(f"[ERREUR 500] {request.method} {request.path} | {qui}{endroit} | "
              f"{type(origine).__name__}: {origine}", file=sys.stderr, flush=True)
    except Exception:
        pass
    if _requete_attend_json():
        return _jsonify({'success': False, 'error': 'Une erreur est survenue. Réessaie dans un instant.'}), 500
    html = """
    <!DOCTYPE html>
    <html lang="fr"><head><meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Erreur — FaceNet</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background:#f0f2f5;
               display:flex; align-items:center; justify-content:center; min-height:100vh; margin:0; color:#050505; }
        .box { text-align:center; background:#fff; padding:40px 30px; border-radius:12px; box-shadow:0 2px 10px rgba(0,0,0,.08); max-width:380px; }
        h1 { font-size:22px; margin:0 0 10px; color:#e41e3f; }
        p { color:#65676b; margin:0 0 20px; }
        a { background:#1877f2; color:#fff; text-decoration:none; padding:10px 22px; border-radius:8px; font-weight:600; }
    </style></head>
    <body><div class="box">
        <h1>Une erreur est survenue</h1>
        <p>Nous travaillons déjà à la résoudre. Réessaie dans un instant.</p>
        <a href="/feed">Retour à l'accueil</a>
    </div></body></html>
    """
    return render_template_string(html), 500


# ==========================================================================
# ====  AJOUT ROBUSTESSE : erreurs 403 / 405 / 413 / 429 + en-têtes + santé ===
# ==========================================================================
def _reponse_erreur_generique(code, titre, message):
    if _requete_attend_json():
        return _jsonify({'success': False, 'error': message}), code
    html = """
    <!DOCTYPE html>
    <html lang="fr"><head><meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ titre }} — FaceNet</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; background:#f0f2f5;
               display:flex; align-items:center; justify-content:center; min-height:100vh; margin:0; color:#050505; }
        .box { text-align:center; background:#fff; padding:40px 30px; border-radius:12px; box-shadow:0 2px 10px rgba(0,0,0,.08); max-width:380px; }
        h1 { font-size:22px; margin:0 0 10px; color:#1877f2; }
        p { color:#65676b; margin:0 0 20px; }
        a { background:#1877f2; color:#fff; text-decoration:none; padding:10px 22px; border-radius:8px; font-weight:600; }
    </style></head>
    <body><div class="box">
        <h1>{{ titre }}</h1>
        <p>{{ message }}</p>
        <a href="/feed">Retour à l'accueil</a>
    </div></body></html>
    """
    return render_template_string(html, titre=titre, message=message), code


@app.errorhandler(403)
def acces_refuse(erreur):
    return _reponse_erreur_generique(403, "Accès refusé", "Tu n'as pas l'autorisation d'accéder à cette page.")


@app.errorhandler(405)
def methode_non_autorisee(erreur):
    return _reponse_erreur_generique(405, "Action non autorisée", "Cette action n'est pas disponible ici.")


@app.errorhandler(413)
def fichier_trop_volumineux(erreur):
    limite = app.config.get('MAX_CONTENT_LENGTH')
    precision = f" (maximum {int(limite / (1024 * 1024))} Mo)" if limite else ""
    return _reponse_erreur_generique(413, "Fichier trop volumineux", "Le fichier envoyé est trop volumineux" + precision + ".")


@app.errorhandler(429)
def trop_de_requetes(erreur):
    return _reponse_erreur_generique(429, "Trop de requêtes", "Merci de patienter un instant avant de réessayer.")


# En-têtes de sécurité discrets. setdefault : si une route en pose déjà un, elle garde le sien.
# (Pas de HSTS volontairement : avec le certificat auto-signé local, il bloquerait l'accès au site.)
@app.after_request
def ajouter_en_tetes_securite(response):
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
    return response


# Test de santé : https://<ton-ip>:5000/healthz -> {"status": "ok", "db": true}
def _sante_application():
    base_ok = True
    try:
        db.session.execute(text('SELECT 1'))
    except Exception:
        base_ok = False
        try:
            db.session.rollback()
        except Exception:
            pass
    return _jsonify({'status': 'ok' if base_ok else 'degrade', 'db': base_ok}), (200 if base_ok else 503)


app.add_url_rule('/healthz', 'facenet_healthz', _sante_application, methods=['GET'])


# --- Sauvegarde automatique de la base SQLite (au plus 1 par jour, on garde les 7 dernières) ---
# Copie cohérente via l'API de sauvegarde de SQLite (sans arrêter le serveur) dans instance/sauvegardes/.
# Désactiver : FACENET_SANS_SAUVEGARDE=1
def _sauvegarder_base():
    import glob
    import sqlite3
    import time as _t
    source_path = os.path.join(instance_path, 'facenet.db')
    if not os.path.exists(source_path):
        return
    dossier = os.path.join(instance_path, 'sauvegardes')
    os.makedirs(dossier, exist_ok=True)
    existantes = sorted(glob.glob(os.path.join(dossier, 'facenet-*.db')))
    if existantes and _t.time() - os.path.getmtime(existantes[-1]) < 24 * 3600:
        return
    destination = os.path.join(dossier, datetime.now().strftime('facenet-%Y%m%d-%H%M%S.db'))
    src = sqlite3.connect(source_path, timeout=30)
    dst = sqlite3.connect(destination)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    existantes = sorted(glob.glob(os.path.join(dossier, 'facenet-*.db')))
    for ancienne in existantes[:-7]:
        try:
            os.remove(ancienne)
        except OSError:
            pass
    print(f"--- [sauvegarde] Base copiée -> instance/sauvegardes/{os.path.basename(destination)} ---", flush=True)


def _boucle_sauvegardes():
    while True:
        try:
            _sauvegarder_base()
        except Exception as e:
            print(f"[sauvegarde] Non effectuée : {e}", flush=True)
        try:
            socketio.sleep(6 * 3600)
        except Exception:
            import time as _sauvegarde_time
            _sauvegarde_time.sleep(6 * 3600)


if os.environ.get('FACENET_SANS_SAUVEGARDE') != '1':
    try:
        socketio.start_background_task(_boucle_sauvegardes)
    except Exception as e:
        print(f"--- [sauvegarde] Service non démarré : {e} ---")


_EXT_STATIQUES_CACHEES = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.avif', '.svg', '.ico',
                          '.woff', '.woff2', '.ttf', '.mp3', '.wav', '.ogg', '.m4a', '.mp4', '.webm')


@app.after_request
def add_no_cache_headers(response):
    # Fichiers statiques : le navigateur les garde et vérifie juste s'ils ont changé (réponse 304
    # quasi instantanée) au lieu de les retélécharger à chaque page. Toujours à jour, mais beaucoup plus rapide.
    if request.path.startswith('/static/'):
        # VITESSE : images, polices, audio et vidéo sont gardées 1 h par le navigateur (plus d'aller-retour
        # réseau à chaque affichage). CSS / JS / HTML restent toujours revérifiés : tes modifications s'affichent tout de suite.
        if (request.path.lower().endswith(_EXT_STATIQUES_CACHEES)
                and response.status_code in (200, 206, 304)):
            response.headers["Cache-Control"] = "public, max-age=3600"
        else:
            response.headers["Cache-Control"] = "no-cache"
        return response
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


if __name__ == '__main__':
    DOSSIER_VOCAUX = os.path.join('static', 'uploads', 'vocaux')
    if not os.path.exists(DOSSIER_VOCAUX):
        os.makedirs(DOSSIER_VOCAUX)
        print(f"--- Dossier créé avec succès : {DOSSIER_VOCAUX}")

    if UTILISER_HTTPS:
        print("--- Serveur FaceNet en HTTPS sur le port 5000 -> ouvre https://<ton-ip>:5000 "
              "(avertissement du navigateur au 1er accès : 'Continuer') ---")
    else:
        print("--- Serveur FaceNet en HTTP sur le port 5000 ---")

    # Le redémarrage automatique est géré par le surveillant en haut du fichier,
    # donc use_reloader reste False ici (évite le crash Windows KeyError: 'WERKZEUG_SERVER_FD').
    options_ssl = {}
    if UTILISER_HTTPS:
        if getattr(socketio, 'async_mode', 'threading') == 'threading':
            options_ssl['ssl_context'] = _CERTIFICAT
        else:
            options_ssl['certfile'], options_ssl['keyfile'] = _CERTIFICAT

    # AJOUT : avec eventlet/gevent, Flask-SocketIO coupe le journal du serveur quand debug=False
    # (les erreurs n'apparaissaient plus). On le garde allumé ; FACENET_LOG_REQUETES=0 pour le réduire.
    options_journal = {}
    if getattr(socketio, 'async_mode', 'threading') in ('eventlet', 'gevent'):
        options_journal['log_output'] = os.environ.get('FACENET_LOG_REQUETES') != '0'

    socketio.run(
        app,
        host='0.0.0.0',
        port=5000,
        debug=(os.environ.get('FACENET_DEBUG') == '1'),   # VITESSE/SÉCURITÉ : mettre FACENET_DEBUG=1 pour retrouver le mode debug
        use_reloader=False,
        allow_unsafe_werkzeug=True,
        **options_ssl,
        **options_journal
    )