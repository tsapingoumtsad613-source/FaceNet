"""
groupes_pro.py — Routes du module « Groupes FaceNet » (blueprint `groupes_pro`, préfixe /g).

Branchement dans app.py (voir BRANCHEMENT_GROUPES.md) :
    from groupes_pro import groupes_pro_bp
    app.register_blueprint(groupes_pro_bp)

Pages : /g/  (hub)   /g/<id>  (page du groupe)   /g/<id>/gerer  (administration)
API   : /g/api/...   (JSON)
Les routes réservées au staff (modération, membres, réglages, statistiques, journal) sont dans groupes_moderation.py.
"""
import json
import os
from datetime import datetime, timedelta

from flask import current_app, render_template, request
from sqlalchemy import case, func, or_

from extensions import db
from groupes_core import (Acces, Erreur, MAX_COM, MAX_GROUPES_CREES, MAX_IMAGES_PAR_POST, MAX_POST, PAGE, appliquer_reaction,
                          blocage_entre, connecte, contient_interdit, exiger_ecriture, exiger_membre, exiger_staff, exiger_voir,
                          groupe_et_acces, groupe_json, groupes_pro_bp as bp, iso, journal, lire_json, moi, nb_liens, notifier,
                          parse_dt, posts_json, propre, purger_posts, sauver_image, staff_ids, url_upload, user_min, users_par_id,
                          _compte_reactions, _json)
from groupes_models import (CATEGORIES, Grp, GrpCom, GrpDemande, GrpEvenement, GrpInvitation, GrpMembre, GrpNotif, GrpOption,
                            GrpPost, GrpRsvp, GrpSignalement, GrpVote, REACTIONS, VISIBILITES)
from models import User

MOTIFS_SIGNALEMENT = ('spam', 'harcelement', 'haine', 'violence', 'fraude', 'nudite', 'desinformation', 'autre')


# =============================================================================
# Pages
# =============================================================================
@bp.route('/')
@connecte
def hub():
    return render_template('grp_hub.html', categories=CATEGORIES)


@bp.route('/<int:gid>')
@connecte
def page(gid):
    gr, a = groupe_et_acces(gid)
    return render_template('grp_page.html', gid=gr.id, nom=gr.nom, categories=CATEGORIES)


@bp.route('/<int:gid>/gerer')
@connecte
def gerer(gid):
    gr, a = groupe_et_acces(gid)
    exiger_staff(gr, a)
    return render_template('grp_gerer.html', gid=gr.id, nom=gr.nom, est_admin=a.admin, categories=CATEGORIES)


# =============================================================================
# Hub : découvrir, mes groupes, invitations, fil, notifications, création
# =============================================================================
@bp.route('/api/decouvrir')
@connecte
def api_decouvrir():
    u = moi()
    q = propre(request.args.get('q'), 80).replace('%', '').replace('_', '')
    cat = request.args.get('categorie')
    page = max(1, request.args.get('page', 1, type=int))
    bannis = [m.groupe_id for m in GrpMembre.query.filter_by(user_id=u.id, statut='banni').all()]
    qs = Grp.query.filter(Grp.visibilite.in_(('public', 'prive')), Grp.archive.is_(False))
    if bannis:
        qs = qs.filter(~Grp.id.in_(bannis))
    if q:
        qs = qs.filter(or_(Grp.nom.ilike('%' + q + '%'), Grp.description.ilike('%' + q + '%')))
    if cat in CATEGORIES:
        qs = qs.filter(Grp.categorie == cat)
    lignes = qs.order_by(Grp.nb_membres.desc(), Grp.id.desc()).offset((page - 1) * 20).limit(21).all()
    return _json(groupes=[groupe_json(gr, Acces(gr, u)) for gr in lignes[:20]], suite=len(lignes) > 20)


@bp.route('/api/mes-groupes')
@connecte
def api_mes_groupes():
    u = moi()
    lignes = (db.session.query(Grp, GrpMembre).join(GrpMembre, GrpMembre.groupe_id == Grp.id)
              .filter(GrpMembre.user_id == u.id, GrpMembre.statut == 'actif').order_by(Grp.nom).all())
    demandes = (db.session.query(Grp).join(GrpDemande, GrpDemande.groupe_id == Grp.id)
                .filter(GrpDemande.user_id == u.id, GrpDemande.statut == 'en_attente').all())
    return _json(groupes=[groupe_json(gr, Acces(gr, u)) for gr, _ in lignes],
                 demandes=[{'id': gr.id, 'nom': gr.nom, 'avatar': url_upload(gr.avatar, 'default_groupe.png')} for gr in demandes])


