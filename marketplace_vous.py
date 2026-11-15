"""
marketplace_vous.py — page « Vous » du Marketplace + toutes les pages qui en dépendent.

Installation (à la FIN de routes.py, après le dernier bloc) :

    try:
        from marketplace_vous import init_marketplace_vous
        init_marketplace_vous(main_bp)
    except Exception as _e_mkv:
        print(f"DEBUG marketplace_vous : routes non chargées : {_e_mkv}")

Rien d'existant n'est modifié. Une seule nouvelle table (marketplace_avis), créée toute seule.
Les autres données réutilisent l'existant : MarketplaceFavori, HistoriqueActivite, Abonnement, ProfilInfoSup.
"""
import re
from datetime import datetime

from flask import Blueprint, abort, current_app, jsonify, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy.orm.attributes import InstrumentedAttribute

from extensions import db
from models import (Abonnement, Annonce, DemandeAmitie, HistoriqueActivite, MarketplaceFavori, Message,
                    Notification, ProfilInfoSup, User)


class MarketplaceAvis(db.Model):
    __tablename__ = 'marketplace_avis'
    __table_args__ = (db.UniqueConstraint('vendeur_id', 'auteur_id', name='uq_mk_avis'), {'extend_existing': True})
    id = db.Column(db.Integer, primary_key=True)
    vendeur_id = db.Column(db.Integer, nullable=False, index=True)
    auteur_id = db.Column(db.Integer, nullable=False, index=True)
    note = db.Column(db.Integer, nullable=False)
    commentaire = db.Column(db.String(500), nullable=True)
    date_creation = db.Column(db.DateTime, default=datetime.utcnow)


_etat = {'ok': False}
VILLES_CM = ['Douala', 'Yaoundé', 'Bafoussam', 'Bamenda', 'Garoua', 'Maroua', 'Ngaoundéré', 'Bertoua',
             'Buea', 'Limbé', 'Kribi', 'Ebolowa', 'Dschang', 'Bafang', 'Mbouda', 'Foumban', 'Nkongsamba', 'Edéa']


def _tables():
    if _etat['ok']:
        return
    try:
        MarketplaceAvis.__table__.create(bind=db.engine, checkfirst=True)
        ProfilInfoSup.__table__.create(bind=db.engine, checkfirst=True)
        _etat['ok'] = True
    except Exception as e:
        print(f"DEBUG marketplace_vous : création des tables impossible : {e}")


# ── Outils ────────────────────────────────────────────────────────────────────
def _avatar(u):
    return url_for('static', filename='uploads/' + ((getattr(u, 'avatar', None) if u else None) or 'default_avatar.png'))


def _verifie(u):
    """Badge bleu : abonnement Tsapi Verified encore valable (ou badge attribué par le PDG)."""
    exp = getattr(u, 'badge_expire', None)
    if exp and exp > datetime.utcnow():
        return True
    return bool(getattr(u, 'is_verify', False) and getattr(u, 'has_badge_bleu', False))


def _nom(u):
    return (getattr(u, 'nom_complet', None) or getattr(u, 'username', None) or 'Utilisateur') if u else 'Utilisateur'


def _statut(a):
    if getattr(a, 'vendue', False):
        return 'vendu'
    s = getattr(a, 'statut', None)
    return s if s in ('disponible', 'reserve', 'vendu') else 'disponible'


def _resoudre(endpoints, defaut, **valeurs):
    """Premier endpoint qui existe vraiment ; sinon un lien de secours qui, lui, existe (jamais '#')."""
    for ep in endpoints:
        try:
            return url_for(ep, **valeurs)
        except Exception:
            continue
    return defaut


def _chemin_existant(chemins, defaut):
    """Premier chemin réellement enregistré dans l'application ; sinon le lien de secours."""
    existants = {r.rule for r in current_app.url_map.iter_rules()}
    for c in chemins:
        if c in existants:
            return c
    return defaut


def _fiche(a):
    img = getattr(a, 'image', None)
    lien = _resoudre(['main.item_detail'], '/marketplace/annonce/%d' % a.id, item_id=a.id)
    return {'id': a.id, 'titre': a.titre or '', 'prix': a.prix or 0,
            'localisation': getattr(a, 'localisation', '') or '',
            'image': url_for('static', filename='uploads/' + (img or 'default_annonce.png')),
            'statut': _statut(a), 'url': lien}


