"""
groupes_moderation.py — Routes réservées au staff d'un groupe (modérateurs et administrateurs).

  Modérateur : demandes d'adhésion, publications à valider, signalements, silence / avertissement / bannissement des membres.
  Administrateur : rôles, réglages, règles, questions, mots interdits, images, statistiques, journal, suppression du groupe.
  Protections : le créateur ne peut être ni rétrogradé, ni banni, ni retiré ; un modérateur n'agit que sur les membres simples ;
  seul le créateur (ou l'admin du site) agit sur un autre administrateur.
"""
import os
from datetime import datetime, timedelta

from flask import current_app, request
from sqlalchemy import func

from extensions import db
from groupes_core import (Erreur, PAGE, connecte, exiger_admin, exiger_staff, groupe_et_acces, groupes_pro_bp as bp, iso, journal,
                          lire_json, moi, notifier, posts_json, propre, purger_posts, user_min, users_par_id, _json)
from groupes_models import (CATEGORIES, Grp, GrpCom, GrpDemande, GrpJournal, GrpMembre, GrpNotif, GrpPost, GrpQuestion, GrpRegle,
                            GrpSignalement, TABLES_ENFANTS, VISIBILITES)


# =============================================================================
# Aides
# =============================================================================
def _cible_membre(gr, a, uid, bannis_ok=False):
    """Vérifie que l'acteur a le droit d'agir sur le membre `uid` et renvoie sa ligne GrpMembre."""
    m = GrpMembre.query.filter_by(groupe_id=gr.id, user_id=uid).first()
    if not m or (m.statut != 'actif' and not bannis_ok):
        raise Erreur('Membre introuvable.', 404)
    if uid == moi().id:
        raise Erreur('Vous ne pouvez pas agir sur vous-même.')
    if uid == gr.createur_id and not a.site:
        raise Erreur('Le créateur du groupe est protégé.', 403)
    if m.role == 'admin' and not (a.site or moi().id == gr.createur_id):
        raise Erreur('Seul le créateur du groupe peut agir sur un administrateur.', 403)
    if m.role == 'moderateur' and not a.admin:
        raise Erreur('Un modérateur ne peut pas agir sur un autre modérateur.', 403)
    return m


def _nom(uid):
    u = users_par_id([uid]).get(uid)
    return user_min(u)['nom']


# =============================================================================
# Compteurs + demandes d'adhésion
# =============================================================================
@bp.route('/api/<int:gid>/moderation/compteurs')
@connecte
def api_compteurs(gid):
    gr, a = groupe_et_acces(gid)
    exiger_staff(gr, a)
    return _json(demandes=GrpDemande.query.filter_by(groupe_id=gr.id, statut='en_attente').count(),
                 a_valider=GrpPost.query.filter_by(groupe_id=gr.id, statut='en_attente').count(),
                 signalements=GrpSignalement.query.filter_by(groupe_id=gr.id, statut='ouvert').count())


@bp.route('/api/<int:gid>/demandes')
@connecte
def api_demandes(gid):
    gr, a = groupe_et_acces(gid)
    exiger_staff(gr, a)
    lignes = GrpDemande.query.filter_by(groupe_id=gr.id, statut='en_attente').order_by(GrpDemande.id).limit(100).all()
    us = users_par_id([d.user_id for d in lignes])
    return _json(demandes=[{'id': d.id, 'utilisateur': user_min(us.get(d.user_id)), 'reponses': d.reponses, 'cree_le': iso(d.cree_le)} for d in lignes])


@bp.route('/api/demande/<int:did>/traiter', methods=['POST'])
@connecte
def api_traiter_demande(did):
    d = db.session.get(GrpDemande, did)
    if not d or d.statut != 'en_attente':
        raise Erreur('Demande introuvable ou déjà traitée.', 404)
    gr, a = groupe_et_acces(d.groupe_id)
    exiger_staff(gr, a)
    accepter = lire_json().get('decision') == 'accepter'
    d.statut, d.traite_par, d.traite_le = ('accepte' if accepter else 'refuse'), moi().id, datetime.utcnow()
    if accepter:
        m = GrpMembre.query.filter_by(groupe_id=gr.id, user_id=d.user_id).first()
        if m and m.statut == 'banni':
            raise Erreur('Cet utilisateur est banni du groupe.', 403)
        if not m:
            db.session.add(GrpMembre(groupe_id=gr.id, user_id=d.user_id))
            db.session.flush()
            gr.recompter()
    notifier([d.user_id], gr, ('Votre demande pour rejoindre « %s » a été acceptée.' if accepter else 'Votre demande pour rejoindre « %s » a été refusée.') % gr.nom)
    journal(gr, moi().id, 'demande_acceptee' if accepter else 'demande_refusee', _nom(d.user_id))
    db.session.commit()
    return _json()