@bp.route('/api/invitations')
@connecte
def api_invitations():
    u = moi()
    invs = GrpInvitation.query.filter_by(invite_id=u.id, statut='en_attente').order_by(GrpInvitation.id.desc()).all()
    groupes = {gr.id: gr for gr in Grp.query.filter(Grp.id.in_([i.groupe_id for i in invs] or [0]))}
    users = users_par_id([i.par_id for i in invs])
    return _json(invitations=[{'id': i.id, 'groupe': {'id': i.groupe_id, 'nom': groupes[i.groupe_id].nom,
                                                      'avatar': url_upload(groupes[i.groupe_id].avatar, 'default_groupe.png'),
                                                      'nb_membres': groupes[i.groupe_id].nb_membres},
                               'par': user_min(users.get(i.par_id)), 'cree_le': iso(i.cree_le)}
                              for i in invs if i.groupe_id in groupes])


@bp.route('/api/invitation/<int:iid>/repondre', methods=['POST'])
@connecte
def api_invitation_repondre(iid):
    u = moi()
    inv = db.session.get(GrpInvitation, iid)
    if not inv or inv.invite_id != u.id or inv.statut != 'en_attente':
        raise Erreur('Invitation introuvable.', 404)
    gr = db.session.get(Grp, inv.groupe_id)
    accepter = bool(lire_json().get('accepter'))
    inv.statut = 'accepte' if accepter else 'refuse'
    if accepter and gr:
        m = GrpMembre.query.filter_by(groupe_id=gr.id, user_id=u.id).first()
        if m and m.statut == 'banni':
            raise Erreur('Vous avez été banni de ce groupe.', 403)
        if not m:
            db.session.add(GrpMembre(groupe_id=gr.id, user_id=u.id))
            db.session.flush()
            gr.recompter()
        notifier([inv.par_id], gr, '%s a rejoint « %s » grâce à votre invitation.' % (u.username, gr.nom))
    db.session.commit()
    return _json(groupe_id=gr.id if gr else None)


@bp.route('/api/creer', methods=['POST'])
@connecte
def api_creer():
    u, d = moi(), lire_json()
    nom = propre(d.get('nom'), 80)
    if len(nom) < 3:
        raise Erreur('Le nom du groupe doit contenir au moins 3 caractères.')
    if Grp.query.filter_by(createur_id=u.id).count() >= MAX_GROUPES_CREES:
        raise Erreur('Vous avez atteint la limite de %d groupes créés.' % MAX_GROUPES_CREES, 429)
    if Grp.query.filter(Grp.createur_id == u.id, func.lower(Grp.nom) == nom.lower()).first():
        raise Erreur('Vous avez déjà un groupe avec ce nom.')
    visibilite = d.get('visibilite') if d.get('visibilite') in VISIBILITES else 'public'
    gr = Grp(nom=nom, description=propre(d.get('description'), 1000), createur_id=u.id, visibilite=visibilite,
             categorie=d.get('categorie') if d.get('categorie') in CATEGORIES else 'autre',
             validation_adhesion=(visibilite != 'public'))
    db.session.add(gr)
    db.session.flush()
    db.session.add(GrpMembre(groupe_id=gr.id, user_id=u.id, role='admin'))
    db.session.flush()
    gr.recompter()
    journal(gr, u.id, 'groupe_cree', gr.nom)
    db.session.commit()
    return _json(id=gr.id)


@bp.route('/api/fil')
@connecte
def api_fil():
    """Publications récentes de TOUS mes groupes."""
    u = moi()
    avant = request.args.get('avant', type=int)
    ids = [m.groupe_id for m in GrpMembre.query.filter_by(user_id=u.id, statut='actif').all()]
    if not ids:
        return _json(posts=[], suite=False)
    qs = GrpPost.query.filter(GrpPost.groupe_id.in_(ids), GrpPost.statut == 'publie')
    if avant:
        qs = qs.filter(GrpPost.id < avant)
    lignes = qs.order_by(GrpPost.id.desc()).limit(PAGE + 1).all()
    return _json(posts=posts_json(lignes[:PAGE]), suite=len(lignes) > PAGE)


@bp.route('/api/notifs')
@connecte
def api_notifs():
    u = moi()
    lignes = GrpNotif.query.filter_by(user_id=u.id).order_by(GrpNotif.id.desc()).limit(30).all()
    non_lues = GrpNotif.query.filter_by(user_id=u.id, lu=False).count()
    return _json(non_lues=non_lues, notifs=[{'id': n.id, 'texte': n.texte, 'lien': n.lien, 'lu': n.lu, 'cree_le': iso(n.cree_le)} for n in lignes])


