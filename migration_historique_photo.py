"""
migration_photo_historique.py
--------------------------------
Script à exécuter UNE SEULE FOIS pour mettre à jour la base SQLite
existante avec les colonnes ajoutées dans models.py :
- user.notifier_changement_photo
- publication.type_publication
- la table photo_historique (créée automatiquement si absente)

Ne supprime ni ne modifie aucune donnée existante : ajoute seulement
les colonnes manquantes, avec des valeurs par défaut sûres pour les
lignes déjà présentes.

Utilisation :
    python migration_photo_historique.py
"""

from app import app  # adapte cet import si ton fichier principal Flask a un autre nom
from extensions import db
from sqlalchemy import text, inspect

with app.app_context():
    inspecteur = inspect(db.engine)

    colonnes_user = [c['name'] for c in inspecteur.get_columns('user')]
    if 'notifier_changement_photo' not in colonnes_user:
        db.session.execute(text(
            "ALTER TABLE user ADD COLUMN notifier_changement_photo BOOLEAN DEFAULT 1"
        ))
        print("✔ Colonne user.notifier_changement_photo ajoutée.")
    else:
        print("… user.notifier_changement_photo existe déjà, rien à faire.")

    colonnes_publication = [c['name'] for c in inspecteur.get_columns('publication')]
    if 'type_publication' not in colonnes_publication:
        db.session.execute(text(
            "ALTER TABLE publication ADD COLUMN type_publication VARCHAR(30)"
        ))
        print("✔ Colonne publication.type_publication ajoutée.")
    else:
        print("… publication.type_publication existe déjà, rien à faire.")

    db.session.commit()

    # Crée la table photo_historique si elle n'existe pas encore
    # (et toute autre table manquante définie dans models.py).
    db.create_all()
    print("✔ Table photo_historique vérifiée/créée.")

    print("\nMigration terminée avec succès.")