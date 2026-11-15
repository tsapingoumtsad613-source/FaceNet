"""
Qualité vidéo des reels — côté serveur.

Ce module ajoute :
  • GET  /api/reel/<pub_id>/video?q=auto|360|480|720|original   → sert la bonne version du fichier
  • GET  /api/reel/<pub_id>/qualites                            → état des versions (disponible / en préparation)
  • planifier_variantes(pub)     → à appeler après l'upload d'une vidéo (génération en arrière-plan)
  • supprimer_variantes(pub_id)  → à appeler quand une vidéo est supprimée définitivement
  • commande CLI  flask generer-variantes  → génère les versions des vidéos déjà en ligne

Principe : le fichier original n'est JAMAIS modifié. Les versions allégées sont créées avec ffmpeg
dans static/uploads/variantes/<pub_id>_<q>.mp4. Tant qu'une version n'est pas prête, la route sert
l'original (donc la vidéo se lit toujours) et lance la génération en arrière-plan.

Prérequis serveur : ffmpeg et ffprobe installés (apt install ffmpeg).

Le blueprint est supposé s'appeler `main` (comme dans url_for('main.profile')). Si ta variable
de blueprint porte un autre nom (bp, main_bp…), remplace `main` dans les deux décorateurs
@main.route et dans @main.cli ci-dessous.
"""
import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from flask import abort, current_app, jsonify, request, send_file
from flask_login import current_user, login_required

# ─── ADAPTE CES DEUX IMPORTS À TON PROJET ───────────────────────────────────
from . import main                      # le blueprint « main » (from app.routes import main, etc.)
from .models import Publication         # ton modèle de publication (champs : id, user_id, media_url, confidentialite)
# ────────────────────────────────────────────────────────────────────────────

# Hauteur du petit côté de la vidéo pour chaque qualité (un reel vertical 1080×1920 → 360 = 360×640).
QUALITES = {
    '360': {'court_cote': 360, 'crf': 30, 'maxrate': '700k',  'audio': '64k'},
    '480': {'court_cote': 480, 'crf': 28, 'maxrate': '1200k', 'audio': '96k'},
    '720': {'court_cote': 720, 'crf': 26, 'maxrate': '2500k', 'audio': '128k'},
}
EXTENSIONS_VIDEO = ('.mp4', '.webm', '.mov')
LOCK_PERIME_APRES = 30 * 60      # un verrou de génération plus vieux que 30 min est considéré mort
FFMPEG_TIMEOUT = 15 * 60         # une génération ne dépasse jamais 15 min

_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='variantes-video')
_en_cours = set()
_en_cours_lock = threading.Lock()


# ─────────────────────────── Chemins ───────────────────────────
def _dossier_uploads():
    return os.path.join(current_app.static_folder, 'uploads')


def _dossier_variantes():
    d = os.path.join(_dossier_uploads(), 'variantes')
    os.makedirs(d, exist_ok=True)
    return d


def _chemin_original(pub):
    """Chemin disque de la vidéo d'origine, ou None si ce n'est pas une vidéo locale."""
    if not pub or not pub.media_url:
        return None
    if not pub.media_url.lower().endswith(EXTENSIONS_VIDEO):
        return None
    base = os.path.realpath(_dossier_uploads())
    chemin = os.path.realpath(os.path.join(base, pub.media_url))
    if not chemin.startswith(base + os.sep) or not os.path.isfile(chemin):
        return None
    return chemin


def _chemin_variante(pub_id, q):
    return os.path.join(_dossier_variantes(), f'{int(pub_id)}_{q}.mp4')


def _marqueur_identique(pub_id, q):
    """Fichier vide : la source est déjà aussi petite que cette qualité, on sert l'original."""
    return _chemin_variante(pub_id, q)[:-4] + '.orig'


def _variante_a_jour(pub_id, q, chemin_source):
    v = _chemin_variante(pub_id, q)
    return os.path.isfile(v) and os.path.getsize(v) > 0 and os.path.getmtime(v) >= os.path.getmtime(chemin_source)


def _identique_a_jour(pub_id, q, chemin_source):
    m = _marqueur_identique(pub_id, q)
    return os.path.isfile(m) and os.path.getmtime(m) >= os.path.getmtime(chemin_source)