# =============================================================================
# Publications à valider
# =============================================================================
@bp.route('/api/<int:gid>/a-valider')
@connecte
def api_a_valider(gid):
    gr, a = groupe_et_acces(gid)
    exiger_staff(gr, a)
    lignes = GrpPost.query.filter_by(groupe_id=gr.id, statut='en_attente').order_by(GrpPost.id).limit(50).all()
    return _json(posts=posts_json(lignes))


@bp.route('/api/post/<int:pid>/valider', methods=['POST'])
@connecte
def api_valider_post(pid):
    post = db.session.get(GrpPost, pid)
    if not post or post.statut != 'en_attente':
        raise Erreur('Publication introuvable ou déjà traitée.', 404)
    gr, a = groupe_et_acces(post.groupe_id)
    exiger_staff(gr, a)
    accepter = lire_json().get('decision') == 'accepter'
    if accepter:
        post.statut, post.motif_attente = 'publie', None
        post.cree_le = datetime.utcnow()
        notifier([post.auteur_id], gr, 'Votre publication dans « %s » a été approuvée.' % gr.nom, '/g/%d#post-%d' % (gr.id, post.id))
    else:
        notifier([post.auteur_id], gr, 'Votre publication dans « %s » n’a pas été approuvée.' % gr.nom)
        for rel in post.medias:
            try:
                os.remove(os.path.join(current_app.static_folder, 'uploads', rel))
            except OSError:
                pass
        purger_posts([post.id])
    journal(gr, moi().id, 'post_approuve' if accepter else 'post_refuse', 'publication #%d' % pid)
    db.session.commit()
    return _json()


# =============================================================================
# Signalements
# =============================================================================
@bp.route('/api/<int:gid>/signalements')
@connecte
def api_signalements(gid):
    gr, a = groupe_et_acces(gid)
    exiger_staff(gr, a)
    lignes = GrpSignalement.query.filter_by(groupe_id=gr.id, statut='ouvert').order_by(GrpSignalement.id).limit(60).all()
    us = users_par_id([s.signaleur_id for s in lignes])
    sortie = []
    for s in lignes:
        extrait, auteur_id = '', None
        if s.cible_type == 'post':
            p = db.session.get(GrpPost, s.cible_id)
            extrait, auteur_id = (p.contenu[:200], p.auteur_id) if p else ('(publication déjà supprimée)', None)
        elif s.cible_type == 'com':
            c = db.session.get(GrpCom, s.cible_id)
            extrait, auteur_id = (c.contenu[:200], c.auteur_id) if c and not c.supprime else ('(commentaire déjà supprimé)', None)
        else:
            auteur_id = s.cible_id
            extrait = 'Membre signalé : ' + _nom(s.cible_id)
        sortie.append({'id': s.id, 'cible_type': s.cible_type, 'cible_id': s.cible_id, 'motif': s.motif, 'detail': s.detail, 'extrait': extrait,
                       'auteur_id': auteur_id, 'signaleur': user_min(us.get(s.signaleur_id)), 'cree_le': iso(s.cree_le)})
    return _json(signalements=sortie)


@bp.route('/api/signalement/<int:sid>/traiter', methods=['POST'])
@connecte
def api_traiter_signalement(sid):
    s = db.session.get(GrpSignalement, sid)
    if not s or s.statut != 'ouvert':
        raise Erreur('Signalement introuvable ou déjà traité.', 404)
    gr, a = groupe_et_acces(s.groupe_id)
    exiger_staff(gr, a)
    decision = lire_json().get('decision')
    if decision == 'supprimer':
        if s.cible_type == 'post':
            p = db.session.get(GrpPost, s.cible_id)
            if p:
                notifier([p.auteur_id], gr, 'Une de vos publications a été supprimée après signalement dans « %s ».' % gr.nom)
                purger_posts([p.id])
        elif s.cible_type == 'com':
            c = db.session.get(GrpCom, s.cible_id)
            if c:
                c.supprime, c.contenu = True, ''
        s.statut = 'traite'
    elif decision == 'rejeter':
        s.statut = 'rejete'
    else:
        raise Erreur('Décision invalide.')
    s.traite_par = moi().id
    GrpSignalement.query.filter(GrpSignalement.groupe_id == gr.id, GrpSignalement.cible_type == s.cible_type,
                                GrpSignalement.cible_id == s.cible_id, GrpSignalement.statut == 'ouvert').update({'statut': s.statut, 'traite_par': moi().id})
    journal(gr, moi().id, 'signalement_' + s.statut, '%s #%d' % (s.cible_type, s.cible_id), s.motif)
    db.session.commit()
    return _json()


