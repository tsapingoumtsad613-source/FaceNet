# ══════════════════════════════════════════════════════════════════════
#  AJOUT ADDITIF : VŒUX DE NOËL ET DU NOUVEL AN
#  À COLLER TOUT À LA FIN de routes.py (après la dernière route).
#  Aucune route, fonction, table ou colonne existante n'est modifiée :
#   • pas de nouvelle table, pas de migration (on réutilise Notification et Publication)
#   • la notification de minuit est créée au premier chargement de page après minuit
#     (heure de Douala), une seule fois par utilisateur et par fête : pas de planificateur à installer
#   • le clic mène à /voeux-fetes/<noel|nouvel_an> grâce au champ extra_data['lien']
#     (déjà géré par _resoudre_lien_notification, rien à y changer)
# ══════════════════════════════════════════════════════════════════════
FETES_VOEUX = {
    'noel': {
        'nom': 'Noël', 'emoji': '🎅',
        'titre': "Souhaitez un joyeux Noël à vos amis !",
        'systeme': ("Joyeux Noël à toute l'équipe FaceNet ! Que cette fête de Noël vous apporte paix, joie, "
                    "santé et bénédictions auprès de vos proches. Touchez ici pour souhaiter Joyeux Noël à vos amis."),
        'recu': "{nom} vous a souhaité un Joyeux Noël sur votre fil. Que cette belle fête vous apporte paix, joie et bonheur !",
    },
    'nouvel_an': {
        'nom': 'Nouvel An', 'emoji': '🎆',
        'titre': "Souhaitez une bonne année à vos amis !",
        'systeme': ("Bonne année {annee} à toute l'équipe FaceNet ! Que cette nouvelle année vous apporte santé, "
                    "bonheur et réussite dans tous vos projets. Touchez ici pour envoyer vos vœux à vos amis."),
        'recu': "{nom} vous a souhaité une Bonne Année {annee} sur votre fil. Que cette année soit remplie de bonheur et de réussite !",
    },
}


def _fete_du_jour():
    """('noel'|'nouvel_an', année) si on est dans la fenêtre de la fête (heure de Douala), sinon None."""
    n = datetime.now(pytz.timezone('Africa/Douala'))
    if n.month == 12 and n.day in (25, 26):
        return 'noel', n.year
    if n.month == 1 and n.day in (1, 2):
        return 'nouvel_an', n.year
    return None


@main_bp.before_app_request
def _fete_notifier_utilisateur():
    """Crée, une seule fois, la notification « Joyeux Noël / Bonne année » de FaceNet pour l'utilisateur connecté."""
    try:
        if request.endpoint in (None, 'static') or request.path.startswith('/static/'):
            return None
        uid = session.get('user_id')
        fete = _fete_du_jour() if uid else None
        if not fete:
            return None
        cle, annee = fete
        deja = [n for n in Notification.query.filter_by(recipient_id=uid, type='voeux_' + cle).all()
                if (n.extra_data or {}).get('annee') == annee]
        if deja:
            return None
        infos = FETES_VOEUX[cle]
        db.session.add(Notification(
            recipient_id=uid, actor_id=uid, verb='voeux_fetes', type='voeux_' + cle,
            target_type='fete', target_id=0,
            message=infos['systeme'].format(annee=annee),
            extra_data={'fete': cle, 'emoji': infos['emoji'], 'annee': annee,
                        'lien': url_for('main.voeux_fetes', fete_type=cle)}))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"DEBUG: notification de fête non créée : {e}")
    return None


@main_bp.route('/voeux-fetes/<fete_type>')
@login_required
def voeux_fetes(fete_type):
    infos = FETES_VOEUX.get(fete_type)
    if not infos:
        abort(404)
    return render_template('voeux_fetes.html', fete_type=fete_type, fete_nom=infos['nom'],
                           fete_emoji=infos['emoji'], fete_titre=infos['titre'],
                           ami_id=request.args.get('ami', type=int))


@main_bp.route('/api/voeux-fetes/publier', methods=['POST'])
@login_required
def api_voeux_fetes_publier():
    data = request.get_json(silent=True) or {}
    cle = data.get('type')
    infos = FETES_VOEUX.get(cle)
    if not infos:
        return jsonify(success=False, error="Fête inconnue."), 400
    try:
        dest_id = int(data.get('destinataire_id') or 0)
    except (TypeError, ValueError):
        dest_id = 0
    contenu = (data.get('contenu') or '').strip()
    if not contenu:
        return jsonify(success=False, error="Écrivez un message."), 400
    if len(contenu) > 1500:
        return jsonify(success=False, error="Message trop long (1500 caractères maximum)."), 400
    if dest_id == current_user.id or dest_id not in _amis_ids(current_user.id):
        return jsonify(success=False, error="Vous ne pouvez souhaiter ce message qu'à vos amis."), 403
    if BlockedUser.query.filter(or_(
            and_(BlockedUser.owner_id == current_user.id, BlockedUser.blocked_id == dest_id),
            and_(BlockedUser.owner_id == dest_id, BlockedUser.blocked_id == current_user.id))).first():
        return jsonify(success=False, error="Ce compte est bloqué ou vous a bloqué."), 403

    annee = datetime.now(pytz.timezone('Africa/Douala')).year
    deja = [n for n in Notification.query.filter_by(recipient_id=dest_id, actor_id=current_user.id,
                                                    type='voeux_recu_' + cle).all()
            if (n.extra_data or {}).get('annee') == annee]
    if deja:
        return jsonify(success=False, status='info',
                       error="Vous lui avez déjà souhaité ce message cette année."), 409
    try:
        pub = Publication(contenu=contenu, user_id=current_user.id, confidentialite='amis')
        if 'identifies' in Publication.__table__.columns:
            pub.identifies = str(dest_id)          # l'ami est identifié dans la publication
        db.session.add(pub)
        db.session.flush()
        nom = current_user.nom_complet or current_user.username
        db.session.add(Notification(
            recipient_id=dest_id, actor_id=current_user.id, verb='voeux_fetes', type='voeux_recu_' + cle,
            target_type='post', target_id=pub.id,
            message=infos['recu'].format(nom=nom, annee=annee),
            extra_data={'fete': cle, 'recu': True, 'emoji': infos['emoji'], 'annee': annee, 'pub_id': pub.id}))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"DEBUG: publication de vœux impossible : {e}")
        return jsonify(success=False, error="Publication impossible pour le moment. Réessayez."), 500
    return jsonify(success=True, message="Vœux publiés ! 🎉", url=url_for('main.feed'))