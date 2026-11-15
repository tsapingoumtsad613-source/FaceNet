# -*- coding: utf-8 -*-
"""
FaceNet — Notes (comme sur Facebook / Messenger)

Module AUTONOME : il n'ajoute aucune colonne à models.py et ne modifie aucune
route existante. Il crée sa propre table « fn_notes » (automatiquement, au
premier appel) et ajoute des routes au blueprint « main » via
enregistrer_routes_notes(main_bp), appelée une seule fois à la fin de routes.py.

Routes ajoutées :
  GET  /note/creer                  -> page de création de la note
  GET  /api/notes/actives           -> ma note + celles de mes amis (24 h)
  POST /api/notes/publier           -> publier / remplacer ma note
  POST /api/notes/supprimer         -> supprimer ma note
  POST /api/notes/<id>/repondre     -> répondre à une note (arrive en message privé)
  GET  /api/notes/gifs              -> recherche de GIFs (Giphy, clé côté serveur)
"""
import os
from datetime import datetime, timedelta
from urllib.parse import urlparse

import requests
from flask import jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import or_

from extensions import db
from models import BlockedUser, DemandeAmitie, Message, User

NOTE_MAX_CARACTERES = 80
NOTE_DUREE_HEURES = 24
# Domaines autorisés pour les GIFs (évite d'afficher n'importe quelle URL)
_GIF_HOTES_OK = ('giphy.com', 'tenor.com')


class Note(db.Model):
    __tablename__ = 'fn_notes'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, nullable=False, index=True)
    texte = db.Column(db.String(NOTE_MAX_CARACTERES), nullable=True)
    musique_titre = db.Column(db.String(200), nullable=True)
    musique_artiste = db.Column(db.String(200), nullable=True)
    musique_cover = db.Column(db.String(500), nullable=True)
    musique_preview_url = db.Column(db.String(500), nullable=True)
    gif_url = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False, index=True)


_table_prete = False


def _assurer_table():
    """Crée la table fn_notes si elle n'existe pas (une seule fois par processus)."""
    global _table_prete
    if _table_prete:
        return
    Note.__table__.create(bind=db.engine, checkfirst=True)
    _table_prete = True


def _uid():
    return session.get('user_id')


def _ajax_ok():
    # Les écritures doivent venir de notre JS (un formulaire d'un autre site ne peut pas poser cet en-tête).
    return request.headers.get('X-Requested-With') == 'XMLHttpRequest'


def _ids_amis(uid):
    amis = set()
    for d in DemandeAmitie.query.filter(
            DemandeAmitie.statut == 'acceptee',
            or_(DemandeAmitie.emetteur_id == uid, DemandeAmitie.recepteur_id == uid)).all():
        amis.add(d.recepteur_id if d.emetteur_id == uid else d.emetteur_id)
    return amis


def _ids_bloques(uid):
    exclus = {b.blocked_id for b in BlockedUser.query.filter_by(owner_id=uid).all()}
    exclus |= {b.owner_id for b in BlockedUser.query.filter_by(blocked_id=uid).all()}
    return exclus


def _gif_valide(url):
    if not url:
        return None
    try:
        p = urlparse(url)
    except Exception:
        return None
    hote = (p.hostname or '').lower()
    if p.scheme != 'https' or not any(hote == h or hote.endswith('.' + h) for h in _GIF_HOTES_OK):
        return None
    return url[:500]


def _https_ou_none(url, maxlen=500):
    url = (url or '').strip()
    return url[:maxlen] if url.startswith('https://') else None


def _serialiser(note, auteur, moi_id):
    return {
        'id': note.id,
        'user_id': note.user_id,
        'username': auteur.username,
        'nom_complet': getattr(auteur, 'nom_complet', None) or auteur.username,
        'avatar': auteur.avatar or '',
        'texte': note.texte or '',
        'musique_titre': note.musique_titre or '',
        'musique_artiste': note.musique_artiste or '',
        'musique_cover': note.musique_cover or '',
        'musique_preview_url': note.musique_preview_url or '',
        'gif_url': note.gif_url or '',
        'created_at': note.created_at.isoformat() + 'Z',
        'mine': note.user_id == moi_id,
    }


