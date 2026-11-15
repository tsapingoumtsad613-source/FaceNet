"""
Banc d'essai du Cercle familial (base SQLite en mémoire : ne touche PAS à instance/facenet.db).

Utilisation : copier ce fichier à la racine du projet (à côté de models.py, routes.py, famille.py,
extensions.py) puis lancer :   python test_famille.py
Il vérifie : invitations (ami validé uniquement, lien libre), accepter/refuser, modifier/retirer/quitter, nom de la famille,
et la matrice de visibilité Public / Amis / Famille / Moi (fonction réelle _peut_voir_publication
extraite de routes.py ET clause SQL), y compris la perte d'accès quand l'amitié est rompue.
Sortie attendue : « RÉSULTAT : N contrôles réussis, 0 échec(s) ».
"""
import ast, os, sys, json
from datetime import datetime
from flask import Flask, Blueprint
from flask_login import login_required
sys.path.insert(0, os.getcwd())
from extensions import db, login_manager

app = Flask(__name__)
app.config.update(SQLALCHEMY_DATABASE_URI='sqlite:///:memory:', SECRET_KEY='t', TESTING=True,
                  SQLALCHEMY_TRACK_MODIFICATIONS=False)
db.init_app(app); login_manager.init_app(app)

import models
from models import User, Publication, DemandeAmitie, Notification
import famille

@login_manager.user_loader
def _lu(uid): return db.session.get(User, int(uid))

main_bp = Blueprint('main', __name__)
@main_bp.route('/settings')
def settings(): return 'settings'
@main_bp.route('/profile/<username>')
def profile(username): return username
famille.brancher_sur_main(main_bp)
app.register_blueprint(main_bp)

# --- vraie règle _peut_voir_publication extraite de routes.py ---
src = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'routes.py'), encoding='utf-8').read()
tree = ast.parse(src)
ns = {'_compte_masque': lambda uid: False, 'DemandeAmitie': DemandeAmitie, 'or_': famille.or_,
      '_famille_peut_voir': famille.peut_voir_famille}
for n in tree.body:
    if isinstance(n, ast.FunctionDef) and n.name in ('_amis_ids', '_peut_voir_publication'):
        exec(compile(ast.Module([n], []), 'routes', 'exec'), ns)
peut_voir = ns['_peut_voir_publication']

ok = ko = 0
def check(nom, cond):
    global ok, ko
    if cond: ok += 1
    else:
        ko += 1; print('  ECHEC :', nom)

with app.app_context():
    db.create_all()
    def mk(nom):
        u = User(username=nom, nom_complet=nom.upper(), email=f'{nom}@x.t', password='x')
        db.session.add(u); db.session.flush(); return u
    A,B,C,D,E,F,G = [mk(n) for n in 'abcdefg']
    def amis(x, y):
        db.session.add(DemandeAmitie(emetteur_id=x.id, recepteur_id=y.id, statut='acceptee'))
    for x in (B,C,E,F,G): amis(A, x)
    pubs = {}
    for niv in ('public','amis','famille','prive'):
        p = Publication(contenu=niv, user_id=A.id, confidentialite=niv); db.session.add(p); db.session.flush(); pubs[niv] = p
    db.session.commit()
    ids = dict(A=A.id,B=B.id,C=C.id,D=D.id,E=E.id,F=F.id,G=G.id)

def client_de(uid):
    c = app.test_client()
    with c.session_transaction() as s: s['_user_id'] = str(uid); s['_fresh'] = True
    return c

J = {'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json'}
def post(c, url, **data): return c.post(url, json=data, headers=J)

cA = client_de(ids['A'])
print('1) Invitations')
r = post(cA, '/famille/inviter', ami_id=ids['D'], lien='cousin');          check('non-ami refusé (403)', r.status_code == 403)
r = post(cA, '/famille/inviter', ami_id=ids['A'], lien='moi');             check('soi-même refusé', r.status_code == 400)
r = post(cA, '/famille/inviter', ami_id=ids['B'], lien='');                check('lien vide refusé', r.status_code == 400)
liens_libres = {'B': 'Demi-sœur', 'C': 'Arrière-grand-père', 'E': 'Grand-cousin éloigné (côté maternel)', 'F': 'Beau-frère', 'G': 'Marraine'}
lid = {}
for k, lien in liens_libres.items():
    r = post(cA, '/famille/inviter', ami_id=ids[k], lien=lien)
    check(f'invitation {k} « {lien} » acceptée par le serveur', r.status_code == 200 and r.get_json()['success'])
    lid[k] = r.get_json().get('id')
