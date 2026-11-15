from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_required, current_user
from datetime import datetime, date, time
from types import SimpleNamespace
from sqlalchemy import or_
from extensions import db
from models import User, Notification, Publication, DemandeAmitie

anniv_bp = Blueprint('anniv', __name__)

MOIS_FR = ["Janvier", "Février", "Mars", "Avril", "Mai", "Juin",
           "Juillet", "Août", "Septembre", "Octobre", "Novembre", "Décembre"]


# ── Nouvelle table (créée toute seule par db.create_all(), aucune migration) ──
class VoeuAnniversaire(db.Model):
    __tablename__ = 'voeu_anniversaire'
    id = db.Column(db.Integer, primary_key=True)
    auteur_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)   # celui qui fête
    annee = db.Column(db.Integer, nullable=False)
    publication_id = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('auteur_id', 'user_id', 'annee', name='uq_voeu_annuel'),)


# ── Utilitaires ──────────────────────────────────────────────────────────────
def _en_date(raw):
    """User.birth_date est un db.Date : on accepte aussi un texte 'YYYY-MM-DD'."""
    if not raw:
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    try:
        return datetime.strptime(str(raw), '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


def _bissextile(a):
    return a % 4 == 0 and (a % 100 != 0 or a % 400 == 0)


def _occurrence(bday, annee):
    """Date de l'anniversaire pour une année donnée (29 fév. -> 28 fév. si année non bissextile)."""
    if bday.month == 2 and bday.day == 29 and not _bissextile(annee):
        return date(annee, 2, 28)
    return date(annee, bday.month, bday.day)


def _est_aujourdhui(bday, today):
    return _occurrence(bday, today.year) == today


def _amis_ids(user_id):
    demandes = DemandeAmitie.query.filter(
        DemandeAmitie.statut == 'acceptee',
        or_(DemandeAmitie.emetteur_id == user_id, DemandeAmitie.recepteur_id == user_id)).all()
    ids = set()
    for d in demandes:
        ids.add(d.recepteur_id if d.emetteur_id == user_id else d.emetteur_id)
    return ids


def _nom(u):
    return u.nom_complet or u.username


# ── Notifications automatiques (au plus 1 fois par jour et par processus) ────
_dernier_jour_traite = None


def notifier_anniversaires_du_jour():
    """Pour chaque personne dont c'est l'anniversaire, notifie tous ses amis (une seule fois par jour).

    Doit être appelée à chaque requête (voir le hook before_app_request ajouté dans routes.py) :
    elle ne fait le vrai travail qu'une fois par jour, puis retourne immédiatement.
    Ne lève jamais d'exception.
    """
    global _dernier_jour_traite
    today = date.today()
    if _dernier_jour_traite == today:
        return
    _dernier_jour_traite = today
    try:
        # Début du jour LOCAL exprimé en UTC (created_at est stocké en UTC) -> pas de décalage horaire
        debut_jour = datetime.utcnow() - (datetime.now() - datetime.combine(today, time.min))
        nb = 0
        for u in User.query.filter(User.birth_date.isnot(None)).all():
            bday = _en_date(u.birth_date)
            if not bday or not _est_aujourdhui(bday, today):
                continue
            amis = _amis_ids(u.id)
            if not amis:
                continue
            # Une seule requête pour savoir qui a déjà été notifié aujourd'hui
            deja = {r[0] for r in db.session.query(Notification.recipient_id).filter(
                Notification.recipient_id.in_(amis), Notification.verb == 'anniversaire',
                Notification.target_type == 'user', Notification.target_id == u.id,
                Notification.created_at >= debut_jour).all()}
            for ami_id in amis - deja:
                db.session.add(Notification(
                    recipient_id=ami_id, actor_id=u.id, verb='anniversaire', type='anniversaire',
                    target_type='user', target_id=u.id,
                    message=f"C'est l'anniversaire de {_nom(u)} aujourd'hui ! 🎂 Souhaitez-lui un joyeux anniversaire.",
                    extra_data={'anniv_user_id': u.id, 'annee': today.year}))
                nb += 1
        db.session.commit()
        if nb:
            print(f"[anniversaires] {nb} notification(s) d'anniversaire créée(s)")
    except Exception as e:
        db.session.rollback()
        _dernier_jour_traite = None   # on réessaiera à la prochaine requête
        print(f"[anniversaires] Erreur notifications : {e}")


# ── Page liste ───────────────────────────────────────────────────────────────
@anniv_bp.route('/anniversaires')
@login_required
def anniversaires():
    today = date.today()
    ids = _amis_ids(current_user.id)          # on n'affiche que les anniversaires des amis
    du_jour, du_mois, prochains = [], [], []
    users = User.query.filter(User.id.in_(ids), User.birth_date.isnot(None)).all() if ids else []
    for u in users:
        bday = _en_date(u.birth_date)
        if not bday:
            continue
        fiche = SimpleNamespace(id=u.id, username=u.username, nom_complet=_nom(u),
                                date_naissance=bday, avatar=u.avatar)
        occ = _occurrence(bday, today.year)
        if occ == today:
            du_jour.append(fiche)
        elif occ.month == today.month and occ > today:
            du_mois.append(fiche)
        else:
            if occ < today:
                occ = _occurrence(bday, today.year + 1)
            fiche.jours_restants = (occ - today).days
            prochains.append(fiche)
    du_mois.sort(key=lambda f: f.date_naissance.day)
    prochains.sort(key=lambda f: f.jours_restants)
    return render_template('anniversaire.html', anniversaires_du_jour=du_jour,
                           anniversaires_du_mois=du_mois, prochains_anniversaires=prochains[:10],
                           mois_actuel=MOIS_FR[today.month - 1])


# ── Menu de vœux (ouvert depuis la notification) ─────────────────────────────
@anniv_bp.route('/anniversaires/voeux/<int:user_id>')
@login_required
def voeux(user_id):
    cible = db.session.get(User, user_id)
    if not cible or user_id not in _amis_ids(current_user.id):
        flash("Cette personne n'est pas dans vos amis.", "error")
        return redirect(url_for('anniv.anniversaires'))
    bday = _en_date(cible.birth_date)
    today = date.today()
    cest_aujourdhui = bool(bday and _est_aujourdhui(bday, today))
    age = (today.year - bday.year) if bday else None
    deja = VoeuAnniversaire.query.filter_by(auteur_id=current_user.id, user_id=user_id,
                                            annee=today.year).first() is not None
    return render_template('voeux.html', cible=cible, prenom=(cible.prenom or _nom(cible).split(' ')[0]),
                           nom_complet=_nom(cible), age=age, cest_aujourdhui=cest_aujourdhui, deja=deja)


@anniv_bp.route('/anniversaires/voeux/<int:user_id>/publier', methods=['POST'])
@login_required
def publier_voeu(user_id):
    cible = db.session.get(User, user_id)
    if not cible or user_id not in _amis_ids(current_user.id):
        return jsonify({'status': 'error', 'message': "Cette personne n'est pas dans vos amis."}), 403
    data = request.get_json(silent=True) or {}
    contenu = (data.get('contenu') or '').strip()
    if not contenu or len(contenu) > 1500:
        return jsonify({'status': 'error', 'message': "Écrivez un message (1500 caractères max)."}), 400
    annee = date.today().year
    if VoeuAnniversaire.query.filter_by(auteur_id=current_user.id, user_id=user_id, annee=annee).first():
        return jsonify({'status': 'info', 'message': "Vous lui avez déjà souhaité son anniversaire cette année."})
    try:
        pub = Publication(contenu=contenu, user_id=current_user.id, confidentialite='amis',
                          identifies=str(user_id), type_publication='voeu_anniversaire')
        db.session.add(pub)
        db.session.flush()
        db.session.add(VoeuAnniversaire(auteur_id=current_user.id, user_id=user_id,
                                        annee=annee, publication_id=pub.id))
        db.session.add(Notification(
            recipient_id=user_id, actor_id=current_user.id, verb='anniversaire', type='anniversaire',
            target_type='post', target_id=pub.id,
            message=f"{_nom(current_user)} vous a souhaité un joyeux anniversaire 🎉",
            extra_data={'pub_id': pub.id}))
        db.session.commit()
        return jsonify({'status': 'success', 'message': "Votre message d'anniversaire est publié 🎉",
                        'url': url_for('main.feed') + f'#publication-{pub.id}'})
    except Exception as e:
        db.session.rollback()
        print(f"[anniversaires] Erreur publication vœu : {e}")
        return jsonify({'status': 'error', 'message': "Publication impossible pour le moment."}), 500