@bp.route('/api/notifs/lues', methods=['POST'])
@connecte
def api_notifs_lues():
    GrpNotif.query.filter_by(user_id=moi().id, lu=False).update({'lu': True})
    db.session.commit()
    return _json()


# =============================================================================
# Un groupe : infos, adhésion, invitations
# =============================================================================
@bp.route('/api/<int:gid>')
@connecte
def api_groupe(gid):
    gr, a = groupe_et_acces(gid)
    return _json(groupe=groupe_json(gr, a, detail=True))


@bp.route('/api/<int:gid>/rejoindre', methods=['POST'])
@connecte
def api_rejoindre(gid):
    u = moi()
    gr, a = groupe_et_acces(gid)
    if a.actif:
        raise Erreur('Vous êtes déjà membre.')
    if gr.archive:
        raise Erreur('Ce groupe est archivé.', 403)
    if a.invitation or not gr.validation_adhesion:
        db.session.add(GrpMembre(groupe_id=gr.id, user_id=u.id))
        db.session.flush()
        gr.recompter()
        if a.invitation:
            a.invitation.statut = 'accepte'
        db.session.commit()
        return _json(etat='membre')
    from groupes_models import GrpQuestion
    questions = GrpQuestion.query.filter_by(groupe_id=gr.id).order_by(GrpQuestion.ordre, GrpQuestion.id).all()
    reponses = [propre(x, 500) for x in (lire_json().get('reponses') or [])][:len(questions)]
    if len(questions) and (len(reponses) < len(questions) or not all(reponses)):
        raise Erreur('Répondez à toutes les questions pour envoyer votre demande.')
    if GrpDemande.query.filter_by(groupe_id=gr.id, user_id=u.id, statut='en_attente').first():
        raise Erreur('Votre demande est déjà en attente.')
    paires = [{'q': q.texte, 'r': r} for q, r in zip(questions, reponses)]
    db.session.add(GrpDemande(groupe_id=gr.id, user_id=u.id, reponses_json=json.dumps(paires, ensure_ascii=False)))
    notifier(staff_ids(gr), gr, '%s demande à rejoindre « %s ».' % (u.username, gr.nom), '/g/%d/gerer' % gr.id)
    db.session.commit()
    return _json(etat='demande')


@bp.route('/api/<int:gid>/annuler-demande', methods=['POST'])
@connecte
def api_annuler_demande(gid):
    GrpDemande.query.filter_by(groupe_id=gid, user_id=moi().id, statut='en_attente').delete()
    db.session.commit()
    return _json()


@bp.route('/api/<int:gid>/quitter', methods=['POST'])
@connecte
def api_quitter(gid):
    gr, a = groupe_et_acces(gid)
    exiger_membre(gr, a)
    if a.role == 'admin' and GrpMembre.query.filter_by(groupe_id=gr.id, role='admin', statut='actif').count() <= 1:
        raise Erreur('Vous êtes le seul administrateur : nommez-en un autre avant de partir, ou supprimez le groupe.')
    db.session.delete(a.m)
    db.session.flush()
    gr.recompter()
    db.session.commit()
    return _json()


@bp.route('/api/<int:gid>/chercher-utilisateurs')
@connecte
def api_chercher_utilisateurs(gid):
    u = moi()
    gr, a = groupe_et_acces(gid)
    if not (a.actif and (gr.qui_peut_inviter == 'tous' or a.staff)):
        raise Erreur('Vous ne pouvez pas inviter dans ce groupe.', 403)
    q = propre(request.args.get('q'), 60).replace('%', '').replace('_', '')
    if len(q) < 2:
        return _json(utilisateurs=[])
    exclus = [m.user_id for m in GrpMembre.query.filter_by(groupe_id=gr.id).all()] + [u.id]
    lignes = (User.query.filter(~User.id.in_(exclus), or_(User.username.ilike('%' + q + '%'), User.nom_complet.ilike('%' + q + '%')))
              .limit(12).all())
    invites = {i.invite_id for i in GrpInvitation.query.filter_by(groupe_id=gr.id, statut='en_attente')}
    return _json(utilisateurs=[dict(user_min(x), deja_invite=x.id in invites) for x in lignes if not blocage_entre(u.id, x.id)])


