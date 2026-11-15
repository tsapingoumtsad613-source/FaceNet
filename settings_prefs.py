"""
Route OPTIONNELLE : mémorise les préférences d'affichage côté serveur (dans la session Flask).
Aucun modèle / aucune migration nécessaire. Le fichier settings.html fonctionne sans elle.

Activation :
  1) Dans ton app :
        from settings_prefs import prefs_bp
        app.register_blueprint(prefs_bp)
  2) Dans settings.html, remplace  FN_PREFS_SYNC = false  par  FN_PREFS_SYNC = true

Si tu utilises Flask-WTF (CSRFProtect), la page envoie déjà l'en-tête X-CSRFToken
si tu as <meta name="csrf-token" content="{{ csrf_token() }}"> dans base.html.
"""
import re
from flask import Blueprint, jsonify, request, session

prefs_bp = Blueprint("prefs", __name__)

_ALLOWED = {
    "theme": {"light", "dark", "system"},
    "fontsize": {"standard", "large", "xl"},
    "motion": {"normal", "reduce"},
    "contrast": {"normal", "high"},
}
_LANG_RE = re.compile(r"^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})?$")
_DEFAULTS = {
    "theme": "system",
    "fontsize": "standard",
    "motion": "normal",
    "contrast": "normal",
    "langue": "fr",
}


def _current():
    prefs = dict(_DEFAULTS)
    prefs.update(session.get("display_prefs", {}))
    return prefs


@prefs_bp.route("/api/preferences", methods=["GET"])
def get_preferences():
    return jsonify(_current())


@prefs_bp.route("/api/preferences", methods=["POST"])
def save_preferences():
    data = request.get_json(silent=True) or {}
    prefs = _current()

    for key, allowed in _ALLOWED.items():
        if data.get(key) in allowed:
            prefs[key] = data[key]

    langue = data.get("langue")
    if isinstance(langue, str) and _LANG_RE.match(langue):
        prefs["langue"] = langue

    session["display_prefs"] = prefs
    session.modified = True
    return jsonify({"ok": True, "preferences": prefs})