r = post(cA, '/famille/inviter', ami_id=ids['B'], lien='frère');           check('doublon en attente refusé', r.status_code == 400)
with app.app_context():
    n = Notification.query.filter_by(type='family_invite', recipient_id=ids['B']).first()
    check('notification créée pour B', n is not None and n.extra_data.get('famille_id') == lid['B'] and 'Demi-sœur' in n.message)
    check('avant acceptation : personne dans le cercle', famille.membres_famille_ids(ids['A']) == set())

print('2) Avant acceptation, rien de « famille » ne fuit')
def visibles(viewer):
    with app.app_context():
        return {niv for niv, p in pubs.items() if peut_voir(db.session.get(Publication, p.id), viewer)}
def visibles_sql(viewer):
    with app.test_request_context():
        rows = Publication.query.filter(famille.clause_publications_visibles(viewer)).all()
        return {p.contenu for p in rows}
for v in 'BCDEFG': check(f'{v} ne voit pas famille avant acceptation', 'famille' not in visibles(ids[v]))

print('3) Réponses aux invitations')
cB, cC, cD, cE, cF, cG = (client_de(ids[k]) for k in 'BCDEFG')
r = post(cE, f"/famille/{lid['B']}/repondre/accepter");  check('E ne peut pas répondre à l\'invitation de B (404)', r.status_code == 404)
r = post(cB, f"/famille/{lid['B']}/repondre/bidon");     check('action inconnue refusée (400)', r.status_code == 400)
r = post(cB, f"/famille/{lid['B']}/repondre/accepter");  check('B accepte', r.status_code == 200 and r.get_json()['statut'] == 'accepte')
r = post(cB, f"/famille/{lid['B']}/repondre/refuser");   check('B ne peut pas changer d\'avis par ce biais (409)', r.status_code == 409)
r = post(cC, f"/famille/{lid['C']}/repondre/accepter");  check('C accepte', r.status_code == 200)
r = post(cF, f"/famille/{lid['F']}/repondre/refuser");   check('F refuse', r.status_code == 200 and r.get_json()['statut'] == 'refuse')
r = post(cG, f"/famille/{lid['G']}/repondre/accepter");  check('G accepte', r.status_code == 200)
with app.app_context():
    n = Notification.query.filter_by(type='family_invite', recipient_id=ids['B']).first()
    check('invitation marquée traitée (boutons masqués)', n.extra_data.get('traitee') is True and n.extra_data.get('statut') == 'accepte')
    check('A notifié de l\'acceptation', Notification.query.filter_by(type='family_accept', recipient_id=ids['A']).count() == 3)

print('4) Matrice de visibilité (fonction réelle _peut_voir_publication ET clause SQL)')
attendu = {
  'A': {'public','amis','famille','prive'},
  'B': {'public','amis','famille'},        # famille acceptée
  'C': {'public','amis','famille'},
  'D': {'public'},                          # inconnu
  'E': {'public','amis'},                   # invitation jamais acceptée (en attente)
  'F': {'public','amis'},                   # a refusé
  'G': {'public','amis','famille'},         # accepté (avant rupture d'amitié)
}
for v, att in attendu.items():
    check(f'{v} Python  = {sorted(att)}  (obtenu {sorted(visibles(ids[v]))})', visibles(ids[v]) == att)
    check(f'{v} SQL     = {sorted(att)}  (obtenu {sorted(visibles_sql(ids[v]))})', visibles_sql(ids[v]) == att)
with app.app_context():
    check('anonyme Python', {n for n, p in pubs.items() if peut_voir(db.session.get(Publication, p.id), None)} == {'public'})
check('anonyme SQL', visibles_sql(None) == {'public'})

print('5) Rupture d\'amitié = perte immédiate de l\'accès famille')
with app.app_context():
    d = DemandeAmitie.query.filter(DemandeAmitie.statut=='acceptee', DemandeAmitie.recepteur_id==ids['G']).first()
    d.statut = 'refusee'; db.session.commit()
check('G (plus ami) : public seulement', visibles(ids['G']) == {'public'} and visibles_sql(ids['G']) == {'public'})

