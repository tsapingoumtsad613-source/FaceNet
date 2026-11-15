# no_cache.py
from functools import wraps
from flask import make_response


def no_cache(view):
    """
    Empêche le navigateur de mettre en cache la page.
    À utiliser sur les routes sensibles (accueil, dashboard, profil...).
    """
    @wraps(view)
    def no_cache_view(*args, **kwargs):
        response = make_response(view(*args, **kwargs))
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response
    return no_cache_view