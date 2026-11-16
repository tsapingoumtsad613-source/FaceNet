/* FaceNet — Notes : bulles dans la messagerie, bandeau dans le fil, fenêtre de lecture + réponse.
   Script autonome : il n'écrase rien, il AJOUTE des éléments aux pages existantes. */
(function () {
    'use strict';
    if (window.__fnNotesLoaded) return;
    window.__fnNotesLoaded = true;

    var UPLOADS = '/static/uploads/';
    var notes = [], moiId = null;
    var audio = null;

    /* ---------- utilitaires ---------- */
    function el(tag, cls, txt) {
        var e = document.createElement(tag);
        if (cls) e.className = cls;
        if (txt != null) e.textContent = txt;
        return e;
    }
    function avatarUrl(n) { return UPLOADS + (n.avatar || 'default_avatar.png'); }
    function court(s, max) {
        var a = Array.from(s || '');
        return a.length > max ? a.slice(0, max).join('') + '…' : (s || '');
    }
    function resume(n) {
        if (n.texte) return n.texte;
        if (n.musique_titre) return '🎵 ' + n.musique_titre;
        if (n.gif_url) return 'GIF';
        return '';
    }
    function ilYa(iso) {
        var s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
        if (s < 60) return "à l'instant";
        if (s < 3600) return 'il y a ' + Math.floor(s / 60) + ' min';
        return 'il y a ' + Math.floor(s / 3600) + ' h';
    }
    function noteDe(userId) {
        for (var i = 0; i < notes.length; i++) if (notes[i].user_id === userId) return notes[i];
        return null;
    }
    function arreterAudio() { if (audio) { audio.pause(); audio = null; } }

    /* ---------- styles ---------- */
    var css = [
        '.fn-nb{position:absolute;left:30px;top:-12px;z-index:5;max-width:92px;background:var(--bg,#f0f2f5);color:var(--text,#050505);border-radius:14px;padding:3px 8px;font-size:11px;line-height:1.25;font-weight:600;box-shadow:0 1px 3px rgba(0,0,0,.25);cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:block}',
        '.fn-nb-dots{position:absolute;left:24px;top:-3px;z-index:5;width:7px;height:7px;border-radius:50%;background:var(--bg,#f0f2f5);box-shadow:0 1px 2px rgba(0,0,0,.25);pointer-events:none}',
        '.fn-nb.fn-nb-empty{background:#0866FF;color:#fff;font-weight:700}',
        '.fn-notes-strip{display:flex;gap:12px;overflow-x:auto;padding:22px 12px 8px;margin:0 0 10px;background:var(--surface,#fff);border-radius:14px;scrollbar-width:none;box-shadow:0 1px 2px rgba(16,24,40,.06)}',
        '.fn-notes-strip::-webkit-scrollbar{display:none}',
        '.fn-ns-item{flex:0 0 auto;width:78px;text-align:center;cursor:pointer;position:relative;padding-top:30px}',
        '.fn-ns-bub{position:absolute;top:0;left:50%;transform:translateX(-50%);max-width:84px;min-width:40px;background:var(--bg,#f0f2f5);color:var(--text,#050505);border-radius:14px;padding:4px 8px;font-size:11px;line-height:1.25;font-weight:600;box-shadow:0 1px 3px rgba(0,0,0,.22);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
        '.fn-ns-bub.fn-nb-empty{background:#0866FF;color:#fff}',
        '.fn-ns-dot{position:absolute;top:24px;left:calc(50% - 16px);width:7px;height:7px;border-radius:50%;background:var(--bg,#f0f2f5);box-shadow:0 1px 2px rgba(0,0,0,.22)}',
        '.fn-ns-av{width:52px;height:52px;border-radius:50%;object-fit:cover;display:block;margin:0 auto;background:#ddd}',
        '.fn-ns-name{margin-top:5px;font-size:11px;color:var(--text,#050505);opacity:.75;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}',
        '.fn-nm-back{position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:100000;display:flex;align-items:center;justify-content:center;padding:16px}',
        '.fn-nm{width:100%;max-width:400px;background:var(--surface,#fff);color:var(--text,#050505);border-radius:18px;padding:22px 18px 16px;position:relative;max-height:90vh;overflow-y:auto;box-shadow:0 10px 40px rgba(0,0,0,.35)}',
        '.fn-nm-x{position:absolute;top:8px;right:10px;border:none;background:none;color:inherit;font-size:20px;cursor:pointer;opacity:.7}',
        '.fn-nm-head{display:flex;align-items:center;gap:10px;margin-bottom:14px}',
        '.fn-nm-head img{width:46px;height:46px;border-radius:50%;object-fit:cover}',
        '.fn-nm-head b{display:block;font-size:15px}.fn-nm-head span{font-size:12px;opacity:.6}',
        '.fn-nm-card{background:var(--bg,#f0f2f5);border-radius:16px;padding:14px;text-align:center;word-break:break-word;font-size:16px}',
        '.fn-nm-card img.g{display:block;max-width:100%;max-height:200px;margin:8px auto 0;border-radius:12px}',
        '.fn-nm-mus{display:flex;align-items:center;gap:10px;margin-top:10px;text-align:left}',
        '.fn-nm-mus img{width:42px;height:42px;border-radius:8px;object-fit:cover}',
        '.fn-nm-mus .t{flex:1;min-width:0;font-size:13px}.fn-nm-mus .t b{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.fn-nm-mus .t span{opacity:.65;font-size:12px}',
        '.fn-nm-mus button{border:none;background:#0866FF;color:#fff;width:34px;height:34px;border-radius:50%;cursor:pointer}',
        '.fn-nm-reply{display:flex;gap:8px;margin-top:14px}',
        '.fn-nm-reply input{flex:1;min-width:0;border:1px solid var(--border,#ccd0d5);border-radius:20px;padding:10px 14px;font-size:15px;background:var(--surface,#fff);color:inherit;outline:none}',
        '.fn-nm-reply button,.fn-nm-btn{border:none;background:#0866FF;color:#fff;font-weight:700;border-radius:20px;padding:0 16px;cursor:pointer;min-height:40px}',
        '.fn-nm-btn.sec{background:var(--bg,#f0f2f5);color:inherit}.fn-nm-btn.del{background:#fde8ec;color:#e41e3f}',
        '.fn-nm-row{display:flex;gap:10px;margin-top:14px}.fn-nm-row .fn-nm-btn{flex:1}',
        '.fn-nm-msg{margin-top:10px;font-size:13px;text-align:center;min-height:16px}',
        'html[data-fn-theme="dark"] .fn-nb,html[data-fn-theme="dark"] .fn-ns-bub,html[data-fn-theme="dark"] .fn-nm-card{background:#3a3b3c;color:#e4e6eb}',
        'html[data-fn-theme="dark"] .fn-nb-dots,html[data-fn-theme="dark"] .fn-ns-dot{background:#3a3b3c}',
        'html[data-fn-theme="dark"] .fn-notes-strip,html[data-fn-theme="dark"] .fn-nm{background:#242526;color:#e4e6eb}'
    ].join('\n');
    var st = document.createElement('style'); st.textContent = css; document.head.appendChild(st);

    /* ---------- fenêtre de lecture / réponse ---------- */
    function fermerModal() {
        arreterAudio();
        var m = document.getElementById('fnNoteModal'); if (m) m.remove();
    }
    function ouvrirNote(n) {
        fermerModal();
        var back = el('div', 'fn-nm-back'); back.id = 'fnNoteModal';
        back.addEventListener('click', function (e) { if (e.target === back) fermerModal(); });
        var box = el('div', 'fn-nm'); back.appendChild(box);
        var x = el('button', 'fn-nm-x', '✕'); x.type = 'button'; x.addEventListener('click', fermerModal); box.appendChild(x);

        var head = el('div', 'fn-nm-head');
        var im = el('img'); im.src = avatarUrl(n); im.alt = ''; head.appendChild(im);
        var who = el('div'); who.appendChild(el('b', null, n.mine ? 'Votre note' : n.nom_complet)); who.appendChild(el('span', null, ilYa(n.created_at)));
        head.appendChild(who); box.appendChild(head);

        var card = el('div', 'fn-nm-card');
        if (n.texte) card.appendChild(el('div', null, n.texte));
        if (n.gif_url) { var g = el('img', 'g'); g.src = n.gif_url; g.alt = 'GIF'; card.appendChild(g); }
        if (n.musique_titre) {
            var mus = el('div', 'fn-nm-mus');
            if (n.musique_cover) { var c = el('img'); c.src = n.musique_cover; c.alt = ''; mus.appendChild(c); }
            var t = el('div', 't'); t.appendChild(el('b', null, n.musique_titre)); t.appendChild(el('span', null, n.musique_artiste)); mus.appendChild(t);
            if (n.musique_preview_url) {
                var pb = el('button', null, '▶'); pb.type = 'button';
                pb.addEventListener('click', function () {
                    if (audio) { arreterAudio(); pb.textContent = '▶'; return; }
                    audio = new Audio(n.musique_preview_url); audio.play().catch(function () {});
                    audio.addEventListener('ended', function () { pb.textContent = '▶'; audio = null; });
                    pb.textContent = '⏸';
                });
                mus.appendChild(pb);
            }
            card.appendChild(mus);
        }
        box.appendChild(card);

        var msg = el('div', 'fn-nm-msg');
        if (n.mine) {
            var row = el('div', 'fn-nm-row');
            var mod = el('button', 'fn-nm-btn sec', 'Modifier'); mod.type = 'button';
            mod.addEventListener('click', function () { window.location.href = '/note/creer'; });
            var sup = el('button', 'fn-nm-btn del', 'Supprimer'); sup.type = 'button';
            sup.addEventListener('click', function () {
                if (!confirm('Supprimer votre note ?')) return;
                fetch('/api/notes/supprimer', { method: 'POST', credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } })
                    .then(function (r) { return r.json(); })
                    .then(function (d) { if (d.success) { fermerModal(); charger(); } else msg.textContent = d.error || 'Suppression impossible.'; })
                    .catch(function () { msg.textContent = 'Connexion impossible.'; });
            });
            row.appendChild(mod); row.appendChild(sup); box.appendChild(row);
        } else {
            var rep = el('div', 'fn-nm-reply');
            var inp = el('input'); inp.type = 'text'; inp.maxLength = 1000; inp.placeholder = 'Répondre à la note…';
            var env = el('button', null, 'Envoyer'); env.type = 'button';
            function envoyer() {
                var v = inp.value.trim(); if (!v) return;
                env.disabled = true; msg.textContent = '';
                var fd = new FormData(); fd.append('contenu', v);
                fetch('/api/notes/' + n.id + '/repondre', { method: 'POST', body: fd, credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } })
                    .then(function (r) { return r.json(); })
                    .then(function (d) {
                        if (d.success) {
                            msg.style.color = '#31a24c'; msg.textContent = 'Réponse envoyée ✓';
                            inp.value = '';
                            setTimeout(function () { window.location.href = '/messagerie/' + d.destinataire_id; }, 800);
                        } else { msg.style.color = '#e41e3f'; msg.textContent = d.error || 'Envoi impossible.'; env.disabled = false; }
                    })
                    .catch(function () { msg.style.color = '#e41e3f'; msg.textContent = 'Connexion impossible.'; env.disabled = false; });
            }
            env.addEventListener('click', envoyer);
            inp.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); envoyer(); } });
            rep.appendChild(inp); rep.appendChild(env); box.appendChild(rep);
        }
        box.appendChild(msg);
        document.body.appendChild(back);
    }
    window.fnOuvrirNote = ouvrirNote;

    /* ---------- messagerie : bulle « qui réfléchit » sur la photo de profil ---------- */
    function bulle(note, estMoi) {
        var frag = document.createDocumentFragment();
        var b = el('span', 'fn-nb' + (note ? '' : ' fn-nb-empty'), note ? court(resume(note), 14) : '💭 Note');
        b.title = note ? 'Voir la note' : 'Créer une note';
        b.addEventListener('click', function (e) {
            e.stopPropagation(); e.preventDefault();
            if (note) ouvrirNote(note); else window.location.href = '/note/creer';
        });
        frag.appendChild(b);
        frag.appendChild(el('span', 'fn-nb-dots'));
        return frag;
    }
    function nettoyer(sel) { document.querySelectorAll(sel).forEach(function (e) { e.remove(); }); }

    function appliquerMessagerie() {
        nettoyer('.fn-nb, .fn-nb-dots');
        document.querySelectorAll('.chat-item[data-user-id]').forEach(function (item) {
            var n = noteDe(parseInt(item.getAttribute('data-user-id'), 10));
            var av = item.querySelector('.chat-avatar');
            if (n && av) av.appendChild(bulle(n, false));
        });
        var moiAv = document.querySelector('.create-story .story-img');
        if (moiAv) {
            moiAv.style.overflow = 'visible';
            moiAv.appendChild(bulle(noteDe(moiId), true));
        }
    }

    /* ---------- fil d'actualité : bandeau de notes (différent des stories) ---------- */
    function appliquerFeed() {
        nettoyer('.fn-notes-strip');
        var ancre = document.querySelector('.stories-section');
        if (!ancre) return;
        var strip = el('div', 'fn-notes-strip');

        var maNote = noteDe(moiId);
        var mien = el('div', 'fn-ns-item');
        var mb = el('div', 'fn-ns-bub' + (maNote ? '' : ' fn-nb-empty'), maNote ? court(resume(maNote), 14) : '💭 Note');
        mien.appendChild(mb); mien.appendChild(el('span', 'fn-ns-dot'));
        var mi = ancre.querySelector('.story-add-avatar-bg') || null;
        var mimg = el('img', 'fn-ns-av'); mimg.alt = ''; mimg.src = maNote ? avatarUrl(maNote) : (mi ? mi.src : UPLOADS + 'default_avatar.png');
        mien.appendChild(mimg); mien.appendChild(el('div', 'fn-ns-name', 'Votre note'));
        mien.addEventListener('click', function () { if (maNote) ouvrirNote(maNote); else window.location.href = '/note/creer'; });
        strip.appendChild(mien);

        notes.forEach(function (n) {
            if (n.mine) return;
            var it = el('div', 'fn-ns-item');
            it.appendChild(el('div', 'fn-ns-bub', court(resume(n), 14)));
            it.appendChild(el('span', 'fn-ns-dot'));
            var im = el('img', 'fn-ns-av'); im.src = avatarUrl(n); im.alt = ''; it.appendChild(im);
            it.appendChild(el('div', 'fn-ns-name', n.nom_complet));
            it.addEventListener('click', function () { ouvrirNote(n); });
            strip.appendChild(it);
        });
        ancre.parentNode.insertBefore(strip, ancre);
    }

    /* ---------- chargement ---------- */
    function appliquer() {
        if (document.getElementById('chatListContainer')) appliquerMessagerie();
        else if (document.getElementById('story-card-add')) appliquerFeed();
    }
    function charger() {
        fetch('/api/notes/actives', { credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' } })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                if (!d || !d.success) return;
                notes = d.notes || []; moiId = d.moi;
                appliquer();
            })
            .catch(function () { /* silencieux : les notes ne doivent jamais gêner la page */ });
    }
    function start() { charger(); setInterval(charger, 90000); }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start); else start();
})();