# ══════════════════════════════════════════════════════════════════════
# AJOUT ADDITIF : Transparence du profil (autres noms, prononciation,
# mentions légales, date de dernière mise à jour).
# À COLLER À LA FIN de routes.py (après toutes les autres routes).
# ══════════════════════════════════════════════════════════════════════
from models import AutreNom, ProfilTransparence, TYPES_AUTRE_NOM

_TYPES_AUTRE_NOM_DICT = dict(TYPES_AUTRE_NOM)
_AUTRES_NOMS_MAX = 10

_tables_transparence_ok = False
def _assurer_tables_transparence():
    global _tables_transparence_ok
    if _tables_transparence_ok:
        return
    try:
        AutreNom.__table__.create(bind=db.engine, checkfirst=True)
        ProfilTransparence.__table__.create(bind=db.engine, checkfirst=True)
        _tables_transparence_ok = True
    except Exception as e:
        print(f"DEBUG: création tables transparence impossible : {e}")


def _toucher_profil(user_id):
    """Enregistre « profil mis à jour maintenant ». Ne lève jamais d'exception."""
    try:
        _assurer_tables_transparence()
        ligne = db.session.get(ProfilTransparence, user_id)
        if ligne is None:
            ligne = ProfilTransparence(user_id=user_id)
            db.session.add(ligne)
        ligne.mis_a_jour_le = datetime.utcnow()
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"DEBUG: horodatage du profil impossible : {e}")


def _il_y_a(dt):
    """'il y a 4 jours', 'il y a 2 heures', 'à l'instant'..."""
    if not dt:
        return ''
    s = (datetime.utcnow() - dt).total_seconds()
    if s < 60:
        return "à l'instant"
    for secondes, un, plusieurs in ((31536000, 'an', 'ans'), (2592000, 'mois', 'mois'),
                                    (86400, 'jour', 'jours'), (3600, 'heure', 'heures'),
                                    (60, 'minute', 'minutes')):
        n = int(s // secondes)
        if n >= 1:
            return f"il y a {n} {un if n == 1 else plusieurs}"
    return "à l'instant"


_MOIS_FR = ['janvier', 'février', 'mars', 'avril', 'mai', 'juin', 'juillet',
            'août', 'septembre', 'octobre', 'novembre', 'décembre']

def _date_fr(dt, avec_jour=True):
    if not dt:
        return ''
    return (f"{dt.day} " if avec_jour else '') + f"{_MOIS_FR[dt.month - 1]} {dt.year}"


def _donnees_transparence(user):
    """Dictionnaire prêt pour profile.html (modals « infos du profil »,
    « Transparence du profil » et « Autres noms »)."""
    d = {'autres_noms': [], 'prononciation': '', 'mentions_legales': '',
         'inscription': _date_fr(getattr(user, 'created_at', None), avec_jour=False),
         'profil_cree': _date_fr(getattr(user, 'created_at', None)),
         'maj_il_y_a': '', 'abonnement': None, 'verification_date': '',
         'changements_nom': int(getattr(user, 'name_change_count', 0) or 0),
         'dernier_changement_nom': _date_fr(getattr(user, 'last_name_change', None))}
    try:
        _assurer_tables_transparence()
        d['autres_noms'] = [{'id': n.id, 'type': n.type_nom,
                             'type_label': _TYPES_AUTRE_NOM_DICT.get(n.type_nom, 'Autre nom'),
                             'nom': n.nom}
                            for n in AutreNom.query.filter_by(user_id=user.id).order_by(AutreNom.id).all()]
        t = db.session.get(ProfilTransparence, user.id)
        if t is not None:
            d['prononciation'] = t.prononciation or ''
            d['mentions_legales'] = t.mentions_legales or ''
            d['maj_il_y_a'] = _il_y_a(t.mis_a_jour_le)
    except Exception as e:
        db.session.rollback()
        print(f"DEBUG: lecture transparence impossible : {e}")
    if not d['maj_il_y_a']:
        d['maj_il_y_a'] = _il_y_a(getattr(user, 'created_at', None))
    exp = getattr(user, 'badge_expire', None)
    if exp:
        d['abonnement'] = {'forfait': (getattr(user, 'forfait_type', None) or 'Tsapi Verified'),
                           'expire_le': _date_fr(exp), 'actif': exp > datetime.utcnow()}
    pid = getattr(user, 'piece_identite_date', None)
    if pid:
        d['verification_date'] = _date_fr(pid)
    return d


@main_bp.route('/api/autres-noms', methods=['POST'])
@login_required
def api_autres_noms_ajouter():
    data = request.get_json(silent=True) or request.form
    type_nom = (data.get('type') or '').strip()
    nom = re.sub(r'\s+', ' ', (data.get('nom') or '')).strip()
    if type_nom not in _TYPES_AUTRE_NOM_DICT:
        return jsonify(success=False, error="Choisissez un type de nom."), 400
    if len(nom) < 2 or len(nom) > 80:
        return jsonify(success=False, error="Le nom doit contenir entre 2 et 80 caractères."), 400
    if re.search(r'[<>@/\\{}\[\]|]|https?:|www\.', nom, re.I):
        return jsonify(success=False, error="Ce nom contient des caractères non autorisés."), 400
    _assurer_tables_transparence()
    try:
        # Même protection que pour le nom principal : pas d'usurpation d'une personnalité certifiée.
        if compte_certifie_possedant_nom(username=None, noms_affiches=(nom,), exclure_user_id=current_user.id):
            return jsonify(success=False, error=MSG_NOM_CERTIFIE), 400
        existants = AutreNom.query.filter_by(user_id=current_user.id).all()
        if len(existants) >= _AUTRES_NOMS_MAX:
            return jsonify(success=False, error=f"Vous pouvez enregistrer {_AUTRES_NOMS_MAX} autres noms au maximum."), 400
        if any(e.nom.lower() == nom.lower() for e in existants):
            return jsonify(success=False, error="Ce nom est déjà enregistré."), 400
        db.session.add(AutreNom(user_id=current_user.id, type_nom=type_nom, nom=nom))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"DEBUG: ajout autre nom impossible : {e}")
        return jsonify(success=False, error="Enregistrement impossible, veuillez réessayer."), 500
    _toucher_profil(current_user.id)
    return jsonify(success=True, autres_noms=_donnees_transparence(current_user)['autres_noms'])


