# ==========================================================================
# AJOUT ADDITIF — route /api/preferences (appelée par settings.html)
# À COLLER TOUT À LA FIN de routes.py (après fn_enforcer_js). Rien d'existant n'est modifié.
# Utilise _fn_api, _fn_uid, _fn_ok, _fn_err, _fn_ip déjà définis plus haut dans routes.py.
# settings.html l'appelle seulement si FN_PREFS_SYNC = true (actuellement false).
# ==========================================================================

class FnDisplayPrefs(db.Model):
    __tablename__ = 'fn_display_prefs'
    user_id = db.Column(db.Integer, primary_key=True)
    theme = db.Column(db.String(10), nullable=True)
    langue = db.Column(db.String(12), nullable=True)
    fontsize = db.Column(db.String(10), nullable=True)
    motion = db.Column(db.String(10), nullable=True)
    contrast = db.Column(db.String(10), nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)


_fn_display_table_ok = False


def _fn_assurer_table_display():
    global _fn_display_table_ok
    if _fn_display_table_ok:
        return
    try:
        FnDisplayPrefs.__table__.create(bind=db.engine, checkfirst=True)
        _fn_display_table_ok = True
    except Exception as e:
        print(f"DEBUG: création table fn_display_prefs impossible : {e}")


_FN_DISPLAY_CHOICES = {
    'theme': ('light', 'dark', 'system'),
    'fontsize': ('standard', 'large', 'xl'),
    'motion': ('normal', 'reduce'),
    'contrast': ('normal', 'high'),
}
_FN_LANG_RE = re.compile(r'^[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})?$')


def _fn_display_dict(row):
    return {
        'theme': (row.theme if row else None) or 'system',
        'langue': (row.langue if row else None) or 'fr',
        'fontsize': (row.fontsize if row else None) or 'standard',
        'motion': (row.motion if row else None) or 'normal',
        'contrast': (row.contrast if row else None) or 'normal',
    }


@main_bp.route('/api/preferences', methods=['GET', 'POST'])
@_fn_api(csrf=False)
def api_preferences_affichage():
    """GET : renvoie les préférences d'affichage. POST : met à jour (champs partiels acceptés)."""
    _fn_assurer_table_display()
    uid = _fn_uid()
    row = db.session.get(FnDisplayPrefs, uid)

    if request.method == 'GET':
        return _fn_ok(prefs=_fn_display_dict(row))

    # Protection CSRF légère : si le navigateur envoie Origin, il doit être celui du site.
    origin = request.headers.get('Origin')
    if origin and urlparse(origin).netloc != request.host:
        return _fn_err('Origine non autorisée.', 403)

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _fn_err('Données invalides.', 400)

    updates = {}
    for champ, valides in _FN_DISPLAY_CHOICES.items():
        if champ in data:
            if data[champ] not in valides:
                return _fn_err(f'Valeur invalide pour « {champ} ».', 400)
            updates[champ] = data[champ]
    if 'langue' in data:
        if not isinstance(data['langue'], str) or not _FN_LANG_RE.match(data['langue']):
            return _fn_err('Langue invalide.', 400)
        updates['langue'] = data['langue']
    if not updates:
        return _fn_err('Aucune préférence à enregistrer.', 400)

    if row is None:
        row = FnDisplayPrefs(user_id=uid)
        db.session.add(row)
    for k, v in updates.items():
        setattr(row, k, v)
    row.updated_at = datetime.utcnow()
    db.session.commit()
    return _fn_ok(prefs=_fn_display_dict(row))