# =============================================================================
# Membres : rôle, silence, avertissement, bannissement, retrait
# =============================================================================
@bp.route('/api/<int:gid>/membres/<int:uid>/role', methods=['POST'])
@connecte
def api_role(gid, uid):
    gr, a = groupe_et_acces(gid)
    exiger_admin(gr, a)
    m = _cible_membre(gr, a, uid)
    role = lire_json().get('role')
    if role not in ('membre', 'moderateur', 'admin'):
        raise Erreur('Rôle invalide.')
    ancien, m.role = m.role, role
    notifier([uid], gr, 'Votre rôle dans « %s » est maintenant : %s.' % (gr.nom, {'membre': 'membre', 'moderateur': 'modérateur', 'admin': 'administrateur'}[role]))
    journal(gr, moi().id, 'role_change', _nom(uid), '%s → %s' % (ancien, role))
    db.session.commit()
    return _json(role=role)


@bp.route('/api/<int:gid>/membres/<int:uid>/silence', methods=['POST'])
@connecte
def api_silence(gid, uid):
    gr, a = groupe_et_acces(gid)
    exiger_staff(gr, a)
    m = _cible_membre(gr, a, uid)
    heures = lire_json().get('heures')
    heures = int(heures) if str(heures).isdigit() else 0
    if heures > 24 * 30:
        raise Erreur('Durée maximale : 30 jours.')
    m.muet_jusqua = datetime.utcnow() + timedelta(hours=heures) if heures else None
    if heures:
        notifier([uid], gr, 'Vous êtes réduit au silence dans « %s » pendant %d h.' % (gr.nom, heures))
    journal(gr, moi().id, 'silence' if heures else 'silence_leve', _nom(uid), '%d h' % heures if heures else '')
    db.session.commit()
    return _json()


@bp.route('/api/<int:gid>/membres/<int:uid>/avertir', methods=['POST'])
@connecte
def api_avertir(gid, uid):
    gr, a = groupe_et_acces(gid)
    exiger_staff(gr, a)
    m = _cible_membre(gr, a, uid)
    raison = propre(lire_json().get('raison'), 200) or 'Non-respect des règles du groupe'
    m.avertissements += 1
    texte = 'Avertissement dans « %s » : %s' % (gr.nom, raison)
    if m.avertissements % 3 == 0:
        m.muet_jusqua = datetime.utcnow() + timedelta(hours=24)
        texte += ' (3 avertissements : silence de 24 h)'
    notifier([uid], gr, texte)
    journal(gr, moi().id, 'avertissement', _nom(uid), raison)
    db.session.commit()
    return _json(avertissements=m.avertissements)


@bp.route('/api/<int:gid>/membres/<int:uid>/bannir', methods=['POST'])
@connecte
def api_bannir(gid, uid):
    gr, a = groupe_et_acces(gid)
    exiger_staff(gr, a)
    m = _cible_membre(gr, a, uid)
    d = lire_json()
    m.statut, m.role, m.banni_le = 'banni', 'membre', datetime.utcnow()
    m.raison_bannissement = propre(d.get('raison'), 250) or None
    if d.get('supprimer_contenu'):
        ids = [p.id for p in GrpPost.query.filter_by(groupe_id=gr.id, auteur_id=uid).all()]
        purger_posts(ids)
        GrpCom.query.filter_by(groupe_id=gr.id, auteur_id=uid).update({'supprime': True, 'contenu': ''})
    GrpDemande.query.filter_by(groupe_id=gr.id, user_id=uid, statut='en_attente').delete()
    db.session.flush()
    gr.recompter()
    journal(gr, moi().id, 'bannissement', _nom(uid), m.raison_bannissement or '')
    db.session.commit()
    return _json()


@bp.route('/api/<int:gid>/membres/<int:uid>/retirer', methods=['POST'])
@connecte
def api_retirer(gid, uid):
    gr, a = groupe_et_acces(gid)
    exiger_staff(gr, a)
    m = _cible_membre(gr, a, uid)
    db.session.delete(m)
    db.session.flush()
    gr.recompter()
    journal(gr, moi().id, 'membre_retire', _nom(uid))
    db.session.commit()
    return _json()


