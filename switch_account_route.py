# À coller dans routes.py (le blueprint s'appelle `main`, comme dans settings.html).
# Adapte `User` si ton modèle a un autre nom.
from flask import session, redirect, url_for
from flask_login import current_user, login_user


@main.before_app_request
def remember_device_account():
    """Mémorise, dans le cookie de session signé de CET appareil,
    chaque compte qui s'est déjà connecté ici."""
    if current_user.is_authenticated:
        ids = session.get('device_accounts', [])
        if current_user.id not in ids:
            ids.append(current_user.id)
            session['device_accounts'] = ids
            session.permanent = True


@main.route('/switch-account/<username>')
def switch_account(username):
    """Changement de profil direct : aucun mot de passe demandé,
    on arrive sur l'accueil du profil choisi, sans déconnexion."""
    user = User.query.filter_by(username=username).first()
    if user and user.id in session.get('device_accounts', []):
        login_user(user, remember=True)
        return redirect(url_for('main.feed'))
    # compte jamais connecté sur cet appareil -> page de connexion normale
    return redirect(url_for('main.login', username=username))