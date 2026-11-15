# -*- coding: utf-8 -*-
"""
ajouter_colonne_boost.py
────────────────────────────────────────────────────────────────────────
À lancer UNE SEULE FOIS (même principe que ajouter_colonnes_musique.py)
pour ajouter la colonne "date_fin" manquante à la table "post_boosts"
existante, nécessaire à l'expiration automatique des boosts.

Usage :
    python ajouter_colonne_boost.py

Adapte la ligne "from app import app, db" si ton fichier principal
Flask s'appelle autrement.
────────────────────────────────────────────────────────────────────────
"""
from sqlalchemy import text

try:
    from app import app, db
except ImportError:
    raise SystemExit(
        "Adapte l'import en haut de ce fichier : remplace 'from app import "
        "app, db' par le nom réel de ton fichier principal Flask."
    )

with app.app_context():
    colonnes_existantes = {
        col['name'] for col in db.inspect(db.engine).get_columns('post_boosts')
    }

    if 'date_fin' in colonnes_existantes:
        print("— La colonne 'date_fin' existe déjà, on ne touche à rien.")
    else:
        db.session.execute(text("ALTER TABLE post_boosts ADD COLUMN date_fin DATETIME"))
        db.session.commit()
        print("✔ Colonne 'date_fin' ajoutée à la table post_boosts.")

    print("\nTerminé.")