@main_bp.route('/api/autres-noms/<int:nom_id>/supprimer', methods=['POST'])
@login_required
def api_autres_noms_supprimer(nom_id):
    _assurer_tables_transparence()
    try:
        n = AutreNom.query.filter_by(id=nom_id, user_id=current_user.id).first()
        if n is None:
            return jsonify(success=False, error="Nom introuvable."), 404
        db.session.delete(n)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"DEBUG: suppression autre nom impossible : {e}")
        return jsonify(success=False, error="Suppression impossible, veuillez réessayer."), 500
    _toucher_profil(current_user.id)
    return jsonify(success=True, autres_noms=_donnees_transparence(current_user)['autres_noms'])


@main_bp.route('/api/profil/prononciation', methods=['POST'])
@login_required
def api_profil_prononciation():
    data = request.get_json(silent=True) or request.form
    texte = re.sub(r'\s+', ' ', (data.get('prononciation') or '')).strip()
    if len(texte) > 150:
        return jsonify(success=False, error="150 caractères au maximum."), 400
    _assurer_tables_transparence()
    try:
        t = db.session.get(ProfilTransparence, current_user.id)
        if t is None:
            t = ProfilTransparence(user_id=current_user.id)
            db.session.add(t)
        t.prononciation = texte or None
        t.mis_a_jour_le = datetime.utcnow()
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"DEBUG: enregistrement prononciation impossible : {e}")
        return jsonify(success=False, error="Enregistrement impossible, veuillez réessayer."), 500
    return jsonify(success=True, prononciation=texte)