def enregistrer_routes_notes(bp):
    """Ajoute les routes des notes au blueprint donné (main_bp)."""

    @bp.route('/note/creer')
    def creer_note():
        if not _uid():
            return redirect(url_for('main.login'))
        _assurer_table()
        actuelle = Note.query.filter(Note.user_id == _uid(),
                                     Note.expires_at > datetime.utcnow()).first()
        return render_template('note_creer.html', note_actuelle=actuelle,
                               note_max=NOTE_MAX_CARACTERES)

    @bp.route('/api/notes/actives', methods=['GET'])
    def api_notes_actives():
        if not _uid():
            return jsonify(success=False, error='Connexion requise.'), 401
        _assurer_table()
        moi = _uid()
        visibles = (_ids_amis(moi) - _ids_bloques(moi)) | {moi}
        notes = Note.query.filter(Note.user_id.in_(visibles),
                                  Note.expires_at > datetime.utcnow()) \
                          .order_by(Note.created_at.desc()).all()
        auteurs = {u.id: u for u in User.query.filter(User.id.in_([n.user_id for n in notes])).all()} if notes else {}
        data = [_serialiser(n, auteurs[n.user_id], moi) for n in notes if n.user_id in auteurs]
        return jsonify(success=True, notes=data, moi=moi)

    @bp.route('/api/notes/publier', methods=['POST'])
    def api_notes_publier():
        if not _uid():
            return jsonify(success=False, error='Connexion requise.'), 401
        if not _ajax_ok():
            return jsonify(success=False, error='Requête refusée.'), 403
        _assurer_table()
        texte = (request.form.get('texte') or '').strip()
        if len(texte) > NOTE_MAX_CARACTERES:
            return jsonify(success=False,
                           error=f'La note ne peut pas dépasser {NOTE_MAX_CARACTERES} caractères.'), 400
        musique_titre = (request.form.get('musique_titre') or '').strip()[:200] or None
        musique_artiste = (request.form.get('musique_artiste') or '').strip()[:200] or None
        musique_preview = _https_ou_none(request.form.get('musique_preview_url')) if musique_titre else None
        musique_cover = _https_ou_none(request.form.get('musique_cover')) if musique_titre else None
        gif_url = _gif_valide((request.form.get('gif_url') or '').strip())
        if not texte and not musique_titre and not gif_url:
            return jsonify(success=False, error='Écrivez quelque chose, ou ajoutez une musique ou un GIF.'), 400
        try:
            # Une seule note active par personne : la nouvelle remplace l'ancienne.
            Note.query.filter(Note.user_id == _uid()).delete()
            note = Note(user_id=_uid(), texte=texte or None,
                        musique_titre=musique_titre, musique_artiste=musique_artiste,
                        musique_cover=musique_cover, musique_preview_url=musique_preview,
                        gif_url=gif_url,
                        expires_at=datetime.utcnow() + timedelta(hours=NOTE_DUREE_HEURES))
            db.session.add(note)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"DEBUG notes publier : {e}")
            return jsonify(success=False, error='Impossible de publier la note, réessayez.'), 500
        return jsonify(success=True, id=note.id)

    @bp.route('/api/notes/supprimer', methods=['POST'])
    def api_notes_supprimer():
        if not _uid():
            return jsonify(success=False, error='Connexion requise.'), 401
        if not _ajax_ok():
            return jsonify(success=False, error='Requête refusée.'), 403
        _assurer_table()
        try:
            Note.query.filter(Note.user_id == _uid()).delete()
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"DEBUG notes supprimer : {e}")
            return jsonify(success=False, error='Suppression impossible.'), 500
        return jsonify(success=True)

    @bp.route('/api/notes/<int:note_id>/repondre', methods=['POST'])
    def api_notes_repondre(note_id):
        if not _uid():
            return jsonify(success=False, error='Connexion requise.'), 401
        if not _ajax_ok():
            return jsonify(success=False, error='Requête refusée.'), 403
        _assurer_table()
        moi = _uid()
        reponse = (request.form.get('contenu') or '').strip()
        if not reponse:
            return jsonify(success=False, error='Écrivez votre réponse.'), 400
        if len(reponse) > 1000:
            return jsonify(success=False, error='Réponse trop longue.'), 400
        note = db.session.get(Note, note_id)
        if not note or note.expires_at <= datetime.utcnow():
            return jsonify(success=False, error='Cette note a expiré.'), 404
        if note.user_id == moi:
            return jsonify(success=False, error='Vous ne pouvez pas répondre à votre propre note.'), 400
        if note.user_id not in (_ids_amis(moi) - _ids_bloques(moi)):
            return jsonify(success=False, error='Cette note n’est pas disponible.'), 403
        resume = note.texte or (note.musique_titre and f'🎵 {note.musique_titre}') or 'GIF'
        contenu = f'↩️ Réponse à votre note « {resume} » :\n{reponse}'
        try:
            msg = Message(expediteur_id=moi, destinataire_id=note.user_id, contenu=contenu)
            db.session.add(msg)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"DEBUG notes repondre : {e}")
            return jsonify(success=False, error='Envoi impossible, réessayez.'), 500
        try:  # même notification que pour un message normal ; n'empêche jamais l'envoi
            from notifications_service import notifier
            notifier(note.user_id, 'message', db.session.get(User, moi), cible=('message', msg.id))
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"DEBUG notification réponse note : {e}")
        return jsonify(success=True, destinataire_id=note.user_id)

    @bp.route('/api/notes/gifs', methods=['GET'])
    def api_notes_gifs():
        if not _uid():
            return jsonify(success=False, error='Connexion requise.'), 401
        cle = os.environ.get('GIPHY_API_KEY', '').strip()
        if not cle:
            return jsonify(success=False,
                           error="Les GIFs ne sont pas encore configurés (clé GIPHY_API_KEY manquante)."), 503
        q = (request.args.get('q') or '').strip()
        try:
            if q:
                r = requests.get('https://api.giphy.com/v1/gifs/search',
                                 params={'api_key': cle, 'q': q, 'limit': 24, 'rating': 'pg-13', 'lang': 'fr'},
                                 timeout=8)
            else:
                r = requests.get('https://api.giphy.com/v1/gifs/trending',
                                 params={'api_key': cle, 'limit': 24, 'rating': 'pg-13'}, timeout=8)
            r.raise_for_status()
            brut = r.json().get('data', [])
        except (requests.RequestException, ValueError):
            return jsonify(success=False, error='Service GIF indisponible, réessayez.'), 502
        gifs = []
        for g in brut:
            img = g.get('images', {})
            url = (img.get('fixed_height') or {}).get('url')
            mini = (img.get('fixed_width_small') or img.get('fixed_height_small') or {}).get('url') or url
            if _gif_valide(url):
                gifs.append({'url': url, 'preview': mini})
        return jsonify(success=True, gifs=gifs)