# ─────────────────────────── Visibilité ───────────────────────────
def _peut_voir(pub):
    """Mêmes règles que la publication : public = tout le monde connecté ; privé = auteur seul ;
    amis = auteur + amis. Adapte `_sont_amis` à la fonction d'amitié de ton projet."""
    niveau = pub.confidentialite or 'public'
    if niveau == 'public' or pub.user_id == current_user.id:
        return True
    if niveau == 'amis':
        return _sont_amis(current_user.id, pub.user_id)
    return False


def _sont_amis(a, b):
    # ─── ADAPTE ─── remplace par ta vraie vérification d'amitié, par exemple :
    #   from .utils import sont_amis ; return sont_amis(a, b)
    # Tant que ce n'est pas branché, on refuse (plus sûr) : l'original reste disponible via /static.
    try:
        from .utils import sont_amis  # noqa
        return bool(sont_amis(a, b))
    except Exception:
        return False


# ─────────────────────────── Génération ffmpeg ───────────────────────────
def _petit_cote(chemin):
    try:
        out = subprocess.run(
            ['ffprobe', '-v', 'error', '-select_streams', 'v:0',
             '-show_entries', 'stream=width,height:stream_tags=rotate:stream_side_data=rotation',
             '-of', 'default=noprint_wrappers=1', chemin],
            capture_output=True, text=True, timeout=60).stdout
        w = h = None
        for ligne in out.splitlines():
            if ligne.startswith('width='):
                w = int(ligne.split('=')[1])
            elif ligne.startswith('height='):
                h = int(ligne.split('=')[1])
        return min(w, h) if w and h else None
    except Exception:
        return None


def _generer(app, pub_id, chemin_source, q):
    cle = (pub_id, q)
    with app.app_context():
        sortie = _chemin_variante(pub_id, q)
        verrou = sortie + '.lock'
        tmp = sortie[:-4] + '.tmp.mp4'
        verrou_pris = False
        try:
            # verrou inter-processus (plusieurs workers gunicorn)
            try:
                if os.path.exists(verrou) and time.time() - os.path.getmtime(verrou) > LOCK_PERIME_APRES:
                    os.remove(verrou)
                fd = os.open(verrou, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                verrou_pris = True
            except FileExistsError:
                return

            if _variante_a_jour(pub_id, q, chemin_source) or _identique_a_jour(pub_id, q, chemin_source):
                return

            cfg = QUALITES[q]
            pc = _petit_cote(chemin_source)
            if pc is not None and pc <= cfg['court_cote']:
                open(_marqueur_identique(pub_id, q), 'w').close()
                return

            h = cfg['court_cote']
            # le petit côté devient h, l'autre est calculé (pair), jamais d'agrandissement
            vf = f"scale='if(gt(iw,ih),-2,min({h},iw))':'if(gt(iw,ih),min({h},ih),-2)'"
            cmd = [
                'ffmpeg', '-y', '-nostdin', '-loglevel', 'error', '-i', chemin_source,
                '-vf', vf, '-c:v', 'libx264', '-preset', 'veryfast', '-crf', str(cfg['crf']),
                '-maxrate', cfg['maxrate'], '-bufsize', str(int(cfg['maxrate'][:-1]) * 2) + 'k',
                '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', cfg['audio'],
                '-movflags', '+faststart', tmp,
            ]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=FFMPEG_TIMEOUT)
            if r.returncode != 0 or not os.path.isfile(tmp) or os.path.getsize(tmp) == 0:
                current_app.logger.warning('ffmpeg %s/%s a échoué : %s', pub_id, q, (r.stderr or '')[-400:])
                return
            os.replace(tmp, sortie)          # écriture atomique : jamais de fichier à moitié écrit servi
        except Exception as e:                # noqa
            current_app.logger.warning('Génération %s/%s impossible : %s', pub_id, q, e)
        finally:
            if verrou_pris:
                for f in (tmp, verrou):
                    try:
                        os.remove(f)
                    except OSError:
                        pass
            with _en_cours_lock:
                _en_cours.discard(cle)


