# ══════════════════════════════════════════════════════════════════════════
# AJOUTS POUR reel.html — à intégrer dans TES fichiers existants.
# Ce fichier n'est PAS destiné à être importé tel quel : c'est un
# récapitulatif organisé de ce qu'il faut copier/coller (et où),
# écrit avec le même style que ton routes.py actuel.
# ══════════════════════════════════════════════════════════════════════════


# ─────────────────────────────────────────────────────────────────────────
# 1) MODELS.PY — à ajouter (je n'ai pas ce fichier, donc à adapter si tes
#    noms de colonnes/tables diffèrent). Deux changements :
#
#    a) Sur le modèle Commentaire existant, ajoute :
#         parent_id = db.Column(db.Integer, db.ForeignKey('commentaire.id'), nullable=True)
#         reponses  = db.relationship('Commentaire',
#                         backref=db.backref('parent', remote_side='Commentaire.id'),
#                         cascade='all, delete-orphan')
#         likes     = db.relationship('CommentaireLike', backref='commentaire',
#                         cascade='all, delete-orphan')
#
#       (remplace 'commentaire.id' par le vrai nom de table si ta classe
#        Commentaire ne mappe pas sur une table appelée "commentaire")
#
#    b) Nouveau modèle, à ajouter n'importe où dans models.py :
#
#         class CommentaireLike(db.Model):
#             __tablename__ = 'commentaire_like'
#             id = db.Column(db.Integer, primary_key=True)
#             commentaire_id = db.Column(db.Integer, db.ForeignKey('commentaire.id'), nullable=False)
#             user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
#             date_creation = db.Column(db.DateTime, default=datetime.utcnow)
#
#    Puis migration (Flask-Migrate) :
#         flask db migrate -m "ajout parent_id commentaire + table commentaire_like"
#         flask db upgrade
#
#    Une fois ça fait, reel.html n'a RIEN de plus à changer : le template
#    que je t'ai livré lit déjà comm.likes / comm.reponses automatiquement
#    dès qu'ils existent sur le modèle (sinon il retombe sur des valeurs
#    par défaut, donc rien ne casse en attendant la migration).
# ─────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────
# 2) ROUTES.PY — en haut du fichier, ajoute cet import (utilisé pour la
#    mise en cache du fichier vidéo envoyé à Gemini) :
#
#         import time
#
#    (json et re sont déjà importés chez toi, pas besoin d'y toucher)
# ─────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────
# 3) ROUTES.PY — remplace ta route existante api_add_comment (ligne ~1949)
#    par CETTE version, qui accepte en plus un parent_id optionnel pour
#    créer une réponse à un commentaire :
# ─────────────────────────────────────────────────────────────────────────

@main_bp.route('/api/comment/<int:pub_id>', methods=['POST'])
@login_required
def api_add_comment(pub_id):
    pub = Publication.query.get_or_404(pub_id)
    if not _peut_voir_publication(pub, current_user.id):
        return jsonify(success=False, error="Cette publication n'est pas accessible."), 403
    data = request.get_json(silent=True) or {}
    contenu = (data.get('contenu') or '').strip()
    parent_id = data.get('parent_id')
    if not contenu:
        return jsonify(success=False, error='Commentaire vide.'), 400
    if len(contenu) > 5000:
        return jsonify(success=False, error='Commentaire trop long.'), 400
    parent = None
    if parent_id:
        parent = Commentaire.query.filter_by(id=parent_id, publication_id=pub_id).first()
        if not parent:
            return jsonify(success=False, error='Commentaire parent introuvable.'), 404
    commentaire = Commentaire(contenu=contenu, user_id=current_user.id, publication_id=pub_id,
                               parent_id=parent.id if parent else None)
    db.session.add(commentaire); db.session.commit()
    total = Commentaire.query.filter_by(publication_id=pub_id).count()
    return jsonify(success=True, id=commentaire.id, author=current_user.nom_complet,
                   avatar=current_user.avatar or 'default_avatar.png',
                   contenu=contenu, comments_count=total,
                   parent_id=parent.id if parent else None)


# ─────────────────────────────────────────────────────────────────────────
# 4) ROUTES.PY — nouvelle route : "J'aime" sur un commentaire ou une
#    réponse (ajoute-la n'importe où après la définition de Commentaire,
#    par exemple juste après api_report_comment) :
# ─────────────────────────────────────────────────────────────────────────

