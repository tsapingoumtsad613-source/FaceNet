/* ============================================================================
   FaceNet — « Secouer pour signaler un problème »
   Fichier autonome : aucun autre fichier à modifier à part l'inclusion du script
   dans feed.html. Il injecte lui-même son CSS et son HTML (préfixe fnsr-).

   - Détection de secousse (devicemotion) uniquement sur les pages qui chargent ce script.
   - Réglage « Secouer l'appareil pour signaler un problème » mémorisé sur l'appareil.
   - Parcours : accueil → catégorie → détails (+ captures, + infos techniques) → confirmation.
   - Envoi vers POST /api/signalement-probleme (voir signalements.py).
   - Tout élément portant l'attribut  data-signaler-probleme  ouvre aussi l'écran
     (utile pour un lien dans un menu, et indispensable sur iPhone pour l'autorisation).
   - API : window.FaceNetSignalement.ouvrir()
   ============================================================================ */
(function () {
    'use strict';
    if (window.FaceNetSignalement) return;

    /* ───────────── Configuration ───────────── */
    var CFG = {
        endpoint: '/api/signalement-probleme',
        cleReglage: 'facenet_secousse_signalement',   // '1' (défaut) / '0'
        seuilSecousse: 26,        // somme des variations d'accélération (m/s²) pour compter une secousse
        secoussesRequises: 3,     // nombre de secousses dans la fenêtre
        fenetreMs: 1500,
        ecartMinMs: 140,          // deux secousses comptées doivent être espacées d'au moins 140 ms
        pauseApresMs: 5000,       // pas de réouverture juste après une ouverture
        maxCaptures: 3,
        maxMo: 5,
        descMin: 10,
        descMax: 2000,
        timeoutMs: 45000
    };

    var CATEGORIES = [
        { id: 'bug',           e: '🐞', t: 'Un bug ou un plantage',           s: 'L’application se ferme, se bloque ou affiche une erreur', ph: 'Que s’est-il passé ? Sur quel écran, après quelle action ?' },
        { id: 'lenteur',       e: '🐢', t: 'Lenteur ou chargement',            s: 'Les pages, photos ou vidéos mettent trop de temps', ph: 'Quelle page ou quelle action est lente ?' },
        { id: 'connexion',     e: '🔐', t: 'Connexion ou compte',              s: 'Mot de passe, code de vérification, accès au compte', ph: 'Quel message vois-tu ? À quelle étape es-tu bloqué(e) ?' },
        { id: 'notifications', e: '🔔', t: 'Notifications',                    s: 'Notifications absentes, en double ou en retard', ph: 'Quelles notifications posent problème ?' },
        { id: 'messages',      e: '💬', t: 'Messages et appels',               s: 'Envoi, réception, appels audio ou vidéo', ph: 'Décris le problème rencontré avec les messages ou les appels.' },
        { id: 'publication',   e: '📸', t: 'Publications, stories et photos',  s: 'Publier, envoyer ou afficher du contenu', ph: 'Que se passe-t-il quand tu publies ou affiches du contenu ?' },
        { id: 'paiement',      e: '💳', t: 'Paiement, boost ou badge',         s: 'Paiement refusé, boost, vérification d’identité', ph: 'Décris le problème (sans écrire de code secret ni de numéro de carte).' },
        { id: 'spam',          e: '🚫', t: 'Spam ou faux compte',              s: 'Messages indésirables, comptes qui se font passer pour autre chose', ph: 'Explique ce que fait ce compte ou ce contenu.', abus: true },
        { id: 'abus',          e: '⚠️', t: 'Contenu abusif ou harcèlement',    s: 'Insultes, menaces, contenu choquant ou inapproprié', ph: 'Explique ce qui s’est passé.', abus: true },
        { id: 'arnaque',       e: '🕵️', t: 'Arnaque ou usurpation d’identité', s: 'Demande d’argent, faux profil, vol d’identité', ph: 'Explique comment on a essayé de te tromper.', abus: true },
        { id: 'piratage',      e: '🛡️', t: 'Compte piraté ou en danger',       s: 'Activité que tu ne reconnais pas sur ton compte', ph: 'Quelle activité suspecte as-tu remarquée ?', abus: true },
        { id: 'suggestion',    e: '💡', t: 'Suggestion d’amélioration',        s: 'Une idée pour améliorer FaceNet', ph: 'Quelle amélioration proposes-tu ?' },
        { id: 'autre',         e: '📝', t: 'Autre problème',                   s: 'Tout ce qui ne rentre pas dans les catégories ci-dessus', ph: 'Décris le problème le plus précisément possible.' }
    ];

    var ILLU = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 220 210" width="190" height="181" role="img" aria-label="Main qui secoue un téléphone"> <ellipse cx="110" cy="198" rx="62" ry="7" fill="#0b1b3a" opacity=".10"/> <g fill="none" stroke="#1877f2" stroke-width="5" stroke-linecap="round" opacity=".55"> <path d="M30 70 q-12 22 0 44"/><path d="M16 60 q-20 32 0 64" opacity=".5"/> <path d="M190 70 q12 22 0 44"/><path d="M204 60 q20 32 0 64" opacity=".5"/> </g> <g transform="rotate(-12 110 110)"> <!-- avant-bras + manche --> <path d="M80 150 L140 150 L150 212 L70 212 Z" fill="#7a4a2c"/> <path d="M72 176 L148 176 L154 214 L66 214 Z" fill="#1877f2"/> <rect x="66" y="170" width="88" height="10" rx="5" fill="#7c3aed"/> <!-- paume derrière le téléphone --> <rect x="64" y="96" width="92" height="84" rx="28" fill="#a86a40"/> <!-- pouce (dépasse à gauche) --> <rect x="54" y="98" width="34" height="17" rx="8.5" fill="#c07f52" stroke="#8a5430" stroke-width="1.6" transform="rotate(-22 70 106)"/> <!-- téléphone (dos) --> <rect x="72" y="20" width="76" height="140" rx="15" fill="#20242b"/> <rect x="75" y="23" width="70" height="134" rx="12" fill="none" stroke="#3a4049" stroke-width="1.5"/> <rect x="81" y="30" width="32" height="32" rx="10" fill="#2e343d"/> <circle cx="91" cy="40" r="6.5" fill="#0c0e12" stroke="#4b79c9" stroke-width="2"/> <circle cx="91" cy="40" r="2" fill="#7fb2ff"/> <circle cx="103" cy="52" r="6.5" fill="#0c0e12" stroke="#4b79c9" stroke-width="2"/> <circle cx="103" cy="52" r="2" fill="#7fb2ff"/> <circle cx="104" cy="38" r="2.4" fill="#ffd45c"/> <path d="M118 24 L144 24 L144 60 Z" fill="#fff" opacity=".05"/> <text x="110" y="104" text-anchor="middle" font-family="Arial,Helvetica,sans-serif" font-size="12" font-weight="700" letter-spacing="1.4" fill="#aeb6c2">Infinix</text> <!-- doigts à droite --> <g fill="#c07f52" stroke="#8a5430" stroke-width="1.6"> <rect x="132" y="84" width="30" height="15" rx="7.5"/> <rect x="132" y="102" width="32" height="15" rx="7.5"/> <rect x="132" y="120" width="30" height="15" rx="7.5"/> <rect x="132" y="138" width="26" height="14" rx="7"/> </g> </g> </svg>`;

    /* ───────────── Utilitaires ───────────── */
    function $(sel, ctx) { return (ctx || document).querySelector(sel); }
    function $$(sel, ctx) { return Array.prototype.slice.call((ctx || document).querySelectorAll(sel)); }
    function echapper(s) {
        return String(s).replace(/[&<>"']/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
        });
    }
    function lireReglage() {
        try { return window.localStorage.getItem(CFG.cleReglage) !== '0'; } catch (e) { return true; }
    }
    function ecrireReglage(actif) {
        try { window.localStorage.setItem(CFG.cleReglage, actif ? '1' : '0'); } catch (e) {}
    }
    function jetonCsrf() {
        var m = $('meta[name="csrf-token"]') || $('meta[name="csrf_token"]');
        if (m && m.content) return m.content;
        var i = $('input[name="csrf_token"]');
        return i ? i.value : '';
    }
    function categorie(id) {
        for (var i = 0; i < CATEGORIES.length; i++) if (CATEGORIES[i].id === id) return CATEGORIES[i];
        return null;
    }

    /* ───────────── Erreurs JS récentes (jointes aux infos techniques) ───────────── */
    var erreursRecentes = [];
    function noterErreur(msg) {
        erreursRecentes.push({ t: new Date().toISOString(), m: String(msg || '').slice(0, 300) });
        if (erreursRecentes.length > 15) erreursRecentes.shift();
    }
    window.addEventListener('error', function (e) {
        noterErreur((e && e.message ? e.message : 'Erreur') + (e && e.filename ? ' @ ' + String(e.filename).split('/').pop() + ':' + (e.lineno || 0) : ''));
    });
    window.addEventListener('unhandledrejection', function (e) {
        var r = e && e.reason;
        noterErreur('Promesse rejetée : ' + (r && r.message ? r.message : r));
    });

    function collecterDiagnostic() {
        var c = navigator.connection || navigator.mozConnection || navigator.webkitConnection || null;
        var fuseau = '';
        try { fuseau = Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch (e) {}
        return {
            page: location.pathname + location.search,
            titre: document.title,
            appareil: navigator.userAgent,
            langue: navigator.language,
            ecran: screen.width + 'x' + screen.height,
            fenetre: window.innerWidth + 'x' + window.innerHeight,
            densite: window.devicePixelRatio || 1,
            fuseau: fuseau,
            theme: document.documentElement.getAttribute('data-fn-theme') || 'clair',
            en_ligne: navigator.onLine,
            connexion: c ? { type: c.effectiveType || '', debit_mbps: c.downlink || null, economie: !!c.saveData } : null,
            ouverture: etat.source,
            erreurs_js: erreursRecentes.slice(-10)
        };
    }

    /* ───────────── État ───────────── */
    var etat;
    function etatInitial() {
        return { source: 'secousse', cat: null, desc: '', cible: '', diag: true, fichiers: [], envoi: false, etape: 'accueil', filtreAbus: false };
    }
    etat = etatInitial();
    var racine = null, ouvert = false, dernierOuvert = 0, permissionDemandee = false, permissionRefusee = false;

    /* ───────────── CSS ───────────── */
    function injecterCss() {
        if (document.getElementById('fnsr-style')) return;
        var st = document.createElement('style');
        st.id = 'fnsr-style';
        st.textContent = `
#fnsr-root{--fnsr-bg:#fff;--fnsr-tx:#14171c;--fnsr-mu:#5f6673;--fnsr-li:#e6e9ef;--fnsr-sf:#f3f5f9;--fnsr-bl:#1877f2;--fnsr-vi:#7c3aed;--fnsr-er:#d93025;--fnsr-ok:#1e9e5a;
 position:fixed;inset:0;z-index:100100;font-family:inherit;color:var(--fnsr-tx);-webkit-tap-highlight-color:transparent}
html[data-fn-theme="dark"] #fnsr-root{--fnsr-bg:#242526;--fnsr-tx:#e4e6eb;--fnsr-mu:#a8abb2;--fnsr-li:#3e4042;--fnsr-sf:#3a3b3c}
#fnsr-root[hidden]{display:none}
#fnsr-root *{box-sizing:border-box}
html.fnsr-lock,html.fnsr-lock body{overflow:hidden!important}
.fnsr-backdrop{position:absolute;inset:0;background:rgba(10,14,25,.55);opacity:0;transition:opacity .25s ease}
#fnsr-root.fnsr-on .fnsr-backdrop{opacity:1}

.fnsr-sheet{position:absolute;left:0;right:0;bottom:0;max-width:560px;margin:0 auto;background:var(--fnsr-bg);border-radius:26px 26px 0 0;
 padding:10px 20px calc(18px + env(safe-area-inset-bottom,0px));transform:translateY(100%);transition:transform .32s cubic-bezier(.2,.9,.3,1);
 box-shadow:0 -10px 40px rgba(0,0,0,.25);max-height:92vh;overflow-y:auto;-webkit-overflow-scrolling:touch}
#fnsr-root.fnsr-on .fnsr-sheet{transform:translateY(0)}
.fnsr-grab{width:42px;height:5px;border-radius:3px;background:var(--fnsr-li);margin:0 auto 6px}
.fnsr-x{position:absolute;top:12px;right:14px;width:36px;height:36px;border:0;border-radius:50%;background:var(--fnsr-sf);color:var(--fnsr-tx);font-size:18px;cursor:pointer;display:flex;align-items:center;justify-content:center}
.fnsr-hero{display:flex;justify-content:center;margin:2px 0 0;background:radial-gradient(120px 90px at 50% 55%,rgba(24,119,242,.14),transparent 70%)}
.fnsr-illu{display:inline-block;animation:fnsrShake 1.5s ease-in-out infinite;transform-origin:50% 80%}
.fnsr-illu svg{display:block;max-width:100%;height:auto}
@keyframes fnsrShake{0%,100%{transform:rotate(0)}12%{transform:rotate(-7deg) translateX(-3px)}28%{transform:rotate(7deg) translateX(3px)}44%{transform:rotate(-5deg) translateX(-2px)}60%{transform:rotate(4deg) translateX(2px)}78%{transform:rotate(0)}}
.fnsr-h1{margin:6px 0 6px;text-align:center;font-size:21px;font-weight:800;letter-spacing:-.2px}
.fnsr-p{margin:0 0 16px;text-align:center;color:var(--fnsr-mu);font-size:15px;line-height:1.45}
.fnsr-btn{display:flex;align-items:center;justify-content:center;gap:8px;width:100%;min-height:50px;border:0;border-radius:14px;font:inherit;font-size:16px;font-weight:800;cursor:pointer;transition:transform .12s ease,opacity .2s ease,filter .2s ease}
.fnsr-btn:active{transform:scale(.98)}
.fnsr-btn[disabled]{opacity:.45;cursor:not-allowed}
.fnsr-btn-main{color:#fff;background:linear-gradient(135deg,var(--fnsr-bl),var(--fnsr-vi));box-shadow:0 6px 16px rgba(24,119,242,.35)}
.fnsr-btn-soft{color:var(--fnsr-tx);background:var(--fnsr-sf);margin-top:10px}
.fnsr-link{display:block;width:100%;margin:12px 0 4px;padding:8px;border:0;background:none;color:var(--fnsr-bl);font:inherit;font-size:14.5px;font-weight:700;text-align:center;cursor:pointer}
.fnsr-row{display:flex;align-items:center;gap:14px;padding:14px 2px;border-top:1px solid var(--fnsr-li);margin-top:6px}
.fnsr-row-t{flex:1;font-size:15.5px;font-weight:700;line-height:1.3}
.fnsr-row-s{display:block;margin-top:3px;font-size:12.5px;font-weight:500;color:var(--fnsr-mu)}
.fnsr-sw{position:relative;flex:0 0 auto;width:52px;height:32px}
.fnsr-sw input{position:absolute;inset:0;width:100%;height:100%;opacity:0;margin:0;cursor:pointer;z-index:2}
.fnsr-sw i{position:absolute;inset:0;border-radius:16px;background:#c5cad3;transition:background .2s}
.fnsr-sw i:after{content:'';position:absolute;top:3px;left:3px;width:26px;height:26px;border-radius:50%;background:#fff;box-shadow:0 1px 3px rgba(0,0,0,.3);transition:transform .2s}
.fnsr-sw input:checked+i{background:var(--fnsr-bl)}
.fnsr-sw input:checked+i:after{transform:translateX(20px)}
.fnsr-note{margin:0;padding:10px 12px;border-radius:12px;background:var(--fnsr-sf);color:var(--fnsr-mu);font-size:13px;line-height:1.4}
.fnsr-note[hidden]{display:none}

.fnsr-page{position:absolute;inset:0;background:var(--fnsr-bg);display:flex;flex-direction:column;transform:translateX(100%);transition:transform .28s ease;max-width:560px;margin:0 auto}
.fnsr-page[hidden]{display:none}
.fnsr-page.fnsr-in{transform:translateX(0)}
.fnsr-bar{flex:0 0 auto;display:flex;align-items:center;gap:6px;padding:calc(8px + env(safe-area-inset-top,0px)) 10px 8px;border-bottom:1px solid var(--fnsr-li)}
.fnsr-back{width:42px;height:42px;border:0;border-radius:50%;background:none;color:var(--fnsr-tx);font-size:22px;cursor:pointer}
.fnsr-back:active{background:var(--fnsr-sf)}
.fnsr-bar-t{flex:1;text-align:center;font-size:17px;font-weight:800;margin-right:42px}
.fnsr-body{flex:1;overflow-y:auto;-webkit-overflow-scrolling:touch;padding:16px 16px 24px}
.fnsr-foot{flex:0 0 auto;padding:10px 16px calc(12px + env(safe-area-inset-bottom,0px));border-top:1px solid var(--fnsr-li);background:var(--fnsr-bg)}
.fnsr-intro{margin:0 0 14px;color:var(--fnsr-mu);font-size:14.5px;line-height:1.45}
.fnsr-cat{display:flex;align-items:center;gap:13px;width:100%;padding:13px 12px;margin-bottom:8px;border:1px solid var(--fnsr-li);border-radius:16px;background:var(--fnsr-bg);color:var(--fnsr-tx);font:inherit;text-align:left;cursor:pointer;transition:background .15s,border-color .15s}
.fnsr-cat:active{background:var(--fnsr-sf);border-color:var(--fnsr-bl)}
.fnsr-cat-e{flex:0 0 auto;width:42px;height:42px;border-radius:13px;background:var(--fnsr-sf);display:flex;align-items:center;justify-content:center;font-size:22px}
.fnsr-cat-t{display:block;font-size:15.5px;font-weight:800}
.fnsr-cat-s{display:block;margin-top:2px;font-size:12.8px;color:var(--fnsr-mu);line-height:1.35}
.fnsr-cat-c{margin-left:auto;color:var(--fnsr-mu);font-size:18px}
.fnsr-chip{display:flex;align-items:center;gap:10px;padding:10px 12px;margin-bottom:14px;border-radius:14px;background:var(--fnsr-sf);font-weight:800;font-size:14.5px}
.fnsr-chip button{margin-left:auto;border:0;background:none;color:var(--fnsr-bl);font:inherit;font-size:13.5px;font-weight:800;cursor:pointer}
.fnsr-lab{display:block;margin:14px 0 6px;font-size:14px;font-weight:800}
.fnsr-opt{font-weight:500;color:var(--fnsr-mu)}
.fnsr-in,.fnsr-ta{width:100%;padding:12px 14px;border:1.5px solid var(--fnsr-li);border-radius:14px;background:var(--fnsr-bg);color:var(--fnsr-tx);font:inherit;font-size:16px;outline:none;transition:border-color .15s,box-shadow .15s}
.fnsr-ta{min-height:130px;resize:vertical;line-height:1.45}
.fnsr-in:focus,.fnsr-ta:focus{border-color:var(--fnsr-bl);box-shadow:0 0 0 3px rgba(24,119,242,.18)}
.fnsr-count{margin-top:4px;text-align:right;font-size:12px;color:var(--fnsr-mu)}
.fnsr-err{margin:10px 0 0;padding:10px 12px;border-radius:12px;background:rgba(217,48,37,.10);color:var(--fnsr-er);font-size:13.5px;font-weight:700;line-height:1.35}
.fnsr-err[hidden]{display:none}
.fnsr-shots{display:flex;flex-wrap:wrap;gap:10px}
.fnsr-shot{position:relative;width:84px;height:84px;border-radius:14px;overflow:hidden;background:var(--fnsr-sf)}
.fnsr-shot img{width:100%;height:100%;object-fit:cover;display:block}
.fnsr-shot button{position:absolute;top:4px;right:4px;width:24px;height:24px;border:0;border-radius:50%;background:rgba(0,0,0,.65);color:#fff;font-size:13px;cursor:pointer;line-height:1}
.fnsr-add{width:84px;height:84px;border:2px dashed var(--fnsr-li);border-radius:14px;background:none;color:var(--fnsr-bl);font:inherit;font-size:12px;font-weight:800;cursor:pointer;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px}
.fnsr-add b{font-size:26px;line-height:1}
.fnsr-diag{margin-top:16px;padding:12px;border:1px solid var(--fnsr-li);border-radius:14px}
.fnsr-diag .fnsr-row{border:0;margin:0;padding:0}
.fnsr-diag details{margin-top:10px;font-size:12.5px;color:var(--fnsr-mu)}
.fnsr-diag summary{cursor:pointer;font-weight:700;color:var(--fnsr-bl)}
.fnsr-diag pre{margin:8px 0 0;max-height:150px;overflow:auto;white-space:pre-wrap;word-break:break-word;font-size:11.5px;background:var(--fnsr-sf);padding:8px;border-radius:10px;color:var(--fnsr-tx)}
.fnsr-spin{width:18px;height:18px;border-radius:50%;border:3px solid rgba(255,255,255,.4);border-top-color:#fff;animation:fnsrSpin .8s linear infinite}
@keyframes fnsrSpin{to{transform:rotate(360deg)}}
.fnsr-done{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:24px}
.fnsr-ok{width:84px;height:84px;border-radius:50%;background:rgba(30,158,90,.14);color:var(--fnsr-ok);display:flex;align-items:center;justify-content:center;font-size:44px;margin-bottom:14px;animation:fnsrPop .45s cubic-bezier(.2,1.4,.4,1)}
@keyframes fnsrPop{from{transform:scale(.4);opacity:0}to{transform:scale(1);opacity:1}}
.fnsr-ref{display:inline-block;margin:6px 0 18px;padding:8px 14px;border-radius:12px;background:var(--fnsr-sf);font-weight:800;letter-spacing:.5px;font-size:15px}
@media (prefers-reduced-motion:reduce){.fnsr-illu,.fnsr-ok{animation:none}.fnsr-sheet,.fnsr-page,.fnsr-backdrop{transition:none}}
`;
        document.head.appendChild(st);
    }

    /* ───────────── HTML ───────────── */
    function construire() {
        if (racine) return;
        injecterCss();
        racine = document.createElement('div');
        racine.id = 'fnsr-root';
        racine.hidden = true;
        racine.setAttribute('role', 'dialog');
        racine.setAttribute('aria-modal', 'true');
        racine.setAttribute('aria-label', 'Signaler un problème');

        var liste = CATEGORIES.map(function (c) {
            return '<button type="button" class="fnsr-cat" data-fnsr="cat" data-cat="' + c.id + '"' + (c.abus ? ' data-abus="1"' : '') + '>' +
                '<span class="fnsr-cat-e">' + c.e + '</span>' +
                '<span><span class="fnsr-cat-t">' + echapper(c.t) + '</span><span class="fnsr-cat-s">' + echapper(c.s) + '</span></span>' +
                '<span class="fnsr-cat-c">›</span></button>';
        }).join('');

        racine.innerHTML =
            '<div class="fnsr-backdrop" data-fnsr="fermer"></div>' +

            /* Accueil (feuille du bas) */
            '<section class="fnsr-sheet" data-etape="accueil">' +
                '<div class="fnsr-grab"></div>' +
                '<button type="button" class="fnsr-x" data-fnsr="fermer" aria-label="Fermer">✕</button>' +
                '<div class="fnsr-hero"><div class="fnsr-illu">' + ILLU + '</div></div>' +
                '<h2 class="fnsr-h1">Un problème avec FaceNet ?</h2>' +
                '<p class="fnsr-p">Secouez votre téléphone à tout moment pour nous signaler un bug, un spam ou tout autre souci. Notre équipe lit chaque signalement.</p>' +
                '<button type="button" class="fnsr-btn fnsr-btn-main" data-fnsr="demarrer">Signaler un problème</button>' +
                '<button type="button" class="fnsr-link" data-fnsr="abus">Signaler un spam, un abus ou un compte piraté</button>' +
                '<div class="fnsr-row"><span class="fnsr-row-t">Secouer l’appareil pour signaler un problème<span class="fnsr-row-s" id="fnsr-reglage-info"></span></span>' +
                    '<label class="fnsr-sw"><input type="checkbox" id="fnsr-reglage" aria-label="Activer la détection de secousse"><i></i></label></div>' +
                '<p class="fnsr-note" id="fnsr-note-mouvement" hidden></p>' +
            '</section>' +

            /* Catégories */
            '<section class="fnsr-page" data-etape="categorie" hidden>' +
                '<div class="fnsr-bar"><button type="button" class="fnsr-back" data-fnsr="retour" aria-label="Retour">←</button><div class="fnsr-bar-t" id="fnsr-titre-cat">Que se passe-t-il ?</div></div>' +
                '<div class="fnsr-body"><p class="fnsr-intro" id="fnsr-intro-cat">Choisissez la catégorie qui correspond le mieux à votre problème.</p>' + liste + '</div>' +
            '</section>' +

            /* Détails */
            '<section class="fnsr-page" data-etape="details" hidden>' +
                '<div class="fnsr-bar"><button type="button" class="fnsr-back" data-fnsr="retour" aria-label="Retour">←</button><div class="fnsr-bar-t">Décrire le problème</div></div>' +
                '<div class="fnsr-body">' +
                    '<div class="fnsr-chip"><span id="fnsr-chip-e"></span><span id="fnsr-chip-t"></span><button type="button" data-fnsr="retour">Changer</button></div>' +
                    '<div id="fnsr-bloc-cible" hidden><label class="fnsr-lab" for="fnsr-cible">Profil ou lien concerné <span class="fnsr-opt">(facultatif)</span></label>' +
                        '<input class="fnsr-in" id="fnsr-cible" type="text" maxlength="300" autocomplete="off" placeholder="@pseudo ou lien de la publication"></div>' +
                    '<label class="fnsr-lab" for="fnsr-desc">Décrivez le problème</label>' +
                    '<textarea class="fnsr-ta" id="fnsr-desc" maxlength="' + CFG.descMax + '"></textarea>' +
                    '<div class="fnsr-count"><span id="fnsr-nb">0</span>/' + CFG.descMax + '</div>' +
                    '<span class="fnsr-lab">Captures d’écran <span class="fnsr-opt">(facultatif, ' + CFG.maxCaptures + ' max)</span></span>' +
                    '<div class="fnsr-shots" id="fnsr-shots"></div>' +
                    '<input type="file" id="fnsr-file" accept="image/png,image/jpeg,image/webp" multiple hidden>' +
                    '<div class="fnsr-diag"><div class="fnsr-row"><span class="fnsr-row-t">Inclure les informations techniques<span class="fnsr-row-s">Appareil, navigateur, page ouverte et erreurs récentes, uniquement pour comprendre ce problème.</span></span>' +
                        '<label class="fnsr-sw"><input type="checkbox" id="fnsr-diag" checked aria-label="Inclure les informations techniques"><i></i></label></div>' +
                        '<details><summary>Voir ce qui sera envoyé</summary><pre id="fnsr-diag-apercu"></pre></details></div>' +
                    '<p class="fnsr-err" id="fnsr-erreur" role="alert" hidden></p>' +
                '</div>' +
                '<div class="fnsr-foot"><button type="button" class="fnsr-btn fnsr-btn-main" id="fnsr-envoyer" data-fnsr="envoyer" disabled>Envoyer le signalement</button>' +
                    '<button type="button" class="fnsr-btn fnsr-btn-soft" data-fnsr="fermer">Annuler</button></div>' +
            '</section>' +

            /* Confirmation */
            '<section class="fnsr-page" data-etape="merci" hidden>' +
                '<div class="fnsr-done"><div class="fnsr-ok">✓</div>' +
                    '<h2 class="fnsr-h1">Merci, c’est envoyé !</h2>' +
                    '<p class="fnsr-p">Notre équipe va examiner votre signalement. Gardez ce numéro si vous devez nous écrire à ce sujet.</p>' +
                    '<div class="fnsr-ref" id="fnsr-ref"></div>' +
                    '<button type="button" class="fnsr-btn fnsr-btn-main" data-fnsr="fermer" style="max-width:360px">Terminer</button></div>' +
            '</section>';

        document.body.appendChild(racine);

        racine.addEventListener('click', surClic);
        racine.addEventListener('change', surChangement);
        racine.addEventListener('input', surSaisie);
        document.addEventListener('keydown', function (e) {
            if (ouvert && e.key === 'Escape') fermer();
        });
    }

    /* ───────────── Navigation entre écrans ───────────── */
    function afficher(etape) {
        etat.etape = etape;
        var sheet = $('.fnsr-sheet', racine);
        if (etape === 'accueil') {
            $$('.fnsr-page', racine).forEach(function (p) { p.classList.remove('fnsr-in'); setTimeout(function () { if (etat.etape === 'accueil') p.hidden = true; }, 300); });
            sheet.style.visibility = 'visible';
            return;
        }
        var page = $('.fnsr-page[data-etape="' + etape + '"]', racine);
        $$('.fnsr-page', racine).forEach(function (p) { if (p !== page) { p.classList.remove('fnsr-in'); p.hidden = true; } });
        page.hidden = false;
        void page.offsetWidth;
        page.classList.add('fnsr-in');
        sheet.style.visibility = 'hidden';
        var corps = $('.fnsr-body', page);
        if (corps) corps.scrollTop = 0;
    }

    function ouvrirCategories(filtreAbus) {
        etat.filtreAbus = !!filtreAbus;
        $$('.fnsr-cat', racine).forEach(function (b) {
            b.hidden = etat.filtreAbus && !b.getAttribute('data-abus');
        });
        $('#fnsr-titre-cat', racine).textContent = etat.filtreAbus ? 'Signaler un abus' : 'Que se passe-t-il ?';
        $('#fnsr-intro-cat', racine).textContent = etat.filtreAbus
            ? 'Pour signaler directement une publication ou un profil, vous pouvez aussi utiliser le menu ⋯ qui se trouve à côté. Sinon, choisissez ci-dessous.'
            : 'Choisissez la catégorie qui correspond le mieux à votre problème.';
        afficher('categorie');
    }

    function choisirCategorie(id) {
        var c = categorie(id);
        if (!c) return;
        etat.cat = id;
        $('#fnsr-chip-e', racine).textContent = c.e;
        $('#fnsr-chip-t', racine).textContent = c.t;
        $('#fnsr-desc', racine).placeholder = c.ph;
        $('#fnsr-bloc-cible', racine).hidden = !c.abus;
        majApercuDiagnostic();
        majBoutonEnvoi();
        afficher('details');
    }

    function retour() {
        if (etat.etape === 'details') ouvrirCategories(etat.filtreAbus);
        else if (etat.etape === 'categorie') afficher('accueil');
        else fermer();
    }

    /* ───────────── Champs ───────────── */
    function montrerErreur(msg) {
        var e = $('#fnsr-erreur', racine);
        if (!msg) { e.hidden = true; e.textContent = ''; return; }
        e.textContent = msg;
        e.hidden = false;
        try { e.scrollIntoView({ block: 'nearest', behavior: 'smooth' }); } catch (x) {}
    }
    function majBoutonEnvoi() {
        var ok = !!etat.cat && etat.desc.trim().length >= CFG.descMin && !etat.envoi;
        $('#fnsr-envoyer', racine).disabled = !ok;
    }
    function majApercuDiagnostic() {
        var pre = $('#fnsr-diag-apercu', racine);
        try { pre.textContent = JSON.stringify(collecterDiagnostic(), null, 2); } catch (e) { pre.textContent = ''; }
    }
    function surSaisie(e) {
        if (e.target.id === 'fnsr-desc') {
            etat.desc = e.target.value;
            $('#fnsr-nb', racine).textContent = etat.desc.length;
            majBoutonEnvoi();
            montrerErreur('');
        } else if (e.target.id === 'fnsr-cible') {
            etat.cible = e.target.value;
        }
    }
    function surChangement(e) {
        var t = e.target;
        if (t.id === 'fnsr-reglage') {
            changerReglage(t.checked, t);
        } else if (t.id === 'fnsr-diag') {
            etat.diag = t.checked;
            $('#fnsr-diag-apercu', racine).parentNode.hidden = !t.checked;
        } else if (t.id === 'fnsr-file') {
            ajouterFichiers(t.files);
            t.value = '';
        }
    }

    /* ───────────── Captures d'écran ───────────── */
    var TYPES_OK = ['image/png', 'image/jpeg', 'image/webp'];
    function ajouterFichiers(liste) {
        var refus = '';
        Array.prototype.forEach.call(liste || [], function (f) {
            if (etat.fichiers.length >= CFG.maxCaptures) { refus = 'Maximum ' + CFG.maxCaptures + ' captures d’écran.'; return; }
            if (TYPES_OK.indexOf(f.type) === -1) { refus = 'Format non pris en charge (PNG, JPEG ou WebP uniquement).'; return; }
            if (f.size > CFG.maxMo * 1024 * 1024) { refus = 'Une image dépasse ' + CFG.maxMo + ' Mo.'; return; }
            etat.fichiers.push({ file: f, url: URL.createObjectURL(f) });
        });
        montrerErreur(refus);
        dessinerCaptures();
    }
    function dessinerCaptures() {
        var h = etat.fichiers.map(function (x, i) {
            return '<div class="fnsr-shot"><img src="' + x.url + '" alt="Capture ' + (i + 1) + '"><button type="button" data-fnsr="retirer" data-i="' + i + '" aria-label="Retirer la capture ' + (i + 1) + '">✕</button></div>';
        }).join('');
        if (etat.fichiers.length < CFG.maxCaptures) h += '<button type="button" class="fnsr-add" data-fnsr="ajouter"><b>+</b>Ajouter</button>';
        $('#fnsr-shots', racine).innerHTML = h;
    }
    function viderCaptures() {
        etat.fichiers.forEach(function (x) { try { URL.revokeObjectURL(x.url); } catch (e) {} });
        etat.fichiers = [];
    }

    /* ───────────── Envoi ───────────── */
    function envoyer() {
        if (etat.envoi) return;
        var desc = etat.desc.trim();
        if (!etat.cat) { montrerErreur('Choisissez une catégorie.'); return; }
        if (desc.length < CFG.descMin) { montrerErreur('Décrivez le problème en quelques mots (au moins ' + CFG.descMin + ' caractères).'); return; }
        if (!navigator.onLine) { montrerErreur('Vous êtes hors ligne. Reconnectez-vous puis réessayez.'); return; }

        var fd = new FormData();
        fd.append('categorie', etat.cat);
        fd.append('description', desc);
        fd.append('cible', (etat.cible || '').trim());
        fd.append('source', etat.source);
        if (etat.diag) { try { fd.append('diagnostics', JSON.stringify(collecterDiagnostic())); } catch (e) {} }
        etat.fichiers.forEach(function (x) { fd.append('captures', x.file, x.file.name); });

        etat.envoi = true;
        var btn = $('#fnsr-envoyer', racine);
        btn.disabled = true;
        btn.innerHTML = '<span class="fnsr-spin"></span> Envoi en cours…';
        montrerErreur('');

        var ctrl = ('AbortController' in window) ? new AbortController() : null;
        var timer = ctrl ? setTimeout(function () { ctrl.abort(); }, CFG.timeoutMs) : null;
        var entetes = { 'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json' };
        var csrf = jetonCsrf();
        if (csrf) entetes['X-CSRFToken'] = csrf;

        fetch(CFG.endpoint, { method: 'POST', body: fd, headers: entetes, credentials: 'same-origin', signal: ctrl ? ctrl.signal : undefined })
            .then(function (r) {
                return r.text().then(function (txt) {
                    var data = null;
                    try { data = JSON.parse(txt); } catch (e) {}
                    return { ok: r.ok, status: r.status, data: data };
                });
            })
            .then(function (res) {
                if (res.ok && res.data && res.data.success) {
                    $('#fnsr-ref', racine).textContent = res.data.reference || '';
                    $('#fnsr-ref', racine).hidden = !res.data.reference;
                    reinitialiserFormulaire();
                    afficher('merci');
                    return;
                }
                var msg = res.data && res.data.error;
                if (!msg) {
                    if (res.status === 401 || res.status === 403) msg = 'Votre session a expiré. Rechargez la page et reconnectez-vous.';
                    else if (res.status === 413) msg = 'Les images sont trop lourdes. Retirez-en une et réessayez.';
                    else if (res.status === 429) msg = 'Vous avez envoyé beaucoup de signalements. Réessayez un peu plus tard.';
                    else msg = 'Le serveur n’a pas pu enregistrer le signalement (code ' + res.status + '). Réessayez.';
                }
                montrerErreur(msg);
            })
            .catch(function (err) {
                montrerErreur(err && err.name === 'AbortError'
                    ? 'L’envoi prend trop de temps. Vérifiez votre connexion puis réessayez.'
                    : 'Impossible d’envoyer le signalement. Vérifiez votre connexion puis réessayez.');
            })
            .then(function () {
                if (timer) clearTimeout(timer);
                etat.envoi = false;
                btn.innerHTML = 'Envoyer le signalement';
                majBoutonEnvoi();
            });
    }

    function reinitialiserFormulaire() {
        viderCaptures();
        etat.cat = null; etat.desc = ''; etat.cible = ''; etat.diag = true; etat.filtreAbus = false;
        if (!racine) return;
        $('#fnsr-desc', racine).value = '';
        $('#fnsr-cible', racine).value = '';
        $('#fnsr-nb', racine).textContent = '0';
        $('#fnsr-diag', racine).checked = true;
        $('#fnsr-diag-apercu', racine).parentNode.hidden = false;
        dessinerCaptures();
        montrerErreur('');
        majBoutonEnvoi();
    }

    /* ───────────── Ouverture / fermeture ───────────── */
    function ouvrir(source) {
        if (ouvert) return;
        construire();
        etat.source = source || 'manuel';
        dernierOuvert = Date.now();
        ouvert = true;
        racine.hidden = false;
        document.documentElement.classList.add('fnsr-lock');
        dessinerCaptures();
        afficher('accueil');
        majReglageUI();
        void racine.offsetWidth;
        racine.classList.add('fnsr-on');
        if (source === 'secousse' && navigator.vibrate) { try { navigator.vibrate(30); } catch (e) {} }
    }

    function fermer() {
        if (!ouvert) return;
        if (etat.etape === 'details' && etat.desc.trim().length > 0 && !etat.envoi) {
            if (!window.confirm('Abandonner ce signalement ? Votre texte sera perdu.')) return;
        }
        ouvert = false;
        racine.classList.remove('fnsr-on');
        document.documentElement.classList.remove('fnsr-lock');
        setTimeout(function () {
            if (ouvert) return;
            racine.hidden = true;
            $$('.fnsr-page', racine).forEach(function (p) { p.hidden = true; p.classList.remove('fnsr-in'); });
            $('.fnsr-sheet', racine).style.visibility = 'visible';
            if (etat.etape === 'merci' || true) reinitialiserFormulaire();
        }, 320);
    }

    function surClic(e) {
        var el = e.target.closest ? e.target.closest('[data-fnsr]') : null;
        if (!el || !racine.contains(el)) return;
        switch (el.getAttribute('data-fnsr')) {
            case 'fermer':   fermer(); break;
            case 'demarrer': ouvrirCategories(false); break;
            case 'abus':     ouvrirCategories(true); break;
            case 'cat':      choisirCategorie(el.getAttribute('data-cat')); break;
            case 'retour':   retour(); break;
            case 'ajouter':  $('#fnsr-file', racine).click(); break;
            case 'retirer':
                var i = parseInt(el.getAttribute('data-i'), 10);
                if (etat.fichiers[i]) { try { URL.revokeObjectURL(etat.fichiers[i].url); } catch (x) {} etat.fichiers.splice(i, 1); dessinerCaptures(); montrerErreur(''); }
                break;
            case 'envoyer':  envoyer(); break;
        }
    }

    /* ───────────── Réglage « secouer » + autorisation iOS ───────────── */
    function iosAutorisationRequise() {
        return typeof window.DeviceMotionEvent !== 'undefined' && typeof window.DeviceMotionEvent.requestPermission === 'function';
    }
    function demanderAutorisationMouvement() {
        if (!iosAutorisationRequise()) return Promise.resolve('granted');
        permissionDemandee = true;
        return window.DeviceMotionEvent.requestPermission().then(function (r) {
            permissionRefusee = (r !== 'granted');
            return r;
        }).catch(function () { permissionRefusee = true; return 'denied'; });
    }
    function majReglageUI() {
        if (!racine) return;
        var cb = $('#fnsr-reglage', racine), note = $('#fnsr-note-mouvement', racine), info = $('#fnsr-reglage-info', racine);
        var supporte = typeof window.DeviceMotionEvent !== 'undefined';
        cb.checked = lireReglage() && !permissionRefusee;
        info.textContent = cb.checked ? 'Activé sur cet appareil' : 'Désactivé sur cet appareil';
        var msg = '';
        if (!supporte) msg = 'Cet appareil ne permet pas de détecter les secousses. Utilisez le bouton « Signaler un problème ».';
        else if (window.isSecureContext === false) msg = 'La détection de secousse nécessite une connexion sécurisée (https).';
        else if (permissionRefusee) msg = 'L’accès aux capteurs de mouvement est refusé. Autorisez-le dans les réglages de votre navigateur.';
        else if (iosAutorisationRequise() && !permissionDemandee && cb.checked) msg = 'Sur iPhone, activez le réglage ci-dessus une fois pour autoriser les capteurs de mouvement.';
        note.textContent = msg;
        note.hidden = !msg;
    }
    function changerReglage(actif, cb) {
        if (actif) {
            demanderAutorisationMouvement().then(function (r) {
                if (r !== 'granted') { ecrireReglage(false); } else { ecrireReglage(true); permissionRefusee = false; }
                majReglageUI();
            });
        } else {
            ecrireReglage(false);
            majReglageUI();
        }
    }

    /* ───────────── Détection de secousse ───────────── */
    var derniere = null, secousses = [], derniereCompte = 0;
    function champActif() {
        var a = document.activeElement;
        if (!a) return false;
        var n = (a.tagName || '').toLowerCase();
        return n === 'input' || n === 'textarea' || n === 'select' || a.isContentEditable;
    }
    function surMouvement(e) {
        if (ouvert || document.hidden || !lireReglage()) { derniere = null; return; }
        var a = e && (e.accelerationIncludingGravity || e.acceleration);
        if (!a || a.x == null || a.y == null || a.z == null) return;
        if (derniere) {
            var d = Math.abs(a.x - derniere.x) + Math.abs(a.y - derniere.y) + Math.abs(a.z - derniere.z);
            var t = Date.now();
            if (d > CFG.seuilSecousse && t - derniereCompte > CFG.ecartMinMs) {
                derniereCompte = t;
                secousses = secousses.filter(function (s) { return t - s < CFG.fenetreMs; });
                secousses.push(t);
                if (secousses.length >= CFG.secoussesRequises && t - dernierOuvert > CFG.pauseApresMs && !champActif()) {
                    secousses = [];
                    ouvrir('secousse');
                }
            }
        }
        derniere = { x: a.x, y: a.y, z: a.z };
    }
    if (typeof window.DeviceMotionEvent !== 'undefined') {
        window.addEventListener('devicemotion', surMouvement, { passive: true });
    }

    /* Tout élément [data-signaler-probleme] ouvre l'écran (menu, lien, bouton…) */
    document.addEventListener('click', function (e) {
        var el = e.target.closest ? e.target.closest('[data-signaler-probleme]') : null;
        if (!el) return;
        e.preventDefault();
        if (iosAutorisationRequise() && !permissionDemandee && lireReglage()) demanderAutorisationMouvement();
        ouvrir('manuel');
    });

    window.FaceNetSignalement = { ouvrir: function () { ouvrir('manuel'); }, fermer: fermer };
})();