# -*- coding: utf-8 -*-
"""
ajouter_colonne_musique_debut.py
────────────────────────────────────────────────────────────────────────
À lancer UNE SEULE FOIS, à la racine de ton projet Flask, pour ajouter la
colonne manquante "musique_debut" à la table "publication" existante
(le point de départ, en secondes, choisi par l'utilisateur dans l'écran
"Terminé" du sélecteur de musique) SANS toucher au reste de la base.

Usage :
    python ajouter_colonne_musique_debut.py
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
        col['name'] for col in db.inspect(db.engine).get_columns('publication')
    }

    if 'musique_debut' in colonnes_existantes:
        print("— La colonne 'musique_debut' existe déjà, on ne touche à rien.")
    else:
        db.session.execute(text("ALTER TABLE publication ADD COLUMN musique_debut FLOAT DEFAULT 0"))
        db.session.commit()
        print("✔ Colonne 'musique_debut' ajoutée à la table publication.")

    print("\nTerminé.")