@main_bp.route('/api/comment/<int:comment_id>/like', methods=['POST'])
@login_required
def api_comment_like(comment_id):
    comment = Commentaire.query.get_or_404(comment_id)
    like = CommentaireLike.query.filter_by(commentaire_id=comment_id, user_id=current_user.id).first()
    if like:
        db.session.delete(like); liked = False
    else:
        db.session.add(CommentaireLike(commentaire_id=comment_id, user_id=current_user.id))
        liked = True
    db.session.commit()
    total = CommentaireLike.query.filter_by(commentaire_id=comment_id).count()
    return jsonify(success=True, liked=liked, total_likes=total)


# ─────────────────────────────────────────────────────────────────────────
# 5) ROUTES.PY — recherche dans la vidéo + question à l'IA (Tsapi AI),
#    branchées DIRECTEMENT sur ton client Gemini déjà configuré en haut
#    du fichier (la variable "client" que tu utilises déjà dans
#    tsapi_ai_api). Rien ne passe par /tsapi-ai ni par chat.html : c'est
#    le même assistant, appelé discrètement depuis la page des Reels,
#    la vidéo elle-même étant envoyée à Gemini pour qu'il "regarde" et
#    "écoute" le passage concerné (image + son), au lieu de se baser sur
#    une simple description textuelle.
#
#    Colle ce bloc n'importe où après la définition de "client" (ligne
#    ~202) et avant les routes qui l'utilisent — par exemple juste après
#    api_reel_enregistrer.
# ─────────────────────────────────────────────────────────────────────────

# Cache mémoire très simple : évite de ré-envoyer la même vidéo à Gemini
# à chaque recherche/question (le fichier reste valable côté Gemini
# pendant ~48h, on le garde ici 1h par prudence — ajuste si besoin).
_reel_ia_video_cache = {}
_REEL_IA_CACHE_DUREE = timedelta(hours=1)

def _get_reel_video_file_ia(pub):
    """Envoie (ou réutilise) la vidéo de la publication auprès de Gemini,
    pour qu'elle puisse être analysée (image + son). Renvoie l'objet
    fichier Gemini prêt à être passé dans 'contents', ou None si la
    vidéo est introuvable sur le disque."""
    cache = _reel_ia_video_cache.get(pub.id)
    if cache and (datetime.utcnow() - cache['uploaded_at']) < _REEL_IA_CACHE_DUREE:
        try:
            fichier = client.files.get(name=cache['file_name'])
            etat = str(getattr(fichier, 'state', '') or '')
            if 'ACTIVE' in etat or etat == '':
                return fichier
        except Exception:
            pass
        _reel_ia_video_cache.pop(pub.id, None)

    chemin = os.path.join(current_app.root_path, 'static', 'uploads', pub.media_url or '')
    if not pub.media_url or not os.path.exists(chemin):
        return None

    fichier = client.files.upload(file=chemin)
    tentatives = 0
    while str(getattr(fichier, 'state', '') or '') not in ('', 'ACTIVE', 'State.ACTIVE') and tentatives < 15:
        time.sleep(1)
        fichier = client.files.get(name=fichier.name)
        tentatives += 1

    _reel_ia_video_cache[pub.id] = {'file_name': fichier.name, 'uploaded_at': datetime.utcnow()}
    return fichier


def _extraire_json_ia(texte):
    """Gemini renvoie parfois le JSON entouré de ```json ... ``` : on nettoie
    avant de parser, et on retombe sur None si ce n'est vraiment pas du JSON."""
    texte = (texte or '').strip()
    texte = re.sub(r'^```(json)?|```$', '', texte, flags=re.MULTILINE).strip()
    try:
        return json.loads(texte)
    except Exception:
        return None