print('6) Modifier / retirer / quitter')
r = post(cB, f"/famille/{lid['B']}/modifier", lien='Sœur');             check('B ne peut pas modifier le lien de A (404)', r.status_code == 404)
r = post(cA, f"/famille/{lid['B']}/modifier", lien='  Sœur   jumelle ');check('A modifie le lien', r.status_code == 200 and r.get_json()['lien'] == 'Sœur jumelle')
r = post(cC, f"/famille/{lid['B']}/retirer");                          check('C ne peut pas retirer B du cercle de A (404)', r.status_code == 404)
r = post(cA, f"/famille/{lid['B']}/retirer");                          check('A retire B', r.status_code == 200)
check('B perd l\'accès famille immédiatement', visibles(ids['B']) == {'public','amis'} and visibles_sql(ids['B']) == {'public','amis'})
r = post(cC, f"/famille/{lid['C']}/quitter");                          check('C quitte le cercle', r.status_code == 200)
check('C perd l\'accès famille', 'famille' not in visibles(ids['C']))
r = post(cA, '/famille/inviter', ami_id=ids['F'], lien='Beau-frère');  check('F (refusé) peut être réinvité', r.status_code == 200)

print('7) Injection / valeurs extrêmes')
r = post(cA, '/famille/inviter', ami_id=ids['B'], lien='x'*500);
with app.app_context():
    l = famille.LienFamilial.query.filter_by(proprietaire_id=ids['A'], membre_id=ids['B']).first()
    check('lien tronqué à 60 caractères', l is not None and len(l.lien) <= 60)
r = post(cA, '/famille/inviter', ami_id='abc', lien='x');              check('ami_id non numérique refusé', r.status_code == 400)
r = cA.post('/famille/inviter', data={'ami_id': ids['C'], 'lien': '<script>alert(1)</script>'})
check('formulaire classique accepté (redirection)', r.status_code in (302, 303))

print('8) Nom de la famille')
r = post(cA, '/famille/nom', nom='  Famille   Dupont ')
check('A nomme sa famille (nom nettoyé)', r.status_code == 200 and r.get_json()['nom'] == 'Famille Dupont')
with app.app_context():
    check('nom enregistré', famille.nom_famille_de(ids['A']) == 'Famille Dupont')
    n = Notification.query.filter_by(type='family_invite', recipient_id=ids['E']).first()
    check('invitation en attente mise à jour avec le nom', n is not None and 'Famille Dupont' in n.message)
r = post(cA, '/famille/nom', nom='Les Dupont');            check('A modifie le nom', r.status_code == 200 and r.get_json()['nom'] == 'Les Dupont')
with app.app_context():
    check('un seul nom par propriétaire', famille.NomFamille.query.filter_by(proprietaire_id=ids['A']).count() == 1
          and famille.nom_famille_de(ids['A']) == 'Les Dupont')
r = post(cB, '/famille/nom', nom='Famille B');             check('B nomme SA famille', r.status_code == 200)
with app.app_context():
    check('le nom de B ne touche pas celui de A', famille.nom_famille_de(ids['A']) == 'Les Dupont' and famille.nom_famille_de(ids['B']) == 'Famille B')
    check('noms_familles_de', famille.noms_familles_de([ids['A'], ids['B'], ids['D']]) == {ids['A']: 'Les Dupont', ids['B']: 'Famille B'})
r = post(cA, '/famille/nom', nom='x'*500)
with app.app_context():
    check('nom tronqué à la longueur maximale', 0 < len(famille.nom_famille_de(ids['A'])) <= famille.LONGUEUR_MAX_NOM)
r = post(cA, '/famille/nom', nom='')
with app.app_context():
    check('nom vide = nom retiré', r.status_code == 200 and famille.nom_famille_de(ids['A']) == '')
    n = Notification.query.filter_by(type='family_invite', recipient_id=ids['E']).first()
    check('invitation sans nom après retrait', '«' not in n.message)
r = cA.post('/famille/nom', data={'nom': '<b>Mon clan</b>'})
check('formulaire classique accepté (redirection)', r.status_code in (302, 303))
with app.app_context():
    check('texte stocké tel quel (échappé à l\'affichage par Jinja)', famille.nom_famille_de(ids['A']) == '<b>Mon clan</b>')

print(f'\nRÉSULTAT : {ok} contrôles réussis, {ko} échec(s)')
sys.exit(1 if ko else 0)