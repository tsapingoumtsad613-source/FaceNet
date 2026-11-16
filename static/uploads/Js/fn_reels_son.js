/* FN Reels Son : affichage dynamique du volume (0 à 300 %) + détection Bluetooth.
   Additif : ne modifie aucune fonction de reel.html, tout est dans des try/catch.
   AUCUN menu ni bouton ajouté : seulement un affichage qui apparaît quand le volume change.
   Déclencheurs : touches de volume lues par la page (application mobile / WebView qui les relaie,
   touches multimédia du clavier) et touches + / - (ordinateur). Une application native peut aussi appeler
   window.fnReelsVolume.monter(10) / .monter(-10) ou envoyer l'évènement « fn-volume-key ».
   Jusqu'à 100 % : volume natif. Au-delà : amplification Web Audio (vidéos du même site uniquement).
   Le boost n'est jamais mémorisé : on repart à 100 % maximum à chaque visite. */
(function () {
    'use strict';
    if (window.__fnReelsSon) return;
    window.__fnReelsSon = true;

    var CLE = 'fn_reel_volume', MAX = 300, PAS = 10;
    var niveau = 100;
    try {
        var m = parseInt(localStorage.getItem(CLE), 10);
        if (isFinite(m) && m >= 0) niveau = Math.min(100, m);
    } catch (e) { }

    var ctx = null, gain = null, sources = new WeakMap();

    function toast(msg) { try { if (typeof showReelToast === 'function') showReelToast(msg); } catch (e) { } }
    function videoActive() {
        try { if (typeof reelActiveVideo !== 'undefined' && reelActiveVideo) return reelActiveVideo; } catch (e) { }
        var vs = document.querySelectorAll('#reels-container video');
        for (var i = 0; i < vs.length; i++) if (!vs[i].paused) return vs[i];
        return null;
    }

    /* ---- Moteur audio (boost au-delà de 100 %) ---- */
    function memeOrigine(v) {
        try { return new URL(v.currentSrc || v.src || '', location.href).origin === location.origin; } catch (e) { return false; }
    }
    function assurerCtx() {
        try {
            if (!ctx) {
                var AC = window.AudioContext || window.webkitAudioContext;
                if (!AC) return false;
                ctx = new AC();
                gain = ctx.createGain();
                gain.connect(ctx.destination);
            }
            return true;
        } catch (e) { return false; }
    }
    function router(v) {
        if (!v || !memeOrigine(v) || !assurerCtx()) return false;
        try {
            if (ctx.state === 'suspended') ctx.resume();
            if (!sources.has(v)) {
                var src = ctx.createMediaElementSource(v);
                src.connect(gain);
                sources.set(v, src);
            }
            return true;
        } catch (e) { return false; }
    }
    function reveillerAudio() { assurerCtx(); try { if (ctx && ctx.state === 'suspended') ctx.resume(); } catch (e) { } }
    ['pointerup', 'touchend', 'click', 'keydown'].forEach(function (t) { document.addEventListener(t, reveillerAudio, true); });

    function appliquer(v) {
        if (!v) return;
        try {
            if (sources.has(v)) { v.volume = 1; if (gain) gain.gain.value = niveau / 100; }
            else v.volume = Math.min(1, niveau / 100);
        } catch (e) { }
    }
    function voulerSon(v) {
        try {
            if (niveau > 0 && typeof reelPrefs !== 'undefined' && !reelPrefs.sound) {
                reelPrefs.sound = true;
                if (typeof saveReelPrefs === 'function') saveReelPrefs();
            }
            if (niveau > 0 && v && v.muted) v.muted = false;
            if (typeof reelRefreshSoundUI === 'function') reelRefreshSoundUI();
        } catch (e) { }
    }
    function fixer(n) {
        n = Math.max(0, Math.min(MAX, Math.round(n)));
        var v = videoActive();
        if (n > 100 && (!v || !router(v))) { n = 100; toast('Boost indisponible pour cette vidéo'); }
        var avant = niveau;
        niveau = n;
        if (gain && gain.gain) { try { gain.gain.value = niveau / 100; } catch (e) { } }
        appliquer(v);
        voulerSon(v);
        try { localStorage.setItem(CLE, String(Math.min(100, niveau))); } catch (e) { }
        if (navigator.vibrate && ((avant < 100 && niveau >= 100) || (avant > 100 && niveau <= 100))) { try { navigator.vibrate(8); } catch (e) { } }
    }
    document.addEventListener('play', function (e) {
        var v = e.target;
        if (!v || v.tagName !== 'VIDEO' || !v.closest || !v.closest('#reels-container')) return;
        if (niveau > 100) router(v);
        appliquer(v);
        sonderBluetooth();
    }, true);

    /* ---- Affichage (aucune interaction : il apparaît, puis disparaît) ---- */
    var hud = null, minuteur = null, btNom = null;
    function injecterStyle() {
        if (document.getElementById('fn-vol-style')) return;
        var st = document.createElement('style');
        st.id = 'fn-vol-style';
        st.textContent =
            '#fn-vol-hud{position:fixed;left:50%;top:calc(env(safe-area-inset-top,0px) + 64px);z-index:60;width:min(86vw,330px);box-sizing:border-box;' +
            'display:flex;align-items:center;gap:14px;padding:12px 16px;border-radius:26px;color:#fff;pointer-events:none;' +
            'font-family:system-ui,-apple-system,sans-serif;--c:#1877f2;--p:33.3%;' +
            'background:rgba(22,22,26,.78);-webkit-backdrop-filter:blur(22px) saturate(1.4);backdrop-filter:blur(22px) saturate(1.4);' +
            'border:1px solid rgba(255,255,255,.09);box-shadow:0 12px 34px rgba(0,0,0,.45),0 0 26px -8px var(--c);' +
            'opacity:0;transform:translate(-50%,-14px) scale(.96);transition:opacity .22s ease,transform .32s cubic-bezier(.2,.9,.3,1.2),box-shadow .3s ease;}' +
            '#fn-vol-hud.show{opacity:1;transform:translate(-50%,0) scale(1);}' +
            '#fn-vol-hud[data-zone="2"]{--c:#ff9800;}#fn-vol-hud[data-zone="3"]{--c:#f44336;}' +
            '#fn-vol-hud .fn-vh-ic{flex:none;width:44px;height:44px;border-radius:50%;display:flex;align-items:center;justify-content:center;' +
            'background:rgba(255,255,255,.12);color:var(--c);font-size:19px;transition:color .25s ease;}' +
            '@supports (background:color-mix(in srgb,red 20%,transparent)){#fn-vol-hud .fn-vh-ic{background:color-mix(in srgb,var(--c) 22%,transparent);}}' +
            '#fn-vol-hud .fn-vh-mid{flex:1;min-width:0;}' +
            '#fn-vol-hud .fn-vh-top{display:flex;align-items:center;justify-content:space-between;min-height:16px;margin-bottom:7px;gap:8px;}' +
            '#fn-vol-hud .fn-vh-tag{display:none;font-size:10px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;padding:3px 8px;border-radius:10px;background:var(--c);color:#fff;}' +
            '#fn-vol-hud[data-zone="2"] .fn-vh-tag,#fn-vol-hud[data-zone="3"] .fn-vh-tag{display:inline-block;}' +
            '#fn-vol-hud .fn-vh-bt{display:none;align-items:center;gap:5px;font-size:11px;font-weight:600;color:#8fc2ff;margin-left:auto;min-width:0;}' +
            '#fn-vol-hud .fn-vh-bt.show{display:inline-flex;}' +
            '#fn-vol-hud .fn-vh-bt b{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:120px;}' +
            '#fn-vol-hud .fn-vh-track{position:relative;height:9px;border-radius:5px;background:rgba(255,255,255,.16);overflow:hidden;}' +
            '#fn-vol-hud .fn-vh-fill{height:100%;width:var(--p);border-radius:5px;transition:width .12s ease-out;' +
            'background-image:linear-gradient(90deg,#1877f2 0%,#1877f2 30%,#ff9800 55%,#ff9800 62%,#f44336 100%);background-repeat:no-repeat;background-size:300% 100%;}' +
            '#fn-vol-hud .fn-vh-notch{position:absolute;top:0;bottom:0;left:33.33%;width:2px;background:rgba(255,255,255,.55);}' +
            '#fn-vol-hud .fn-vh-num{flex:none;min-width:68px;text-align:right;font-variant-numeric:tabular-nums;line-height:1;}' +
            '#fn-vol-hud .fn-vh-num b{font-size:30px;font-weight:800;display:inline-block;}' +
            '#fn-vol-hud .fn-vh-num small{font-size:13px;font-weight:700;opacity:.8;margin-left:1px;}' +
            '#fn-vol-hud .fn-vh-num b.pop{animation:fnVhPop .18s ease-out;}' +
            '@keyframes fnVhPop{0%{transform:scale(1)}40%{transform:scale(1.14)}100%{transform:scale(1)}}' +
            '@media (prefers-reduced-motion:reduce){#fn-vol-hud,#fn-vol-hud .fn-vh-fill{transition:none;}#fn-vol-hud .fn-vh-num b.pop{animation:none;}}';
        document.head.appendChild(st);
    }
    function construire() {
        if (hud || !document.body) return;
        injecterStyle();
        hud = document.createElement('div');
        hud.id = 'fn-vol-hud';
        hud.setAttribute('role', 'status');
        hud.setAttribute('aria-live', 'polite');
        hud.setAttribute('data-zone', '1');
        hud.innerHTML =
            '<div class="fn-vh-ic"><i class="fa-solid fa-volume-high"></i></div>' +
            '<div class="fn-vh-mid"><div class="fn-vh-top"><span class="fn-vh-tag">Boost</span>' +
            '<span class="fn-vh-bt"><i class="fa-brands fa-bluetooth-b"></i><b></b></span></div>' +
            '<div class="fn-vh-track"><div class="fn-vh-fill"></div><span class="fn-vh-notch"></span></div></div>' +
            '<div class="fn-vh-num"><b>100</b><small>%</small></div>';
        document.body.appendChild(hud);
        majInterface();
    }
    function majInterface() {
        if (!hud) return;
        var zone = niveau > 200 ? 3 : (niveau > 100 ? 2 : 1);
        hud.setAttribute('data-zone', String(zone));
        hud.style.setProperty('--p', (niveau / MAX * 100) + '%');
        var fill = hud.querySelector('.fn-vh-fill');
        if (fill) fill.style.backgroundSize = (niveau > 0 ? (MAX / niveau * 100) : 100) + '% 100%';
        var tag = hud.querySelector('.fn-vh-tag');
        if (tag) tag.textContent = zone === 3 ? 'Très fort' : 'Boost';
        var num = hud.querySelector('.fn-vh-num b');
        if (num) {
            num.textContent = String(niveau);
            num.classList.remove('pop'); void num.offsetWidth; num.classList.add('pop');
        }
        var ic = hud.querySelector('.fn-vh-ic i');
        if (ic) ic.className = 'fa-solid ' + (niveau === 0 ? 'fa-volume-xmark' : (niveau < 50 ? 'fa-volume-low' : 'fa-volume-high'));
        var bt = hud.querySelector('.fn-vh-bt');
        if (bt) {
            bt.classList.toggle('show', !!btNom);
            var b = bt.querySelector('b');
            if (b) b.textContent = btNom ? btNom.replace(/^default\s*-\s*/i, '') : '';
        }
    }
    function afficher() {
        construire();
        majInterface();
        hud.classList.add('show');
        clearTimeout(minuteur);
        minuteur = setTimeout(function () { if (hud) hud.classList.remove('show'); }, 2000);
    }
    function monter(delta) {
        fixer(niveau + delta);
        afficher();
    }
    window.fnReelsVolume = {
        monter: monter,
        fixer: function (n) { fixer(n); afficher(); },
        niveau: function () { return niveau; }
    };

    /* ---- Déclencheurs ---- */
    document.addEventListener('volumeupbutton', function () { monter(PAS); }, false);      /* plugins Cordova / Capacitor */
    document.addEventListener('volumedownbutton', function () { monter(-PAS); }, false);
    document.addEventListener('fn-volume-key', function (e) {                              /* application native : dispatchEvent(new CustomEvent('fn-volume-key', {detail:{direction:'up'}})) */
        var d = e && e.detail && e.detail.direction;
        if (d === 'up') monter(PAS); else if (d === 'down') monter(-PAS);
    }, false);
    document.addEventListener('keydown', function (e) {
        var t = e.target;
        if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
        var k = e.key, c = e.keyCode, sens = 0;
        if (k === 'AudioVolumeUp' || c === 175 || c === 24 || k === '+' || k === '=') sens = 1;
        else if (k === 'AudioVolumeDown' || c === 174 || c === 25 || k === '-' || k === '_') sens = -1;
        if (!sens) return;
        monter(sens * PAS);
    });

    /* ---- Bluetooth (détection au mieux : dépend de ce que le navigateur révèle) ---- */
    function sonderBluetooth() {
        try {
            if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return;
            navigator.mediaDevices.enumerateDevices().then(function (liste) {
                var trouve = null;
                liste.forEach(function (d) {
                    if (d.kind === 'audiooutput' && /bluetooth|airpods|buds|hands-?free/i.test(d.label || '')) trouve = d.label;
                });
                if (trouve && trouve !== btNom) toast('Bluetooth connecté : ' + trouve.replace(/^default\s*-\s*/i, ''));
                else if (!trouve && btNom) toast('Bluetooth déconnecté');
                btNom = trouve;
                majInterface();
            }).catch(function () { });
        } catch (e) { }
    }
    try { if (navigator.mediaDevices && navigator.mediaDevices.addEventListener) navigator.mediaDevices.addEventListener('devicechange', sonderBluetooth); } catch (e) { }

    function demarrer() { try { construire(); sonderBluetooth(); } catch (e) { } }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', demarrer);
    else demarrer();
})();