@bp.route('/api/<int:gid>/bannis')
@connecte
def api_bannis(gid):
    gr, a = groupe_et_acces(gid)
    exiger_staff(gr, a)
    lignes = GrpMembre.query.filter_by(groupe_id=gr.id, statut='banni').order_by(GrpMembre.banni_le.desc()).limit(100).all()
    us = users_par_id([m.user_id for m in lignes])
    return _json(bannis=[dict(user_min(us.get(m.user_id)), raison=m.raison_bannissement or '', banni_le=iso(m.banni_le)) for m in lignes])


@bp.route('/api/<int:gid>/membres/<int:uid>/debannir', methods=['POST'])
@connecte
def api_debannir(gid, uid):
    gr, a = groupe_et_acces(gid)
    exiger_staff(gr, a)
    m = _cible_membre(gr, a, uid, bannis_ok=True)
    if m.statut != 'banni':
        raise Erreur('Ce membre n’est pas banni.')
    db.session.delete(m)
    journal(gr, moi().id, 'debannissement', _nom(uid))
    db.session.commit()
    return _json()


# =============================================================================
# Réglages (admin)
# =============================================================================
def _bool(v):
    return v is True or str(v).lower() in ('1', 'true', 'on', 'oui')


@bp.route('/api/<int:gid>/parametres', methods=['POST'])
@connecte
def api_parametres(gid):
    gr, a = groupe_et_acces(gid)
    exiger_admin(gr, a)
    d = lire_json()
    modifies = []
    if 'nom' in d:
        nom = propre(d['nom'], 80)
        if len(nom) < 3:
            raise Erreur('Le nom doit contenir au moins 3 caractères.')
        gr.nom = nom; modifies.append('nom')
    if 'description' in d:
        gr.description = propre(d['description'], 1000); modifies.append('description')
    if d.get('categorie') in CATEGORIES:
        gr.categorie = d['categorie']; modifies.append('categorie')
    if d.get('visibilite') in VISIBILITES:
        gr.visibilite = d['visibilite']; modifies.append('visibilite')
    for cle in ('validation_adhesion', 'validation_publications', 'publications_anonymes', 'archive'):
        if cle in d:
            setattr(gr, cle, _bool(d[cle])); modifies.append(cle)
    for cle in ('qui_peut_publier', 'qui_peut_inviter'):
        if d.get(cle) in ('tous', 'admins'):
            setattr(gr, cle, d[cle]); modifies.append(cle)
    if 'mots_interdits' in d:
        gr.mots_interdits = propre(d['mots_interdits'], 2000); modifies.append('mots_interdits')
    if 'anti_flood_secondes' in d and str(d['anti_flood_secondes']).isdigit():
        gr.anti_flood_secondes = min(int(d['anti_flood_secondes']), 3600); modifies.append('anti_flood')
    journal(gr, moi().id, 'parametres', ', '.join(modifies))
    db.session.commit()
    return _json()


@bp.route('/api/<int:gid>/image', methods=['POST'])
@connecte
def api_image(gid):
    from groupes_core import sauver_image
    gr, a = groupe_et_acces(gid)
    exiger_admin(gr, a)
    for champ in ('avatar', 'couverture'):
        rel = sauver_image(request.files.get(champ))
        if rel:
            setattr(gr, champ, rel)
    journal(gr, moi().id, 'image_modifiee')
    db.session.commit()
    from groupes_core import url_upload
    return _json(avatar=url_upload(gr.avatar, 'default_groupe.png'), couverture=url_upload(gr.couverture))


@bp.route('/api/<int:gid>/regles', methods=['POST'])
@connecte
def api_regles(gid):
    gr, a = groupe_et_acces(gid)
    exiger_admin(gr, a)
    regles = [(propre(r.get('titre'), 120), propre(r.get('detail'), 600)) for r in (lire_json().get('regles') or []) if isinstance(r, dict)]
    regles = [r for r in regles if r[0]][:15]
    GrpRegle.query.filter_by(groupe_id=gr.id).delete()
    for i, (t, dt) in enumerate(regles):
        db.session.add(GrpRegle(groupe_id=gr.id, titre=t, detail=dt, ordre=i))
    journal(gr, moi().id, 'regles_modifiees', '%d règle(s)' % len(regles))
    db.session.commit()
    return _json()


