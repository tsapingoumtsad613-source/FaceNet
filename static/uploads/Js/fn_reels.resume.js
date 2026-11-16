/* FN Reels Resume : le reel CONTINUE là où la vidéo du fil s'était arrêtée (il ne recommence pas).
   Lit « fn_reel_resume » écrit par feed.html au clic sur une vidéo.
   Additif : ne modifie aucune fonction de reel.html, tout est dans des try/catch.
   La valeur est supprimée dès que la lecture a bien repris au bon endroit (ou après 15 s). */
(function () {
    'use strict';
    if (window.__fnReelsResume) return;
    window.__fnReelsResume = true;

    var CLE = 'fn_reel_resume';
    var VALIDITE_MS = 120000;
    var data = null;

    try {
        var brut = sessionStorage.getItem(CLE);
        if (!brut) return;
        data = JSON.parse(brut);
    } catch (e) { return; }
    if (!data || !data.id || !(data.t > 0.3) || (Date.now() - (data.ts || 0)) > VALIDITE_MS) {
        try { sessionStorage.removeItem(CLE); } catch (e) { }
        return;
    }

    var id = String(data.id);
    try {
        var p = new URLSearchParams(location.search).get('video');
        if (p && String(p) !== id) { sessionStorage.removeItem(CLE); return; }
    } catch (e) { }

    var termine = false;
    var observateur = null;
    var lies = [];

    function correspond(v) {
        if (v.id === 'reel-video-' + id) return true;
        var carte = v.closest ? v.closest('.reel-fullscreen-card') : null;
        if (carte && carte.id === 'publication-' + id) return true;
        var ds = v.dataset || {};
        if (String(ds.pubId || ds.id || ds.videoId || ds.reelId || '') === id) return true;
        var parent = v.closest ? v.closest('[data-pub-id],[data-id],[data-video-id],[data-reel-id]') : null;
        if (parent) {
            var d = parent.dataset || {};
            return String(d.pubId || d.id || d.videoId || d.reelId || '') === id;
        }
        return false;
    }

    function finir() {
        if (termine) return;
        termine = true;
        try { sessionStorage.removeItem(CLE); } catch (e) { }
        if (observateur) { try { observateur.disconnect(); } catch (e) { } }
    }

    function placer(v) {
        var cible = data.t;
        if (isFinite(v.duration) && v.duration > 0 && cible > v.duration - 0.5) { finir(); return; }
        try { v.currentTime = cible; } catch (e) { }
    }

    /* La page peut remettre la vidéo à zéro (amorçage de la première image, rechargement de la source…) :
       tant que la lecture n'a pas repris au bon endroit, on replace la vidéo (6 essais maximum). */
    function verifier(v) {
        if (termine) return;
        var ecart = (v.currentTime || 0) - data.t;
        if (ecart >= -1.5) { if (!v.paused) finir(); return; }
        v.__fnEssais = (v.__fnEssais || 0) + 1;
        if (v.__fnEssais > 6 || v.readyState < 1) return;
        placer(v);
    }

    function lier(v) {
        if (termine || v.__fnResume || v.tagName !== 'VIDEO' || !correspond(v)) return;
        v.__fnResume = true;
        try { v.dataset.frameReady = '1'; } catch (e) { }   /* évite l'amorçage à 0,01 s de reel.html */
        if (v.readyState >= 1) placer(v);
        else v.addEventListener('loadedmetadata', function () { placer(v); }, { once: true });
        var f = function () { verifier(v); };
        v.addEventListener('playing', f);
        v.addEventListener('timeupdate', f);
        lies.push(v);
    }

    function balayer() {
        var videos = document.getElementsByTagName('video');
        for (var i = 0; i < videos.length && !termine; i++) lier(videos[i]);
    }

    function demarrer() {
        balayer();
        if (termine || !('MutationObserver' in window) || !document.body) return;
        observateur = new MutationObserver(balayer);
        observateur.observe(document.body, { childList: true, subtree: true });
        setTimeout(finir, 15000);
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', demarrer);
    else demarrer();
})();