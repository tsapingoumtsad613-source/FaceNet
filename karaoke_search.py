"""
Recherche de chansons karaoké (instrumentales complètes) pour FaceNet.

Route fournie : GET /karaoke/api/search?q=...&limit=30&page=1

Enregistrement dans ton app Flask :

    from karaoke_search import karaoke_search_bp
    app.register_blueprint(karaoke_search_bp, url_prefix='/karaoke')

Catalogue : un fichier JSON (instance/karaoke_catalogue.json) que TU remplis avec
des pistes dont tu as les droits. Voir karaoke_catalogue.exemple.json.
"""
import json
import os
import re
import subprocess
import unicodedata

from flask import Blueprint, current_app, jsonify, request

karaoke_search_bp = Blueprint('karaoke_search', __name__)

TOLERANCE_DUREE = 0.97      # la piste doit durer au moins 97 % de la durée annoncée
LIMITE_MAX = 50

_cache_catalogue = {'mtime': None, 'data': []}
_cache_duree = {}           # (chemin, mtime) -> durée réelle en secondes
_cache_lrc = {}             # (chemin, mtime) -> lignes de paroles


# ----------------------------------------------------------------------------
# Utilitaires
# ----------------------------------------------------------------------------
def _normaliser(texte):
    texte = unicodedata.normalize('NFD', str(texte or ''))
    texte = ''.join(c for c in texte if unicodedata.category(c) != 'Mn')
    return re.sub(r'\s+', ' ', texte.lower()).strip()


def _chemin_catalogue():
    return current_app.config.get(
        'KARAOKE_CATALOGUE_PATH',
        os.path.join(current_app.instance_path, 'karaoke_catalogue.json'))


def _charger_catalogue():
    chemin = _chemin_catalogue()
    try:
        mtime = os.path.getmtime(chemin)
    except OSError:
        return []
    if _cache_catalogue['mtime'] != mtime:
        try:
            with open(chemin, 'r', encoding='utf-8') as f:
                data = json.load(f)
            _cache_catalogue['data'] = data if isinstance(data, list) else []
        except (OSError, ValueError):
            current_app.logger.exception('Catalogue karaoké illisible')
            _cache_catalogue['data'] = []
        _cache_catalogue['mtime'] = mtime
    return _cache_catalogue['data']


def _chemin_local(url):
    """Transforme /static/... en chemin disque. Retourne None pour une URL distante."""
    if not url or not url.startswith('/static/'):
        return None
    base = os.path.realpath(current_app.static_folder)
    chemin = os.path.realpath(os.path.join(base, url[len('/static/'):]))
    if not chemin.startswith(base + os.sep):    # protection contre ../
        return None
    return chemin if os.path.isfile(chemin) else None


def _duree_reelle(chemin):
    """Durée réelle du fichier via ffprobe (None si indisponible)."""
    try:
        cle = (chemin, os.path.getmtime(chemin))
    except OSError:
        return None
    if cle in _cache_duree:
        return _cache_duree[cle]
    duree = None
    try:
        sortie = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', chemin],
            capture_output=True, text=True, timeout=15, check=True).stdout.strip()
        duree = float(sortie)
    except (OSError, ValueError, subprocess.SubprocessError):
        duree = None
    _cache_duree[cle] = duree
    return duree


def _lire_lrc(url):
    """Paroles synchronisées (fichier .lrc que tu fournis toi-même)."""
    chemin = _chemin_local(url)
    if not chemin:
        return []
    cle = (chemin, os.path.getmtime(chemin))
    if cle in _cache_lrc:
        return _cache_lrc[cle]
    lignes = []
    motif = re.compile(r'\[(\d+):(\d+(?:\.\d+)?)\](.*)')
    try:
        with open(chemin, 'r', encoding='utf-8') as f:
            for brut in f:
                m = motif.match(brut.strip())
                if m and m.group(3).strip():
                    lignes.append({'t': int(m.group(1)) * 60 + float(m.group(2)),
                                   'text': m.group(3).strip()})
    except OSError:
        lignes = []
    lignes.sort(key=lambda l: l['t'])
    _cache_lrc[cle] = lignes
    return lignes


def _verifier_complete(entree):
    """
    Une chanson est « complète » si :
      - elle est marquée sans voix (vocals_removed != False),
      - sa durée annoncée est connue,
      - et, quand le fichier est local, sa vraie durée atteint 97 % de la durée annoncée.
    """
    if entree.get('vocals_removed') is False or entree.get('published') is False:
        return False, 0
    annoncee = float(entree.get('duration') or 0)
    if annoncee <= 0:
        return False, 0
    chemin = _chemin_local(entree.get('instrumental_url', ''))
    if chemin:
        reelle = _duree_reelle(chemin)
        if reelle is None:                       # ffprobe absent : on s'en tient au catalogue
            return True, annoncee
        if reelle < annoncee * TOLERANCE_DUREE:
            return False, reelle
        return True, reelle
    return True, annoncee                        # URL distante : non vérifiable ici


# ----------------------------------------------------------------------------
# Route
# ----------------------------------------------------------------------------
@karaoke_search_bp.route('/api/search', methods=['GET'])
def api_search():
    q = _normaliser(request.args.get('q', ''))
    try:
        limit = max(1, min(LIMITE_MAX, int(request.args.get('limit', 30))))
        page = max(1, int(request.args.get('page', 1)))
    except ValueError:
        return jsonify(ok=False, error='Paramètres invalides'), 400

    mots = q.split()
    trouves = []
    for e in _charger_catalogue():
        if not isinstance(e, dict) or not e.get('instrumental_url') or not e.get('title'):
            continue
        meule = _normaliser(e.get('title', '') + ' ' + e.get('artist', ''))
        if all(m in meule for m in mots):
            trouves.append(e)

    trouves.sort(key=lambda e: _normaliser(e.get('title', '')))
    total = len(trouves)
    debut = (page - 1) * limit

    resultats = []
    for e in trouves[debut:debut + limit]:
        complete, duree = _verifier_complete(e)
        if not complete:
            continue                              # on n'expose jamais une piste incomplète
        resultats.append({
            'id': e.get('id') or _normaliser(e['title']).replace(' ', '-'),
            'title': e['title'],
            'artist': e.get('artist', ''),
            'duration': round(duree, 2),
            'cover': e.get('cover', ''),
            'instrumental_url': e['instrumental_url'],
            'complete': True,
            'vocals_removed': True,
            'lyrics': _lire_lrc(e['lyrics_url']) if e.get('lyrics_url') else [],
        })

    return jsonify(ok=True, results=resultats, total=total, page=page, limit=limit)