def _planifier(pub_id, chemin_source, q):
    if q not in QUALITES:
        return
    if _variante_a_jour(pub_id, q, chemin_source) or _identique_a_jour(pub_id, q, chemin_source):
        return
    cle = (pub_id, q)
    with _en_cours_lock:
        if cle in _en_cours:
            return
        _en_cours.add(cle)
    app = current_app._get_current_object()
    _pool.submit(_generer, app, pub_id, chemin_source, q)


def planifier_variantes(pub, qualites=('360', '480', '720')):
    """À appeler après l'enregistrement d'une publication vidéo. Ne bloque pas la requête."""
    chemin = _chemin_original(pub)
    if not chemin:
        return
    for q in qualites:
        _planifier(pub.id, chemin, q)


def supprimer_variantes(pub_id):
    """À appeler à la suppression DÉFINITIVE d'une vidéo (pas pour la corbeille : elle peut être restaurée)."""
    d = _dossier_variantes()
    for q in QUALITES:
        for f in (_chemin_variante(pub_id, q), _marqueur_identique(pub_id, q)):
            try:
                os.remove(f)
            except OSError:
                pass


# ─────────────────────────── Routes ───────────────────────────
def _qualite_demandee():
    q = (request.args.get('q') or 'original').strip().lower()
    return q if (q in QUALITES or q == 'original') else 'original'


@main.route('/api/reel/<int:pub_id>/video')
@login_required
def api_reel_video(pub_id):
    """Sert la vidéo dans la qualité demandée (q=360|480|720|original). Si la version allégée n'est
    pas encore prête, sert l'original et lance sa préparation. Gère les requêtes Range (lecture/seek)."""
    pub = Publication.query.get_or_404(pub_id)
    if not _peut_voir(pub):
        abort(403)
    original = _chemin_original(pub)
    if not original:
        abort(404)

    q = _qualite_demandee()
    fichier, servi = original, 'original'
    if q in QUALITES:
        if _variante_a_jour(pub_id, q, original):
            fichier, servi = _chemin_variante(pub_id, q), q
        else:
            if not _identique_a_jour(pub_id, q, original):
                _planifier(pub_id, original, q)

    rep = send_file(fichier, mimetype='video/mp4' if fichier.endswith('.mp4') else None,
                    conditional=True, max_age=0)
    rep.headers['X-Qualite-Servie'] = servi
    # la version servie peut changer (original → allégée) : le navigateur doit revalider
    rep.headers['Cache-Control'] = 'private, no-cache' if servi == 'original' and q in QUALITES else 'private, max-age=86400'
    rep.headers['Vary'] = 'Cookie'
    return rep


@main.route('/api/reel/<int:pub_id>/qualites')
@login_required
def api_reel_qualites(pub_id):
    pub = Publication.query.get_or_404(pub_id)
    if not _peut_voir(pub):
        abort(403)
    original = _chemin_original(pub)
    if not original:
        return jsonify(success=True, qualites=[], original=False)
    etat = []
    for q in QUALITES:
        if _variante_a_jour(pub_id, q, original):
            etat.append({'id': q, 'etat': 'pret', 'octets': os.path.getsize(_chemin_variante(pub_id, q))})
        elif _identique_a_jour(pub_id, q, original):
            etat.append({'id': q, 'etat': 'identique'})       # la source est déjà plus petite
        else:
            with _en_cours_lock:
                etat.append({'id': q, 'etat': 'en_preparation' if (pub_id, q) in _en_cours else 'absent'})
    return jsonify(success=True, original=True, octets_original=os.path.getsize(original), qualites=etat)


# ─────────────────────────── Commande de rattrapage ───────────────────────────
@main.cli.command('generer-variantes')
def cmd_generer_variantes():
    """flask main generer-variantes  (ou flask generer-variantes selon l'enregistrement du blueprint)
    Génère les versions allégées de toutes les vidéos déjà publiées, une par une."""
    total = 0
    for pub in Publication.query.filter(Publication.media_url.isnot(None)).all():
        chemin = _chemin_original(pub)
        if not chemin:
            continue
        for q in QUALITES:
            if not (_variante_a_jour(pub.id, q, chemin) or _identique_a_jour(pub.id, q, chemin)):
                _generer(current_app._get_current_object(), pub.id, chemin, q)
                total += 1
    print(f'{total} version(s) traitée(s).')