@main_bp.route('/api/reel/<int:pub_id>/rechercher', methods=['GET'])
@login_required
def api_reel_rechercher(pub_id):
    pub = Publication.query.get_or_404(pub_id)
    if not _peut_voir_publication(pub, current_user.id):
        return jsonify(success=False, error="Cette vidéo n'est pas accessible."), 403
    requete = (request.args.get('q') or '').strip()
    if not requete:
        return jsonify(success=True, resultats=[])
    try:
        fichier = _get_reel_video_file_ia(pub)
        if not fichier:
            return jsonify(success=False, error="Vidéo introuvable pour l'analyse."), 404
        prompt = f"""
Tu regardes cette video (image ET son) et tu dois retrouver les passages qui
correspondent a : "{requete}".
Reponds UNIQUEMENT avec un JSON valide, sans aucun texte autour, exactement
sous cette forme :
{{"resultats": [{{"timestamp": <secondes entieres depuis le debut de la video>, "texte": "<court extrait ou description du passage>"}}]}}
Maximum 5 resultats, du plus pertinent au moins pertinent.
Si rien ne correspond, reponds {{"resultats": []}}.
"""
        response = client.models.generate_content(
            model='gemini-3.5-flash-lite',
            contents=[fichier, prompt],
            config=types.GenerateContentConfig(temperature=0.2, max_output_tokens=512))
        data = _extraire_json_ia(response.text)
        resultats = (data or {}).get('resultats', [])[:5]
        return jsonify(success=True, resultats=resultats)
    except Exception as e:
        print(f"DEBUG: Erreur recherche video IA (pub {pub_id}) : {e}")
        return jsonify(success=False, error="Recherche momentanément indisponible."), 500


@main_bp.route('/api/reel/<int:pub_id>/question', methods=['POST'])
@login_required
def api_reel_question(pub_id):
    pub = Publication.query.get_or_404(pub_id)
    if not _peut_voir_publication(pub, current_user.id):
        return jsonify(success=False, error="Cette vidéo n'est pas accessible."), 403
    data = request.get_json(silent=True) or {}
    question = (data.get('question') or '').strip()
    if not question:
        return jsonify(success=False, error='Question vide.'), 400
    try:
        fichier = _get_reel_video_file_ia(pub)
        if not fichier:
            return jsonify(success=False, error="Vidéo introuvable pour l'analyse."), 404
        instructions = """
Tu es Tsapi AI, l'assistant de FaceNet. Tu regardes attentivement cette video
(image ET son) pour repondre precisement a la question de l'utilisateur : ce
qui est dit, les gestes effectues, un moment particulier...
Reponds UNIQUEMENT avec un JSON valide, sans aucun texte autour, exactement
sous cette forme :
{"reponse": "<reponse claire et concise, en francais>", "timestamp": <secondes entieres si tu identifies un moment precis, sinon null>}
"""
        response = client.models.generate_content(
            model='gemini-3.5-flash-lite',
            contents=[fichier, f"{instructions}\n\nQuestion : {question}"],
            config=types.GenerateContentConfig(temperature=0.4, max_output_tokens=512))
        resultat = _extraire_json_ia(response.text) or {}
        reponse_texte = resultat.get('reponse') or (response.text or '').strip() or \
            "Je n'ai pas trouvé de réponse précise pour cette vidéo."
        return jsonify(success=True, reponse=reponse_texte, timestamp=resultat.get('timestamp'))
    except Exception as e:
        print(f"DEBUG: Erreur question video IA (pub {pub_id}) : {e}")
        return jsonify(success=False, error="L'assistant est momentanément indisponible."), 500


# ─────────────────────────────────────────────────────────────────────────
# NOTES IMPORTANTES
#
# • "Discrètement" : ces deux routes ne passent jamais par /tsapi-ai ni par
#   chat.html. reel.html les appelle directement en fetch() depuis le
#   tiroir "Rechercher / Poser une question" que je t'ai déjà livré, et la
#   réponse s'affiche dans ce même tiroir — l'utilisateur ne quitte jamais
#   la page des Reels, et rien n'indique "chat IA" ailleurs sur le site.
#
# • Modèle utilisé : je garde 'gemini-3.5-flash-lite' comme dans ta route
#   /tsapi-ai existante pour rester cohérent. Si ce modèle ne gère pas bien
#   la vidéo chez toi (résultats vagues, erreurs), remplace-le simplement
#   par un modèle Gemini avec support vidéo confirmé sur ton compte — le
#   reste du code ne change pas.
#
# • Coût / latence : l'upload d'une vidéo vers Gemini prend quelques
#   secondes la première fois (d'où le cache d'1h). Sur des vidéos très
#   longues, envisage de limiter l'analyse aux 2-3 premières minutes pour
#   rester rapide.
#
# • Aucune route existante n'a été supprimée ou modifiée à part
#   api_add_comment (point 3), qui reste 100% rétrocompatible : un appel
#   sans parent_id continue de fonctionner exactement comme avant.
# ─────────────────────────────────────────────────────────────────────────