@bp.route('/api/<int:gid>/inviter', methods=['POST'])
@connecte
def api_inviter(gid):
    u = moi()
    gr, a = groupe_et_acces(gid)
    if not (a.actif and (gr.qui_peut_inviter == 'tous' or a.staff)):
        raise Erreur('Vous ne pouvez pas inviter dans ce groupe.', 403)
    ids = [int(x) for x in (lire_json().get('user_ids') or []) if str(x).isdigit()][:20]
    envoyes = 0
    for uid in ids:
        cible = db.session.get(User, uid)
        existant = GrpMembre.query.filter_by(groupe_id=gr.id, user_id=uid).first()
        if not cible or existant or blocage_entre(u.id, uid):
            continue
        if GrpInvitation.query.filter_by(groupe_id=gr.id, invite_id=uid, statut='en_attente').first():
            continue
        db.session.add(GrpInvitation(groupe_id=gr.id, invite_id=uid, par_id=u.id))
        notifier([uid], gr, '%s vous invite à rejoindre « %s ».' % (u.username, gr.nom), '/g/')
        envoyes += 1
    db.session.commit()
    return _json(envoyes=envoyes)


@bp.route('/api/<int:gid>/membres')
@connecte
def api_membres(gid):
    gr, a = groupe_et_acces(gid)
    exiger_voir(gr, a)
    q = propre(request.args.get('q'), 60).replace('%', '').replace('_', '')
    page = max(1, request.args.get('page', 1, type=int))
    qs = (db.session.query(GrpMembre, User).join(User, User.id == GrpMembre.user_id)
          .filter(GrpMembre.groupe_id == gr.id, GrpMembre.statut == 'actif'))
    if q:
        qs = qs.filter(or_(User.username.ilike('%' + q + '%'), User.nom_complet.ilike('%' + q + '%')))
    ordre = case((GrpMembre.role == 'admin', 0), (GrpMembre.role == 'moderateur', 1), else_=2)
    lignes = qs.order_by(ordre, GrpMembre.rejoint_le.desc()).offset((page - 1) * 30).limit(31).all()
    return _json(membres=[dict(user_min(x, m.role), rejoint_le=iso(m.rejoint_le), muet=m.est_muet(), avertissements=m.avertissements if a.staff else 0)
                          for m, x in lignes[:30]], suite=len(lignes) > 30)


# =============================================================================
# Publications
# =============================================================================
def _liste(src, cle):
    return src.getlist(cle) if hasattr(src, 'getlist') else (src.get(cle) or [])


def _vrai(v):
    return str(v).lower() in ('1', 'true', 'on', 'oui')


@bp.route('/api/<int:gid>/posts')
@connecte
def api_posts(gid):
    u = moi()
    gr, a = groupe_et_acces(gid)
    exiger_voir(gr, a)
    avant = request.args.get('avant', type=int)
    q = propre(request.args.get('q'), 80).replace('%', '').replace('_', '')
    qs = GrpPost.query.filter_by(groupe_id=gr.id, statut='publie')
    if request.args.get('type') == 'medias':
        qs = qs.filter(GrpPost.medias_json != '[]')
    if q:
        qs = qs.filter(GrpPost.contenu.ilike('%' + q + '%'))
    filtre = bool(q or avant or request.args.get('type'))
    if not filtre:
        qs = qs.filter(GrpPost.epingle.is_(False))
    if avant:
        qs = qs.filter(GrpPost.id < avant)
    lignes = qs.order_by(GrpPost.id.desc()).limit(PAGE + 1).all()
    tete = []
    if not filtre:
        tete = GrpPost.query.filter_by(groupe_id=gr.id, statut='publie', epingle=True).order_by(GrpPost.id.desc()).limit(3).all()
        tete += GrpPost.query.filter_by(groupe_id=gr.id, statut='en_attente', auteur_id=u.id).order_by(GrpPost.id.desc()).all()
    return _json(posts=posts_json(tete + lignes[:PAGE]), suite=len(lignes) > PAGE)


