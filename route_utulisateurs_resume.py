# ─────────────────────────────────────────────────────────────────────────
# À COLLER dans ton fichier de routes (celui qui contient « main = Blueprint(...) »),
# sans modifier aucune autre route. Elle sert uniquement à afficher les NOMS des
# personnes identifiées sur le fil (« avec Marie et 2 autres » + liste complète).
#
# À adapter si besoin :
#   - « main »  : le nom de ton Blueprint dans ce fichier
#   - l'import de User : « from models import User » ou « from .models import User »
# ─────────────────────────────────────────────────────────────────────────
@main.route('/api/utilisateurs/resume')
def api_utilisateurs_resume():
    from flask import request, jsonify, url_for
    from flask_login import current_user
    try:
        from models import User
    except ImportError:
        from .models import User

    if not current_user.is_authenticated:
        return jsonify({'success': False, 'utilisateurs': []}), 401

    ids = []
    for part in (request.args.get('ids') or '').split(','):
        part = part.strip()
        if part.isdigit():
            ids.append(int(part))
    ids = ids[:60]
    if not ids:
        return jsonify({'success': True, 'utilisateurs': []})

    par_id = {u.id: u for u in User.query.filter(User.id.in_(ids)).all()}
    resultat = []
    for i in ids:
        u = par_id.get(i)
        if u is None:
            continue
        resultat.append({
            'id': u.id,
            'nom_complet': u.nom_complet,
            'username': u.username,
            'avatar': u.avatar or 'default_avatar.png',
            'profil_url': url_for('main.profile', username=u.username),
        })
    return jsonify({'success': True, 'utilisateurs': resultat})