def _col_proprio():
    for nom in ('proprietaire_id', 'user_id'):
        c = getattr(Annonce, nom, None)
        if isinstance(c, InstrumentedAttribute):
            return c
    return None


def _annonces_de(uid):
    c = _col_proprio()
    if c is not None:
        return Annonce.query.filter(c == uid).order_by(Annonce.date_creation.desc()).all()
    return [a for a in Annonce.query.order_by(Annonce.date_creation.desc()).all()
            if getattr(a, 'proprietaire_id', getattr(a, 'user_id', None)) == uid]


def _ville(user):
    _tables()
    try:
        ligne = db.session.get(ProfilInfoSup, (user.id, 'mk_ville'))
        if ligne and ligne.valeur:
            return ligne.valeur
    except Exception:
        db.session.rollback()
    return (getattr(user, 'ville', None) or '').strip()


def _fiche_user(u):
    lien = _resoudre(['main.profil_par_id'], '/marketplace/vendeur/%d' % u.id, user_id=u.id)
    return {'id': u.id, 'nom': _nom(u), 'avatar': _avatar(u), 'verifie': _verifie(u), 'url': lien}


def _moyenne(avis):
    return round(sum(a.note for a in avis) / len(avis), 1) if avis else 0


def _avis_json(lignes):
    ids = {l.auteur_id for l in lignes} | {l.vendeur_id for l in lignes}
    users = {u.id: u for u in User.query.filter(User.id.in_(ids)).all()} if ids else {}
    return [{'note': l.note, 'commentaire': l.commentaire or '',
             'date': l.date_creation.strftime('%d/%m/%Y') if l.date_creation else '',
             'auteur': _fiche_user(users[l.auteur_id]) if l.auteur_id in users else None,
             'vendeur': _fiche_user(users[l.vendeur_id]) if l.vendeur_id in users else None} for l in lignes]


def _page(mode, titre, retour='/marketplace/vous', **ctx):
    return render_template('marketplace_page.html', mode=mode, titre=titre, retour=retour, **ctx)