@bp.route('/api/<int:gid>/posts', methods=['POST'])
@connecte
def api_creer_post(gid):
    u = moi()
    gr, a = groupe_et_acces(gid)
    exiger_ecriture(gr, a)
    if gr.qui_peut_publier == 'admins' and not a.staff:
        raise Erreur('Seuls les administrateurs peuvent publier dans ce groupe.', 403)
    multipart = (request.content_type or '').startswith('multipart/')
    src = request.form if multipart else lire_json()
    fichiers = [f for f in request.files.getlist('images') if f and f.filename][:MAX_IMAGES_PAR_POST] if multipart else []
    contenu = propre(src.get('contenu'), MAX_POST)
    type_ = src.get('type') if src.get('type') in ('texte', 'annonce', 'sondage') else 'texte'
    if type_ == 'annonce' and not a.staff:
        raise Erreur('Seuls les administrateurs peuvent publier une annonce.', 403)
    options = [propre(o, 100) for o in _liste(src, 'options') if propre(o, 100)]
    if type_ == 'sondage':
        if not contenu:
            raise Erreur('Posez votre question pour le sondage.')
        if not 2 <= len(options) <= 8:
            raise Erreur('Un sondage doit avoir entre 2 et 8 choix.')
    if not contenu and not fichiers:
        raise Erreur('Écrivez quelque chose ou ajoutez une image.')
    # --- anti-spam ---
    maintenant = datetime.utcnow()
    if not a.staff:
        dernier = GrpPost.query.filter_by(groupe_id=gr.id, auteur_id=u.id).order_by(GrpPost.id.desc()).first()
        if dernier and (maintenant - dernier.cree_le).total_seconds() < max(0, gr.anti_flood_secondes):
            raise Erreur('Doucement : patientez quelques secondes avant de publier à nouveau.', 429)
        if GrpPost.query.filter(GrpPost.groupe_id == gr.id, GrpPost.auteur_id == u.id, GrpPost.cree_le > maintenant - timedelta(days=1)).count() >= 30:
            raise Erreur('Limite de 30 publications par jour atteinte dans ce groupe.', 429)
    # --- décision de modération automatique ---
    statut, motif = 'publie', None
    if not a.staff:
        mot = contient_interdit(gr, contenu + ' ' + ' '.join(options))
        if gr.validation_publications:
            statut, motif = 'en_attente', 'Validation obligatoire du groupe'
        elif mot:
            statut, motif = 'en_attente', 'Mot interdit : %s' % mot
        elif nb_liens(contenu) >= 3 or (nb_liens(contenu) >= 1 and a.m and (maintenant - a.m.rejoint_le) < timedelta(hours=24)):
            statut, motif = 'en_attente', 'Lien d’un membre récent / liens multiples'
    medias = [sauver_image(f) for f in fichiers]
    post = GrpPost(groupe_id=gr.id, auteur_id=u.id, contenu=contenu, type=type_, statut=statut, motif_attente=motif,
                   anonyme=gr.publications_anonymes and _vrai(src.get('anonyme')),
                   medias_json=json.dumps([m for m in medias if m]), commentaires_fermes=_vrai(src.get('commentaires_fermes')) and a.staff)
    if type_ == 'sondage':
        heures = src.get('duree_heures')
        if str(heures).isdigit() and 1 <= int(heures) <= 24 * 30:
            post.sondage_fin = maintenant + timedelta(hours=int(heures))
    db.session.add(post)
    db.session.flush()
    for i, t in enumerate(options if type_ == 'sondage' else []):
        db.session.add(GrpOption(groupe_id=gr.id, post_id=post.id, texte=t, ordre=i))
    if statut == 'en_attente':
        notifier(staff_ids(gr), gr, 'Une publication attend votre validation dans « %s ».' % gr.nom, '/g/%d/gerer' % gr.id)
    db.session.commit()
    return _json(post=posts_json([post])[0], en_attente=statut == 'en_attente', motif=motif)


def _post_et_groupe(pid):
    post = db.session.get(GrpPost, pid)
    if not post or post.statut == 'supprime':
        raise Erreur('Publication introuvable.', 404)
    gr, a = groupe_et_acces(post.groupe_id)
    return post, gr, a


def _effacer_fichiers(post):
    base = os.path.join(current_app.static_folder, 'uploads')
    for rel in post.medias:
        try:
            os.remove(os.path.join(base, rel))
        except OSError:
            pass


@bp.route('/api/post/<int:pid>/modifier', methods=['POST'])
@connecte
def api_modifier_post(pid):
    u = moi()
    post, gr, a = _post_et_groupe(pid)
    if post.auteur_id != u.id or gr.archive:
        raise Erreur('Vous ne pouvez pas modifier cette publication.', 403)
    exiger_ecriture(gr, a)
    contenu = propre(lire_json().get('contenu'), MAX_POST)
    if not contenu and not post.medias:
        raise Erreur('Le texte ne peut pas être vide.')
    if not a.staff and contient_interdit(gr, contenu):
        raise Erreur('Ce texte contient un mot interdit dans ce groupe.')
    post.contenu, post.modifie_le = contenu, datetime.utcnow()
    db.session.commit()
    return _json(post=posts_json([post])[0])


@bp.route('/api/post/<int:pid>/supprimer', methods=['POST'])
@connecte
def api_supprimer_post(pid):
    u = moi()
    post, gr, a = _post_et_groupe(pid)
    if post.auteur_id != u.id and not a.staff:
        raise Erreur('Vous ne pouvez pas supprimer cette publication.', 403)
    if post.auteur_id != u.id:
        journal(gr, u.id, 'post_supprime', 'publication #%d' % post.id, post.contenu[:120])
        notifier([post.auteur_id], gr, 'Une de vos publications a été supprimée par la modération de « %s ».' % gr.nom)
    _effacer_fichiers(post)
    purger_posts([post.id])
    db.session.commit()
    return _json()


