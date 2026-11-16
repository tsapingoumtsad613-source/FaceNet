/* FaceNet — client d'appel WebRTC (audio / vidéo) branché sur les routes /api/appel/*.
 * À inclure dans appel.html :  <script src="{{ url_for('static', filename='js/fn_appel.js') }}"></script>
 *
 *   FnAppel.demarrer({
 *     appelId: <id lu dans l'URL : ?appel_id=>,
 *     video: true|false,                       // ?type=video
 *     localVideo: <video muted>, remoteVideo: <video> ou <audio>,
 *     onEtat:  function (libelle, appel) {},   // "Sonnerie…", "Connecté", "Reconnexion…"
 *     onFin:   function (appel, raison) {},    // appel terminé / refusé / manqué
 *     onErreur: function (message) {}
 *   });
 *   FnAppel.raccrocher();  FnAppel.micro(true|false);  FnAppel.camera(true|false);
 * Serveurs STUN/TURN : définir window.FN_ICE_SERVERS avant le démarrage pour utiliser un TURN (recommandé en production). */
(function (global) {
    'use strict';
    var S = null;

    function api(chemin, corps) {
        var o = { credentials: 'same-origin', cache: 'no-store', headers: { 'X-Requested-With': 'XMLHttpRequest' } };
        if (corps !== undefined) { o.method = 'POST'; o.headers['Content-Type'] = 'application/json'; o.body = JSON.stringify(corps); }
        return fetch(chemin, o).then(function (r) { return r.json(); });
    }
    function envoyer(kind, payload) {
        return api('/api/appel/' + S.id + '/signal', { kind: kind, payload: payload }).catch(function () {});
    }
    function nettoyer() {
        if (!S) return;
        clearTimeout(S.minuteur);
        try { S.flux && S.flux.getTracks().forEach(function (t) { t.stop(); }); } catch (e) {}
        try { S.pc && S.pc.close(); } catch (e) {}
        S.fini = true;
    }
    function terminer(appel, raison) {
        if (!S || S.fini) return;
        nettoyer();
        if (S.opts.onFin) S.opts.onFin(appel, raison || (appel && appel.statut));
    }
    function appliquerSignal(sig) {
        var pc = S.pc;
        if (sig.kind === 'offer' && S.role === 'appele') {
            return pc.setRemoteDescription(sig.payload).then(function () { return vidangerIce(); })
                .then(function () { return pc.createAnswer(); })
                .then(function (rep) { return pc.setLocalDescription(rep).then(function () { return envoyer('answer', pc.localDescription); }); });
        }
        if (sig.kind === 'answer' && S.role === 'appelant') {
            return pc.setRemoteDescription(sig.payload).then(vidangerIce);
        }
        if (sig.kind === 'ice') {
            if (pc.remoteDescription && pc.remoteDescription.type) return pc.addIceCandidate(sig.payload).catch(function () {});
            S.iceEnAttente.push(sig.payload);
        }
        return Promise.resolve();
    }
    function vidangerIce() {
        var liste = S.iceEnAttente.splice(0);
        return Promise.all(liste.map(function (c) { return S.pc.addIceCandidate(c).catch(function () {}); }));
    }
    function boucle() {
        if (!S || S.fini) return;
        api('/api/appel/' + S.id + '/etat?after_id=' + S.dernierSignal).then(function (d) {
            if (!d || !d.success) { terminer(null, 'introuvable'); return; }
            S.role = d.role;
            var a = d.appel;
            if (['termine', 'refuse', 'annule', 'manque'].indexOf(a.statut) !== -1) { terminer(a); return; }
            if (S.opts.onEtat && !S.connecte) S.opts.onEtat(a.statut === 'sonne' ? 'Sonnerie…' : 'Connexion…', a);
            var suite = Promise.resolve();
            (d.signals || []).forEach(function (sig) {
                S.dernierSignal = Math.max(S.dernierSignal, sig.id);
                suite = suite.then(function () { return appliquerSignal(sig); }).catch(function () {});
            });
            return suite;
        }).catch(function () {}).then(function () {
            if (S && !S.fini) S.minuteur = setTimeout(boucle, S.connecte ? 2500 : 1000);
        });
    }

    var FnAppel = {
        demarrer: function (opts) {
            if (S) nettoyer();
            S = { opts: opts, id: opts.appelId, role: null, dernierSignal: 0, iceEnAttente: [], connecte: false, fini: false, flux: null, pc: null, minuteur: null };
            var contraintes = { audio: true, video: !!opts.video };
            return navigator.mediaDevices.getUserMedia(contraintes).then(function (flux) {
                S.flux = flux;
                if (opts.localVideo) { opts.localVideo.srcObject = flux; opts.localVideo.muted = true; opts.localVideo.play && opts.localVideo.play().catch(function () {}); }
                var pc = S.pc = new RTCPeerConnection({ iceServers: global.FN_ICE_SERVERS || [{ urls: 'stun:stun.l.google.com:19302' }, { urls: 'stun:stun1.l.google.com:19302' }] });
                flux.getTracks().forEach(function (t) { pc.addTrack(t, flux); });
                pc.ontrack = function (ev) {
                    if (opts.remoteVideo && ev.streams[0]) { opts.remoteVideo.srcObject = ev.streams[0]; opts.remoteVideo.play && opts.remoteVideo.play().catch(function () {}); }
                };
                pc.onicecandidate = function (ev) { if (ev.candidate) envoyer('ice', ev.candidate); };
                pc.onconnectionstatechange = function () {
                    if (!S || S.fini) return;
                    if (pc.connectionState === 'connected') { S.connecte = true; opts.onEtat && opts.onEtat('Connecté', null); }
                    else if (pc.connectionState === 'disconnected') { opts.onEtat && opts.onEtat('Reconnexion…', null); }
                    else if (pc.connectionState === 'failed') { opts.onErreur && opts.onErreur("La connexion a échoué (réseau ou pare-feu). Réessayez."); }
                };
                return api('/api/appel/' + S.id + '/etat').then(function (d) {
                    if (!d || !d.success) throw new Error('Appel introuvable.');
                    S.role = d.role;
                    if (S.role === 'appelant') {
                        return pc.createOffer().then(function (o) { return pc.setLocalDescription(o); }).then(function () { return envoyer('offer', pc.localDescription); });
                    }
                });
            }).then(function () { boucle(); }).catch(function (e) {
                nettoyer();
                var refus = e && (e.name === 'NotAllowedError' || e.name === 'PermissionDeniedError');
                if (opts.onErreur) opts.onErreur(refus ? "Autorisez le micro (et la caméra) pour passer l'appel." : ((e && e.message) || "Impossible de démarrer l'appel."));
                if (S && S.id) api('/api/appel/' + S.id + '/terminer', {}).catch(function () {});
            });
        },
        raccrocher: function () {
            if (!S) return Promise.resolve();
            var id = S.id;
            return api('/api/appel/' + id + '/terminer', {}).catch(function () {}).then(function (d) { terminer(d && d.appel, 'raccroche'); });
        },
        micro: function (actif) { if (S && S.flux) S.flux.getAudioTracks().forEach(function (t) { t.enabled = !!actif; }); },
        camera: function (actif) { if (S && S.flux) S.flux.getVideoTracks().forEach(function (t) { t.enabled = !!actif; }); }
    };
    global.FnAppel = FnAppel;
    window.addEventListener('pagehide', function () {
        if (S && !S.fini && navigator.sendBeacon) { try { navigator.sendBeacon('/api/appel/' + S.id + '/terminer', new Blob(['{}'], { type: 'application/json' })); } catch (e) {} }
    });
})(window);