@bp.route('/api/<int:gid>/questions', methods=['POST'])
@connecte
def api_questions(gid):
    gr, a = groupe_et_acces(gid)
    exiger_admin(gr, a)
    qs = [propre(q, 300) for q in (lire_json().get('questions') or []) if isinstance(q, str) and propre(q, 300)][:5]
    GrpQuestion.query.filter_by(groupe_id=gr.id).delete()
    for i, t in enumerate(qs):
        db.session.add(GrpQuestion(groupe_id=gr.id, texte=t, ordre=i))
    journal(gr, moi().id, 'questions_modifiees', '%d question(s)' % len(qs))
    db.session.commit()
    return _json()


# =============================================================================
# Statistiques, journal, suppression
# =============================================================================
@bp.route('/api/<int:gid>/stats')
@connecte
def api_stats(gid):
    gr, a = groupe_et_acces(gid)
    exiger_admin(gr, a)
    j7, j30 = datetime.utcnow() - timedelta(days=7), datetime.utcnow() - timedelta(days=30)
    top = (db.session.query(GrpPost.auteur_id, func.count()).filter(GrpPost.groupe_id == gr.id, GrpPost.statut == 'publie', GrpPost.cree_le > j30)
           .group_by(GrpPost.auteur_id).order_by(func.count().desc()).limit(5).all())
    us = users_par_id([t[0] for t in top])
    actifs = db.session.query(func.count(func.distinct(GrpPost.auteur_id))).filter(GrpPost.groupe_id == gr.id, GrpPost.cree_le > j7).scalar() or 0
    return _json(membres=gr.nb_membres,
                 nouveaux_7j=GrpMembre.query.filter(GrpMembre.groupe_id == gr.id, GrpMembre.statut == 'actif', GrpMembre.rejoint_le > j7).count(),
                 nouveaux_30j=GrpMembre.query.filter(GrpMembre.groupe_id == gr.id, GrpMembre.statut == 'actif', GrpMembre.rejoint_le > j30).count(),
                 posts_7j=GrpPost.query.filter(GrpPost.groupe_id == gr.id, GrpPost.statut == 'publie', GrpPost.cree_le > j7).count(),
                 posts_30j=GrpPost.query.filter(GrpPost.groupe_id == gr.id, GrpPost.statut == 'publie', GrpPost.cree_le > j30).count(),
                 commentaires_7j=GrpCom.query.filter(GrpCom.groupe_id == gr.id, GrpCom.supprime.is_(False), GrpCom.cree_le > j7).count(),
                 auteurs_actifs_7j=actifs,
                 top_contributeurs=[dict(user_min(us.get(uid)), publications=n) for uid, n in top])


@bp.route('/api/<int:gid>/journal')
@connecte
def api_journal(gid):
    gr, a = groupe_et_acces(gid)
    exiger_admin(gr, a)
    avant = request.args.get('avant', type=int)
    qs = GrpJournal.query.filter_by(groupe_id=gr.id)
    if avant:
        qs = qs.filter(GrpJournal.id < avant)
    lignes = qs.order_by(GrpJournal.id.desc()).limit(PAGE * 2 + 1).all()
    us = users_par_id([j.acteur_id for j in lignes])
    return _json(journal=[{'id': j.id, 'acteur': user_min(us.get(j.acteur_id)), 'action': j.action, 'cible': j.cible, 'detail': j.detail,
                           'cree_le': iso(j.cree_le)} for j in lignes[:PAGE * 2]], suite=len(lignes) > PAGE * 2)


@bp.route('/api/<int:gid>/supprimer-groupe', methods=['POST'])
@connecte
def api_supprimer_groupe(gid):
    u = moi()
    gr, a = groupe_et_acces(gid)
    if not (a.site or u.id == gr.createur_id):
        raise Erreur('Seul le créateur du groupe peut le supprimer.', 403)
    if propre(lire_json().get('confirmer'), 120) != gr.nom:
        raise Erreur('Recopiez exactement le nom du groupe pour confirmer.')
    for post in GrpPost.query.filter_by(groupe_id=gr.id).all():
        for rel in post.medias:
            try:
                os.remove(os.path.join(current_app.static_folder, 'uploads', rel))
            except OSError:
                pass
    for modele in TABLES_ENFANTS:
        modele.query.filter_by(groupe_id=gr.id).delete(synchronize_session=False)
    GrpNotif.query.filter_by(groupe_id=gr.id).delete(synchronize_session=False)
    db.session.delete(gr)
    db.session.commit()
    return _json()