@bp.route('/api/post/<int:pid>/epingler', methods=['POST'])
@connecte
def api_epingler(pid):
    post, gr, a = _post_et_groupe(pid)
    exiger_staff(gr, a)
    if not post.epingle and GrpPost.query.filter_by(groupe_id=gr.id, epingle=True).count() >= 3:
        raise Erreur('Vous pouvez épingler 3 publications maximum.')
    post.epingle = not post.epingle
    journal(gr, moi().id, 'post_epingle' if post.epingle else 'post_desepingle', 'publication #%d' % post.id)
    db.session.commit()
    return _json(epingle=post.epingle)


@bp.route('/api/post/<int:pid>/fermer-commentaires', methods=['POST'])
@connecte
def api_fermer_commentaires(pid):
    post, gr, a = _post_et_groupe(pid)
    if not (a.staff or post.auteur_id == moi().id):
        raise Erreur('Action non autorisée.', 403)
    post.commentaires_fermes = not post.commentaires_fermes
    db.session.commit()
    return _json(ferme=post.commentaires_fermes)


@bp.route('/api/post/<int:pid>/reagir', methods=['POST'])
@connecte
def api_reagir_post(pid):
    post, gr, a = _post_et_groupe(pid)
    exiger_membre(gr, a)
    if post.statut != 'publie':
        raise Erreur('Publication non disponible.', 404)
    return _json(reactions=appliquer_reaction(gr, 'post', post.id, lire_json().get('type')))


@bp.route('/api/post/<int:pid>/voter', methods=['POST'])
@connecte
def api_voter(pid):
    u = moi()
    post, gr, a = _post_et_groupe(pid)
    exiger_membre(gr, a)
    if post.type != 'sondage' or post.statut != 'publie':
        raise Erreur('Ce n’est pas un sondage.')
    if post.sondage_fin and post.sondage_fin < datetime.utcnow():
        raise Erreur('Ce sondage est terminé.')
    oid = lire_json().get('option_id')
    opt = db.session.get(GrpOption, int(oid)) if str(oid).isdigit() else None
    if not opt or opt.post_id != post.id:
        raise Erreur('Choix invalide.')
    vote = GrpVote.query.filter_by(post_id=post.id, user_id=u.id).first()
    if vote and vote.option_id == opt.id:
        db.session.delete(vote)                      # re-cliquer retire son vote
    elif vote:
        vote.option_id = opt.id
    else:
        db.session.add(GrpVote(groupe_id=gr.id, post_id=post.id, option_id=opt.id, user_id=u.id))
    db.session.commit()
    return _json(sondage=posts_json([post])[0]['sondage'])


# =============================================================================
# Commentaires
# =============================================================================
def _com_json(coms, a_par_groupe=None):
    u = moi()
    users = users_par_id({c.auteur_id for c in coms})
    reacts = _compte_reactions('com', [c.id for c in coms], u.id)
    sortie = []
    for c in coms:
        a = a_par_groupe[c.groupe_id]
        sortie.append({'id': c.id, 'post_id': c.post_id, 'parent_id': c.parent_id, 'supprime': c.supprime,
                       'auteur': user_min(users.get(c.auteur_id)), 'contenu': '' if c.supprime else c.contenu, 'cree_le': iso(c.cree_le),
                       'reactions': reacts[c.id], 'peut_supprimer': (c.auteur_id == u.id or a.staff) and not c.supprime})
    return sortie


@bp.route('/api/post/<int:pid>/commentaires')
@connecte
def api_commentaires(pid):
    post, gr, a = _post_et_groupe(pid)
    exiger_voir(gr, a)
    apres = request.args.get('apres', 0, type=int)
    lignes = GrpCom.query.filter(GrpCom.post_id == post.id, GrpCom.id > apres).order_by(GrpCom.id).limit(41).all()
    return _json(commentaires=_com_json(lignes[:40], {gr.id: a}), suite=len(lignes) > 40)


