# ══════════════════════════════════════════════════════════════
#  AJOUT ADDITIF pour routes.py — REPUBLIER UN REEL (avec un petit mot)
#  À coller juste après api_reels_favoris_etat() (même zone que les favoris).
#  Rien d'existant n'est modifié. La table `reel_repost` est créée toute seule au premier
#  appel (même principe que reel_embed et les collections) : pas de migration à faire.
#  S'appuie sur des éléments déjà présents dans ton fichier :
#  _reel_video_accessible, _reel_erreur_serveur, _amis_ids, notifier, User, Publication, datetime.
# ══════════════════════════════════════════════════════════════
import re as _re_repost


class ReelRepost(db.Model):
    __tablename__ = 'reel_repost'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)          # celui qui republie
    publication_id = db.Column(db.Integer, nullable=False, index=True)   # le reel d'origine
    commentaire = db.Column(db.String(300))                              # le petit mot (facultatif)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)
    date_modification = db.Column(db.DateTime)
    __table_args__ = (db.UniqueConstraint('user_id', 'publication_id', name='uq_reel_repost'),)


_table_repost_ok = False
def _assurer_table_repost():
    global _table_repost_ok
    if _table_repost_ok:
        return
    try:
        ReelRepost.__table__.create(bind=db.engine, checkfirst=True)
        _table_repost_ok = True
    except Exception as e:
        print(f"DEBUG: création de la table reel_repost impossible : {e}")


def _nettoyer_note_repost(brut):
    """Petit mot : texte brut, sans caractères de contrôle, espaces normalisés, 300 caractères max."""
    s = _re_repost.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', str(brut or ''))
    s = _re_repost.sub(r'[ \t]+', ' ', s)
    s = _re_repost.sub(r'\n{3,}', '\n\n', s).strip()
    return s[:300]


def _total_reposts(pub_id):
    return ReelRepost.query.filter_by(publication_id=pub_id).count()


@main_bp.route('/api/reel/<int:pub_id>/republier', methods=['POST'])
@login_required
def api_reel_republier(pub_id):
    """Republie un reel (ou modifie le petit mot si déjà republié). → { success, cree, commentaire, total }"""
    pub, erreur = _reel_video_accessible(pub_id)
    if erreur:
        return erreur
    if pub.user_id == current_user.id:
        return jsonify(success=False, error="Vous ne pouvez pas republier votre propre reel."), 400
    # Seuls les reels publics se republient (sinon on exposerait un reel « amis » aux amis de quelqu'un d'autre).
    if (getattr(pub, 'confidentialite', None) or 'public') != 'public':
        return jsonify(success=False, error="Ce reel n'est pas public : il ne peut pas être republié."), 403
    note = _nettoyer_note_repost((request.get_json(silent=True) or {}).get('commentaire'))
    try:
        _assurer_table_repost()
        existant = ReelRepost.query.filter_by(user_id=current_user.id, publication_id=pub.id).first()
        cree = existant is None
        if existant:
            existant.commentaire = note or None
            existant.date_modification = datetime.utcnow()
        else:
            db.session.add(ReelRepost(user_id=current_user.id, publication_id=pub.id, commentaire=note or None))
        db.session.commit()
    except Exception as e:
        return _reel_erreur_serveur(e, "republier reel")
    if cree:
        try:   # l'auteur du reel est prévenu ; une panne de notification ne doit jamais bloquer la republication
            notifier(pub.user_id, 'share', current_user, cible=('post', pub.id), pub_id=pub.id)
        except Exception as e:
            db.session.rollback()
            print(f"DEBUG: notification republication : {e}")
    return jsonify(success=True, cree=cree, commentaire=note, total=_total_reposts(pub.id))


@main_bp.route('/api/reel/<int:pub_id>/republier/annuler', methods=['POST'])
@login_required
def api_reel_republier_annuler(pub_id):
    """Annule sa republication. → { success, total }"""
    try:
        _assurer_table_repost()
        ReelRepost.query.filter_by(user_id=current_user.id, publication_id=pub_id).delete(synchronize_session=False)
        db.session.commit()
        return jsonify(success=True, total=_total_reposts(pub_id))
    except Exception as e:
        return _reel_erreur_serveur(e, "annuler republication")


@main_bp.route('/api/reels/republications/etat', methods=['GET'])
@login_required
def api_reels_republications_etat():
    """État pour une liste d'ids (?ids=1,2,3) : ma republication, le total, les amis qui ont republié."""
    try:
        ids = []
        for brut in (request.args.get('ids') or '').split(','):
            brut = brut.strip()
            if brut.isdigit():
                ids.append(int(brut))
        ids = ids[:60]
        if not ids:
            return jsonify(success=True, etat={})
        _assurer_table_repost()
        moi = current_user.id
        mes = {r.publication_id: r for r in ReelRepost.query.filter(
            ReelRepost.user_id == moi, ReelRepost.publication_id.in_(ids)).all()}
        totaux = dict(db.session.query(ReelRepost.publication_id, db.func.count(ReelRepost.id))
                      .filter(ReelRepost.publication_id.in_(ids)).group_by(ReelRepost.publication_id).all())
        auteurs = dict(db.session.query(Publication.id, Publication.user_id)
                       .filter(Publication.id.in_(ids)).all())
        amis_ids = set(_amis_ids(moi) or set()) - {moi}
        lignes = []
        if amis_ids:
            lignes = ReelRepost.query.filter(ReelRepost.publication_id.in_(ids),
                                             ReelRepost.user_id.in_(amis_ids)
                                             ).order_by(ReelRepost.date_creation.desc()).all()
        users = {u.id: u for u in User.query.filter(User.id.in_({l.user_id for l in lignes})).all()} if lignes else {}
        amis_par_pub, amis_total = {}, {}
        for l in lignes:
            u = users.get(l.user_id)
            if not u:
                continue
            amis_total[l.publication_id] = amis_total.get(l.publication_id, 0) + 1
            liste = amis_par_pub.setdefault(l.publication_id, [])
            if len(liste) < 3:
                liste.append({'id': u.id, 'nom': u.nom_complet,
                              'avatar': url_for('static', filename='uploads/' + (u.avatar or 'default_avatar.png')),
                              'note': l.commentaire or ''})
        etat = {}
        for i in ids:
            etat[str(i)] = {'mine': i in mes, 'commentaire': (mes[i].commentaire or '') if i in mes else '',
                            'total': int(totaux.get(i, 0)), 'propre': auteurs.get(i) == moi,
                            'amis': amis_par_pub.get(i, []), 'amis_total': amis_total.get(i, 0)}
        return jsonify(success=True, etat=etat)
    except Exception as e:
        return _reel_erreur_serveur(e, "état des republications")