@main_bp.route('/api/profil/mentions-legales', methods=['POST'])
@login_required
def api_profil_mentions_legales():
    data = request.get_json(silent=True) or request.form
    texte = (data.get('mentions_legales') or '').strip()
    if len(texte) > 1000:
        return jsonify(success=False, error="1000 caractères au maximum."), 400
    _assurer_tables_transparence()
    try:
        t = db.session.get(ProfilTransparence, current_user.id)
        if t is None:
            t = ProfilTransparence(user_id=current_user.id)
            db.session.add(t)
        t.mentions_legales = texte or None
        t.mis_a_jour_le = datetime.utcnow()
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"DEBUG: enregistrement mentions légales impossible : {e}")
        return jsonify(success=False, error="Enregistrement impossible, veuillez réessayer."), 500
    return jsonify(success=True, mentions_legales=texte)


# ──────────────────────────────────────────────────────────────────────
# Voix ElevenLabs pour « Prononciation du nom » (mp3 mis en cache sur disque).
# Réutilise `client_eleven` déjà défini plus haut dans routes.py.
# ──────────────────────────────────────────────────────────────────────
import hashlib as _pn_hashlib
from flask import send_file as _pn_send_file

_VOIX_NOMS_ID = "21m00Tcm4TlvDq8ikWAM"   # Rachel — remplace par une autre voix ElevenLabs si tu préfères

def _dossier_voix_noms():
    d = os.path.join('static', 'audio', 'noms')
    os.makedirs(d, exist_ok=True)
    return d


def _generer_voix_nom(texte, chemin):
    """Génère un mp3 ElevenLabs lent et clair pour un nom. True si réussi."""
    try:
        try:
            audio = client_eleven.text_to_speech.convert(
                voice_id=_VOIX_NOMS_ID,
                text=texte,
                model_id="eleven_multilingual_v2",
                output_format="mp3_44100_128",
                voice_settings={"stability": 0.75, "similarity_boost": 0.8, "style": 0.0, "speed": 0.85},
            )
        except TypeError:
            # SDK sans l'option voice_settings : appel simple
            audio = client_eleven.text_to_speech.convert(
                voice_id=_VOIX_NOMS_ID, text=texte,
                model_id="eleven_multilingual_v2", output_format="mp3_44100_128")
        with open(chemin, 'wb') as f:
            if isinstance(audio, (bytes, bytearray)):
                f.write(audio)
            else:
                for chunk in audio:
                    if chunk:
                        f.write(chunk)
        if os.path.getsize(chemin) == 0:
            os.remove(chemin)
            return False
        return True
    except Exception as e:
        print(f"DEBUG: voix ElevenLabs (prononciation) impossible : {e}")
        try:
            if os.path.exists(chemin):
                os.remove(chemin)
        except OSError:
            pass
        return False


@main_bp.route('/api/prononciation-audio')
@login_required
def api_prononciation_audio():
    """?user_id=<id> : lit la prononciation enregistrée (sinon le nom complet).
       ?texte=<...>  : aperçu d'un texte saisi (150 caractères max)."""
    texte = re.sub(r'\s+', ' ', (request.args.get('texte') or '')).strip()
    if not texte:
        uid = request.args.get('user_id', type=int)
        cible = db.session.get(User, uid) if uid else None
        if cible is None:
            return jsonify(success=False, error="Profil introuvable."), 404
        _assurer_tables_transparence()
        try:
            t = db.session.get(ProfilTransparence, cible.id)
        except Exception:
            db.session.rollback()
            t = None
        texte = ((t.prononciation if t else '') or cible.nom_complet or cible.username or '').strip()
    if not texte:
        return jsonify(success=False, error="Aucun nom à prononcer."), 400
    if len(texte) > 150:
        return jsonify(success=False, error="150 caractères au maximum."), 400
    cle = _pn_hashlib.sha1(texte.lower().encode('utf-8')).hexdigest()[:24]
    chemin = os.path.join(_dossier_voix_noms(), f"{cle}.mp3")
    if not os.path.exists(chemin):
        if not _generer_voix_nom(texte, chemin):
            return jsonify(success=False, error="La voix n'est pas disponible pour le moment."), 503
    rep = _pn_send_file(os.path.abspath(chemin), mimetype='audio/mpeg')
    rep.headers['Cache-Control'] = 'private, max-age=86400'
    return rep