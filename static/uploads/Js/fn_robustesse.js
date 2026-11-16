/* FaceNet : couche de robustesse autonome pour feed.html et reel.html.
   Purement additive : n'altère aucune fonction existante, ne bloque jamais la page
   (tout est enveloppé dans des try/catch). Fonctions :
   1. Bandeau « Pas de connexion » / « Connexion rétablie »
   2. Avatar cassé -> avatar par défaut
   3. Chargement paresseux des images hors écran
   4. Une seule vidéo à la fois dans le fil (les reels gèrent déjà leur lecture) */
(function () {
    'use strict';
    if (window.__fnRobustesse) return;
    window.__fnRobustesse = true;

    var AVATAR_DEFAUT = '/static/uploads/default_avatar.png';

    /* 1. Hors-ligne */
    try {
        var banniere = null, timer = null;
        var montrer = function (texte, fond) {
            if (!document.body) return;
            if (!banniere) {
                banniere = document.createElement('div');
                banniere.setAttribute('role', 'status');
                banniere.setAttribute('aria-live', 'polite');
                banniere.style.cssText = 'position:fixed;left:0;right:0;top:0;z-index:2147483000;' +
                    'padding:calc(8px + env(safe-area-inset-top,0px)) 12px 8px;text-align:center;' +
                    'font:600 13px/1.3 system-ui,-apple-system,sans-serif;color:#fff;' +
                    'transform:translateY(-110%);transition:transform .25s ease;pointer-events:none;';
                document.body.appendChild(banniere);
            }
            banniere.textContent = texte;
            banniere.style.background = fond;
            requestAnimationFrame(function () { banniere.style.transform = 'translateY(0)'; });
        };
        var cacher = function () { if (banniere) banniere.style.transform = 'translateY(-110%)'; };
        window.addEventListener('offline', function () {
            clearTimeout(timer);
            montrer('Pas de connexion Internet', '#444');
        });
        window.addEventListener('online', function () {
            clearTimeout(timer);
            montrer('Connexion rétablie', '#2e7d32');
            timer = setTimeout(cacher, 2200);
        });
        if (navigator.onLine === false) montrer('Pas de connexion Internet', '#444');
    } catch (e) { /* jamais bloquant */ }

    /* 2. Avatar cassé -> avatar par défaut (uniquement pour les images d'avatar) */
    try {
        document.addEventListener('error', function (ev) {
            var img = ev.target;
            if (!img || img.tagName !== 'IMG' || img.dataset.fnFallback === '1') return;
            var cls = ((img.className || '') + ' ' + ((img.parentElement && img.parentElement.className) || '')).toString();
            if (!/avatar|\bav\b|pam-av|story-ring|profile-pic|user-pic/i.test(cls)) return;
            img.dataset.fnFallback = '1';
            img.src = AVATAR_DEFAUT;
        }, true);
    } catch (e) { /* jamais bloquant */ }

    /* 3. Images paresseuses (celles déjà proches de l'écran ne sont pas touchées) */
    try {
        var rendreParesseux = function (img) {
            if (!img || img.tagName !== 'IMG' || img.hasAttribute('loading') || img.complete) return;
            var r = img.getBoundingClientRect();
            if (r.top < window.innerHeight * 1.5) return;
            img.loading = 'lazy';
            img.decoding = 'async';
        };
        var balayer = function (racine) {
            if (!racine || !racine.querySelectorAll) return;
            var imgs = racine.querySelectorAll('img:not([loading])');
            for (var i = 0; i < imgs.length; i++) rendreParesseux(imgs[i]);
        };
        var demarrer = function () {
            balayer(document);
            if ('MutationObserver' in window && document.body) {
                var attente = null, aTraiter = [];
                new MutationObserver(function (muts) {
                    muts.forEach(function (m) {
                        m.addedNodes.forEach(function (n) { if (n.nodeType === 1) aTraiter.push(n); });
                    });
                    if (attente) return;
                    attente = setTimeout(function () {
                        attente = null;
                        var lot = aTraiter; aTraiter = [];
                        lot.forEach(function (n) { if (n.tagName === 'IMG') rendreParesseux(n); else balayer(n); });
                    }, 120);
                }).observe(document.body, { childList: true, subtree: true });
            }
        };
        if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', demarrer);
        else demarrer();
    } catch (e) { /* jamais bloquant */ }

    /* 4. Une seule vidéo à la fois (fil d'actualité uniquement) */
    try {
        document.addEventListener('play', function (ev) {
            var v = ev.target;
            if (!v || v.tagName !== 'VIDEO') return;
            if (document.getElementById('reels-container')) return; // page Reels : lecture gérée par la page
            var toutes = document.getElementsByTagName('video');
            for (var i = 0; i < toutes.length; i++) {
                if (toutes[i] !== v && !toutes[i].paused) { try { toutes[i].pause(); } catch (e) { } }
            }
        }, true);
    } catch (e) { /* jamais bloquant */ }
})();