@bp.route('/api/post/<int:pid>/commentaires', methods=['POST'])
@connecte
def api_commenter(pid):
    u = moi()
    post, gr, a = _post_et_groupe(pid)
    exiger_ecriture(gr, a)
    if post.statut != 'publie':
        raise Erreur('Publication non disponible.', 404)
    if post.commentaires_fermes and not a.staff:
        raise Erreur('Les commentaires sont fermés sur cette publication.', 403)
    d = lire_json()
    contenu = propre(d.get('contenu'), MAX_COM)
    if not contenu:
        raise Erreur('Commentaire vide.')
    if not a.staff and contient_interdit(gr, contenu):
        raise Erreur('Votre commentaire contient un mot interdit dans ce groupe.')
    dernier = GrpCom.query.filter_by(auteur_id=u.id).order_by(GrpCom.id.desc()).first()
    if dernier and (datetime.utcnow() - dernier.cree_le).total_seconds() < 2:
        raise Erreur('Doucement, vous commentez trop vite.', 429)
    parent = db.session.get(GrpCom, int(d['parent_id'])) if str(d.get('parent_id') or '').isdigit() else None
    if parent and (parent.post_id != post.id or parent.supprime):
        raise Erreur('Commentaire parent introuvable.', 404)
    parent_id = (parent.parent_id or parent.id) if parent else None
    c = GrpCom(groupe_id=gr.id, post_id=post.id, parent_id=parent_id, auteur_id=u.id, contenu=contenu)
    db.session.add(c)
    cibles = {post.auteur_id} | ({parent.auteur_id} if parent else set())
    notifier([x for x in cibles if x != u.id], gr, '%s a commenté dans « %s ».' % (u.username, gr.nom), '/g/%d#post-%d' % (gr.id, post.id))
    db.session.commit()
    return _json(commentaire=_com_json([c], {gr.id: a})[0])


def _com_et_groupe(cid):
    c = db.session.get(GrpCom, cid)
    if not c:
        raise Erreur('Commentaire introuvable.', 404)
    gr, a = groupe_et_acces(c.groupe_id)
    return c, gr, a


@bp.route('/api/commentaire/<int:cid>/supprimer', methods=['POST'])
@connecte
def api_supprimer_commentaire(cid):
    u = moi()
    c, gr, a = _com_et_groupe(cid)
    if c.auteur_id != u.id and not a.staff:
        raise Erreur('Action non autorisée.', 403)
    if c.auteur_id != u.id:
        journal(gr, u.id, 'commentaire_supprime', 'commentaire #%d' % c.id, c.contenu[:120])
    c.supprime, c.contenu = True, ''
    db.session.commit()
    return _json()


@bp.route('/api/commentaire/<int:cid>/reagir', methods=['POST'])
@connecte
def api_reagir_commentaire(cid):
    c, gr, a = _com_et_groupe(cid)
    exiger_membre(gr, a)
    if c.supprime:
        raise Erreur('Commentaire supprimé.', 404)
    return _json(reactions=appliquer_reaction(gr, 'com', c.id, lire_json().get('type')))


# =============================================================================
# Événements
# =============================================================================
def _evt_json(evs, uid):
    rsvps = {}
    for eid, rep, n in db.session.query(GrpRsvp.evenement_id, GrpRsvp.reponse, func.count()).filter(
            GrpRsvp.evenement_id.in_([e.id for e in evs] or [0])).group_by(GrpRsvp.evenement_id, GrpRsvp.reponse):
        rsvps.setdefault(eid, {})[rep] = n
    mes = {r.evenement_id: r.reponse for r in GrpRsvp.query.filter(GrpRsvp.evenement_id.in_([e.id for e in evs] or [0]), GrpRsvp.user_id == uid)}
    return [{'id': e.id, 'titre': e.titre, 'description': e.description, 'lieu': e.lieu, 'debut': iso(e.debut), 'fin': iso(e.fin),
             'createur_id': e.createur_id, 'participants': rsvps.get(e.id, {}).get('participe', 0),
             'interesses': rsvps.get(e.id, {}).get('interesse', 0), 'ma_reponse': mes.get(e.id)} for e in evs]


@bp.route('/api/<int:gid>/evenements')
@connecte
def api_evenements(gid):
    gr, a = groupe_et_acces(gid)
    exiger_voir(gr, a)
    maintenant = datetime.utcnow() - timedelta(hours=3)
    a_venir = GrpEvenement.query.filter(GrpEvenement.groupe_id == gr.id, GrpEvenement.debut >= maintenant).order_by(GrpEvenement.debut).limit(50).all()
    passes = GrpEvenement.query.filter(GrpEvenement.groupe_id == gr.id, GrpEvenement.debut < maintenant).order_by(GrpEvenement.debut.desc()).limit(10).all()
    return _json(a_venir=_evt_json(a_venir, moi().id), passes=_evt_json(passes, moi().id),
                 peut_creer=a.actif and not gr.archive and (a.staff or gr.qui_peut_publier == 'tous'))