# ── Routes ────────────────────────────────────────────────────────────────────
def init_marketplace_vous(bp):

    @bp.route('/marketplace/vous')
    @login_required
    def mk_vous():
        return render_template('marketplace_vous.html', moi={
            'id': current_user.id, 'nom': _nom(current_user), 'avatar': _avatar(current_user),
            'verifie': _verifie(current_user)},
            liens={
                'messages': _resoudre(['marketplace_pro.messages'], '/marketplace/messages'),
                'notifications': _resoudre(['main.notifications'], '/notifications'),
                'parametres': _resoudre(['main.settings', 'main.parametres', 'main.settings_page', 'main.reglages'],
                                        _chemin_existant(['/settings', '/parametres', '/reglages', '/parametre'],
                                                         '/marketplace/localisation')),
            })

    @bp.route('/marketplace/enregistres')
    @login_required
    def mk_enregistres():
        ids = [f.annonce_id for f in MarketplaceFavori.query.filter_by(user_id=current_user.id).all()]
        ids.reverse()
        par_id = {a.id: a for a in Annonce.query.filter(Annonce.id.in_(ids)).all()} if ids else {}
        return _page('enregistres', 'Éléments enregistrés', fiches=[_fiche(par_id[i]) for i in ids if i in par_id])

    @bp.route('/marketplace/recents')
    @login_required
    def mk_recents():
        lignes = (HistoriqueActivite.query.filter_by(user_id=current_user.id, type='annonce')
                  .order_by(HistoriqueActivite.date_consultation.desc()).limit(150).all())
        vus, items = set(), []
        for l in lignes:
            if l.url in vus:
                continue
            vus.add(l.url)
            nums = re.findall(r'\d+', l.url or '')
            a = db.session.get(Annonce, int(nums[-1])) if nums else None
            items.append({'titre': l.titre or (a.titre if a else 'Annonce'), 'url': l.url,
                          'date': l.date_consultation.strftime('%d/%m/%Y %H:%M') if l.date_consultation else '',
                          'fiche': _fiche(a) if a else None})
            if len(items) >= 40:
                break
        return _page('recents', 'Vus récemment', items=items)

    @bp.route('/api/marketplace/recents/effacer', methods=['POST'])
    @login_required
    def mk_api_recents_effacer():
        try:
            HistoriqueActivite.query.filter_by(user_id=current_user.id, type='annonce').delete()
            db.session.commit()
            return jsonify(success=True)
        except Exception as e:
            db.session.rollback()
            print(f"DEBUG marketplace_vous : effacement impossible : {e}")
            return jsonify(success=False, error="Impossible pour le moment."), 500

    @bp.route('/marketplace/vos-annonces')
    @login_required
    def mk_vos_annonces():
        return _page('annonces', 'Vos annonces', fiches=[_fiche(a) for a in _annonces_de(current_user.id)])

    @bp.route('/marketplace/actions-rapides')
    @login_required
    def mk_actions_rapides():
        return _page('actions', 'Actions rapides', fiches=[_fiche(a) for a in _annonces_de(current_user.id)])

    @bp.route('/marketplace/activites')
    @login_required
    def mk_activites():
        mes = _annonces_de(current_user.id)
        fiches = [_fiche(a) for a in mes]
        ids = [a.id for a in mes]
        favoris = MarketplaceFavori.query.filter(MarketplaceFavori.annonce_id.in_(ids)).count() if ids else 0
        stats = {'total': len(fiches),
                 'disponibles': sum(1 for f in fiches if f['statut'] == 'disponible'),
                 'reservees': sum(1 for f in fiches if f['statut'] == 'reserve'),
                 'vendues': sum(1 for f in fiches if f['statut'] == 'vendu'),
                 'revenu': sum(f['prix'] for f in fiches if f['statut'] == 'vendu'),
                 'favoris': favoris}
        return _page('activites', 'Toutes les activités de vente', fiches=fiches, stats=stats)

    @bp.route('/marketplace/followers')
    @login_required
    def mk_followers():
        lignes = Abonnement.query.filter_by(suivi_id=current_user.id).order_by(Abonnement.id.desc()).limit(300).all()
        ids = [l.follower_id for l in lignes]
        users = {u.id: u for u in User.query.filter(User.id.in_(ids)).all()} if ids else {}
        return _page('followers', 'Followers Marketplace',
                     gens=[_fiche_user(users[i]) for i in ids if i in users])

    @bp.route('/marketplace/suivis')
    @login_required
    def mk_suivis():
        lignes = Abonnement.query.filter_by(follower_id=current_user.id).order_by(Abonnement.id.desc()).limit(300).all()
        ids = [l.suivi_id for l in lignes]
        users = {u.id: u for u in User.query.filter(User.id.in_(ids)).all()} if ids else {}
        return _page('suivis', 'Suivi(e)s', gens=[_fiche_user(users[i]) for i in ids if i in users])

    @bp.route('/marketplace/statut')
    @login_required
    def mk_statut():
        return _page('statut', 'Statut Marketplace')

    @bp.route('/marketplace/localisation')
    @login_required
    def mk_localisation():
        return _page('localisation', 'Localisation', ville=_ville(current_user), villes=VILLES_CM)

    @bp.route('/api/marketplace/localisation', methods=['GET', 'POST'])
    @login_required
    def mk_api_localisation():
        _tables()
        if request.method == 'POST':
            ville = ' '.join(str((request.get_json(silent=True) or {}).get('ville') or '').split())[:80]
            if re.search(r'[<>]', ville):
                return jsonify(success=False, error="Caractères non autorisés."), 400
            try:
                ligne = db.session.get(ProfilInfoSup, (current_user.id, 'mk_ville'))
                if ville:
                    if ligne is None:
                        db.session.add(ProfilInfoSup(user_id=current_user.id, cle='mk_ville', valeur=ville))
                    else:
                        ligne.valeur = ville
                elif ligne is not None:
                    db.session.delete(ligne)
                db.session.commit()
            except Exception as e:
                db.session.rollback()
                print(f"DEBUG marketplace_vous : localisation non enregistrée : {e}")
                return jsonify(success=False, error="Enregistrement impossible."), 500
        return jsonify(success=True, ville=_ville(current_user))

    @bp.route('/marketplace/avis')
    @login_required
    def mk_avis():
        _tables()
        recus = MarketplaceAvis.query.filter_by(vendeur_id=current_user.id).order_by(MarketplaceAvis.id.desc()).limit(100).all()
        donnes = MarketplaceAvis.query.filter_by(auteur_id=current_user.id).order_by(MarketplaceAvis.id.desc()).limit(100).all()
        return _page('avis', 'Avis', recus=_avis_json(recus), donnes=_avis_json(donnes), moyenne=_moyenne(recus))

    @bp.route('/marketplace/vendeur/<int:user_id>')
    @login_required
    def mk_vendeur(user_id):
        _tables()
        v = db.session.get(User, user_id)
        if v is None:
            abort(404)
        avis = MarketplaceAvis.query.filter_by(vendeur_id=user_id).order_by(MarketplaceAvis.id.desc()).limit(100).all()
        mon = next((a for a in avis if a.auteur_id == current_user.id), None)
        return _page('vendeur', 'Profil Marketplace', retour='/marketplace', vendeur=_fiche_user(v),
                     fiches=[_fiche(a) for a in _annonces_de(user_id)], avis=_avis_json(avis),
                     moyenne=_moyenne(avis), est_moi=(user_id == current_user.id),
                     mon_avis={'note': mon.note, 'commentaire': mon.commentaire or ''} if mon else None)

    @bp.route('/api/marketplace/avis', methods=['POST'])
    @login_required
    def mk_api_avis():
        _tables()
        d = request.get_json(silent=True) or {}
        try:
            vendeur_id, note = int(d.get('vendeur_id')), int(d.get('note'))
        except (TypeError, ValueError):
            return jsonify(success=False, error="Données invalides."), 400
        if not 1 <= note <= 5:
            return jsonify(success=False, error="La note doit être entre 1 et 5."), 400
        if vendeur_id == current_user.id:
            return jsonify(success=False, error="Vous ne pouvez pas vous noter vous-même."), 400
        if db.session.get(User, vendeur_id) is None:
            return jsonify(success=False, error="Vendeur introuvable."), 404
        texte = ' '.join(str(d.get('commentaire') or '').split())[:500] or None
        try:
            ligne = MarketplaceAvis.query.filter_by(vendeur_id=vendeur_id, auteur_id=current_user.id).first()
            if ligne is None:
                db.session.add(MarketplaceAvis(vendeur_id=vendeur_id, auteur_id=current_user.id, note=note, commentaire=texte))
            else:
                ligne.note, ligne.commentaire, ligne.date_creation = note, texte, datetime.utcnow()
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"DEBUG marketplace_vous : avis non enregistré : {e}")
            return jsonify(success=False, error="Enregistrement impossible."), 500
        return jsonify(success=True)

    # ── Compteurs du menu (la barre du haut les demandait : /api/menu/compteurs répondait 404) ──
    @bp.route('/api/menu/compteurs', methods=['GET'])
    def mk_api_menu_compteurs():
        if not current_user.is_authenticated:
            return jsonify(success=False, error="Connexion requise."), 401
        uid = current_user.id

        def compter(requete):
            try:
                return int(requete.count())
            except Exception as e:
                db.session.rollback()
                print(f"DEBUG marketplace_vous : compteur de menu impossible : {e}")
                return 0

        notifs = compter(Notification.query.filter_by(recipient_id=uid, is_read=False))
        messages = compter(Message.query.filter_by(destinataire_id=uid, lu=False))
        demandes = compter(DemandeAmitie.query.filter_by(recepteur_id=uid, statut='en_attente'))
        rep = jsonify(success=True, notifications=notifs, messages=messages, demandes=demandes,
                      amis=demandes, total=notifs + messages + demandes)
        rep.headers['Cache-Control'] = 'no-store'
        return rep


# Blueprint autonome : enregistré directement dans app.py (voir app.py). Si quelque chose casse ici,
# l'erreur apparaît au démarrage au lieu d'être avalée, et les pages ne dépendent plus de routes.py.
marketplace_vous_bp = Blueprint('marketplace_vous', __name__)
init_marketplace_vous(marketplace_vous_bp)