@bp.route('/api/<int:gid>/evenements', methods=['POST'])
@connecte
def api_creer_evenement(gid):
    u = moi()
    gr, a = groupe_et_acces(gid)
    exiger_ecriture(gr, a)
    if not (a.staff or gr.qui_peut_publier == 'tous'):
        raise Erreur('Seuls les administrateurs peuvent créer un événement.', 403)
    d = lire_json()
    titre = propre(d.get('titre'), 150)
    debut, fin = parse_dt(d.get('debut')), parse_dt(d.get('fin'))
    if len(titre) < 3 or not debut:
        raise Erreur('Un titre et une date de début sont nécessaires.')
    if debut < datetime.utcnow() - timedelta(days=1):
        raise Erreur('La date de début est dans le passé.')
    if fin and fin < debut:
        raise Erreur('La fin ne peut pas précéder le début.')
    e = GrpEvenement(groupe_id=gr.id, createur_id=u.id, titre=titre, description=propre(d.get('description'), 2000),
                     lieu=propre(d.get('lieu'), 200), debut=debut, fin=fin)
    db.session.add(e)
    db.session.flush()
    db.session.add(GrpRsvp(groupe_id=gr.id, evenement_id=e.id, user_id=u.id, reponse='participe'))
    membres = [m.user_id for m in GrpMembre.query.filter_by(groupe_id=gr.id, statut='actif').limit(500) if m.user_id != u.id]
    notifier(membres, gr, 'Nouvel événement dans « %s » : %s' % (gr.nom, titre))
    db.session.commit()
    return _json(evenement=_evt_json([e], u.id)[0])


@bp.route('/api/evenement/<int:eid>/repondre', methods=['POST'])
@connecte
def api_rsvp(eid):
    u = moi()
    e = db.session.get(GrpEvenement, eid)
    if not e:
        raise Erreur('Événement introuvable.', 404)
    gr, a = groupe_et_acces(e.groupe_id)
    exiger_membre(gr, a)
    rep = lire_json().get('reponse')
    if rep not in ('participe', 'interesse', 'non'):
        raise Erreur('Réponse invalide.')
    r = GrpRsvp.query.filter_by(evenement_id=e.id, user_id=u.id).first()
    if r and r.reponse == rep:
        db.session.delete(r)
    elif r:
        r.reponse = rep
    else:
        db.session.add(GrpRsvp(groupe_id=gr.id, evenement_id=e.id, user_id=u.id, reponse=rep))
    db.session.commit()
    return _json(evenement=_evt_json([e], u.id)[0])


@bp.route('/api/evenement/<int:eid>/supprimer', methods=['POST'])
@connecte
def api_supprimer_evenement(eid):
    u = moi()
    e = db.session.get(GrpEvenement, eid)
    if not e:
        raise Erreur('Événement introuvable.', 404)
    gr, a = groupe_et_acces(e.groupe_id)
    if e.createur_id != u.id and not a.staff:
        raise Erreur('Action non autorisée.', 403)
    GrpRsvp.query.filter_by(evenement_id=e.id).delete()
    db.session.delete(e)
    db.session.commit()
    return _json()


# =============================================================================
# Signalements (par tout membre)
# =============================================================================
@bp.route('/api/signaler', methods=['POST'])
@connecte
def api_signaler():
    u, d = moi(), lire_json()
    type_, cid = d.get('cible_type'), d.get('cible_id')
    if type_ not in ('post', 'com', 'membre') or not str(cid).isdigit():
        raise Erreur('Signalement invalide.')
    cid = int(cid)
    if type_ == 'post':
        cible = db.session.get(GrpPost, cid)
        gid = cible.groupe_id if cible else None
    elif type_ == 'com':
        cible = db.session.get(GrpCom, cid)
        gid = cible.groupe_id if cible else None
    else:
        cible, gid = None, d.get('groupe_id')
        gid = int(gid) if str(gid).isdigit() else None
    if not gid or (type_ != 'membre' and not cible):
        raise Erreur('Contenu introuvable.', 404)
    gr, a = groupe_et_acces(gid)
    exiger_membre(gr, a)
    motif = d.get('motif') if d.get('motif') in MOTIFS_SIGNALEMENT else 'autre'
    if GrpSignalement.query.filter_by(groupe_id=gr.id, cible_type=type_, cible_id=cid, signaleur_id=u.id, statut='ouvert').first():
        raise Erreur('Vous avez déjà signalé ce contenu.')
    db.session.add(GrpSignalement(groupe_id=gr.id, cible_type=type_, cible_id=cid, signaleur_id=u.id, motif=motif, detail=propre(d.get('detail'), 500)))
    notifier(staff_ids(gr), gr, 'Nouveau signalement dans « %s ».' % gr.nom, '/g/%d/gerer' % gr.id)
    db.session.commit()
    return _json()


import groupes_moderation  # noqa: E402,F401  (enregistre les routes réservées au staff sur le même blueprint)
