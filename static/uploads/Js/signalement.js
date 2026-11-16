/*
 * signalement.js : modale de signalement réutilisable.
 *
 * Usage : n'importe quel élément avec ces attributs ouvre la modale.
 *   <button data-report-type="post"    data-report-id="{{ pub.id }}">Signaler la publication</button>
 *   <button data-report-type="profile" data-report-id="{{ user.id }}">Signaler le profil</button>
 *   <button data-report-type="message" data-report-id="{{ msg.id }}">Signaler le message</button>
 *   <button data-report-type="group"   data-report-id="{{ groupe.id }}">Signaler le groupe</button>
 *   <button data-report-type="photo"   data-report-id="{{ pub.id }}">Signaler la photo</button>
 *   <button data-report-type="reel"    data-report-id="{{ pub.id }}">Signaler la vidéo</button>
 *   <button data-report-type="comment" data-report-id="{{ comm.id }}">Signaler le commentaire</button>
 * Ou en JS : ouvrirSignalement('post', 42)
 *
 * Les motifs viennent du serveur (/signaler/motifs) : plus de décalage possible
 * entre le JS et le Python. Si tu utilises Flask-WTF, ajoute dans <head> :
 *   <meta name="csrf-token" content="{{ csrf_token() }}">
 *
 * AJOUT : le titre et la question s'adaptent à ce qui est signalé (profil, publication,
 * photo, vidéo, commentaire, musique, message, groupe), et les anciens boutons « Signaler »
 * de feed.html / reel.html / profile.html ouvrent maintenant cette même modale
 * (voir brancherAnciensBoutons en bas de fichier).
 */
(() => {
  // Si le fichier est inclus deux fois (base.html + une page), on ne branche les écouteurs qu'une fois.
  if (window.__rpSignalementCharge) return;
  window.__rpSignalementCharge = true;

  const TITRES = {
    profile: "Signaler ce profil",
    post: "Signaler cette publication",
    message: "Signaler ce message",
    group: "Signaler ce groupe",
    photo: "Signaler cette photo",
    reel: "Signaler cette vidéo",
    comment: "Signaler ce commentaire",
    music: "Signaler cette musique",
  };
  // « Pourquoi signalez-vous … ? » selon ce qui est signalé
  const SUJETS = {
    profile: "ce profil",
    post: "cette publication",
    message: "ce message",
    group: "ce groupe",
    photo: "cette photo",
    reel: "cette vidéo",
    comment: "ce commentaire",
    music: "cette musique",
  };
  // Une photo et un reel sont des publications côté serveur : même route /signaler, type « post ».
  const TYPE_SERVEUR = { photo: "post", reel: "post" };
  let motifsCache = null;

  const csrf = () => document.querySelector('meta[name="csrf-token"]')?.content;

  function injecterStyles() {
    if (document.getElementById("rp-styles")) return;
    const s = document.createElement("style");
    s.id = "rp-styles";
    s.textContent = `
      .rp-overlay{position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:10000;display:flex;align-items:flex-end;justify-content:center}
      .rp-sheet{background:#fff;width:100%;max-width:480px;max-height:88vh;overflow-y:auto;border-radius:14px 14px 0 0;padding:16px 18px 20px;font-family:inherit;color:#1c1e21}
      @media(min-width:520px){.rp-overlay{align-items:center}.rp-sheet{border-radius:12px}}
      .rp-head{display:flex;align-items:center;justify-content:space-between;margin-bottom:4px}
      .rp-head h3{margin:0;font-size:1.15rem}
      .rp-x{border:0;background:#e4e6eb;width:32px;height:32px;border-radius:50%;font-size:20px;cursor:pointer}
      .rp-sub{margin:4px 0 12px;color:#65676b;font-size:.9rem}
      .rp-opt{display:flex;align-items:center;gap:12px;padding:11px 8px;border-radius:8px;cursor:pointer}
      .rp-opt:hover{background:#f0f2f5}
      .rp-opt input{width:18px;height:18px;accent-color:#1877f2}
      .rp-details{width:100%;box-sizing:border-box;margin-top:10px;padding:10px;border:1px solid #ccd0d5;border-radius:8px;font:inherit;resize:vertical;min-height:70px}
      .rp-submit{width:100%;margin-top:12px;padding:11px;border:0;border-radius:8px;background:#1877f2;color:#fff;font-weight:600;font-size:1rem;cursor:pointer}
      .rp-submit:disabled{background:#e4e6eb;color:#bcc0c4;cursor:not-allowed}
      .rp-toast{position:fixed;left:50%;bottom:24px;transform:translateX(-50%);background:#242526;color:#fff;padding:12px 18px;border-radius:8px;z-index:10001;max-width:90vw;font-size:.95rem}
      .rp-toast.err{background:#c0392b}
    `;
    document.head.appendChild(s);
  }

  function toast(texte, erreur = false) {
    const t = document.createElement("div");
    t.className = "rp-toast" + (erreur ? " err" : "");
    t.setAttribute("role", "status");
    t.textContent = texte;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 4000);
  }

  async function chargerMotifs() {
    if (motifsCache) return motifsCache;
    const r = await fetch("/signaler/motifs", { credentials: "same-origin" });
    if (!r.ok) throw new Error("Impossible de charger les motifs de signalement.");
    motifsCache = await r.json();
    return motifsCache;
  }

  // Envoie le signalement à la bonne route selon le type.
  async function envoyer(type, id, motif, details) {
    const headers = { "Content-Type": "application/json", ...(csrf() && { "X-CSRFToken": csrf() }) };
    let url, body;
    // Les commentaires passent maintenant par /signaler (type « comment », voir signalements.py)
    if (type === "music") {
      // route déjà existante dans routes.py (id = {title, artist} de la musique)
      url = "/api/musique/signaler";
      body = { titre: id.title || id.titre || "", artiste: id.artist || id.artiste || "" };
    } else if (type === "comment") {
      // Les commentaires ont leur propre route (routes.py : /api/comment/<id>/report)
      url = "/api/comment/" + encodeURIComponent(id) + "/report";
      body = { raison: motif.label || motif.key, description: details };
    } else {
      url = "/signaler";
      body = { target_type: TYPE_SERVEUR[type] || type, target_id: id, reason: motif.key, details };
    }
    const res = await fetch(url, { method: "POST", credentials: "same-origin", headers, body: JSON.stringify(body) });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !(data.ok || data.success)) throw new Error(data.error || data.message || `Erreur ${res.status}`);
  }

  async function ouvrirSignalement(type, id) {
    if (!TITRES[type]) return console.error("Type de signalement inconnu :", type);
    if (type === "music" ? !(id && (id.title || id.titre)) : (id === undefined || id === null || id === "")) {
      return toast("Impossible d'identifier l'élément à signaler.", true);
    }
    injecterStyles();

    let motifs;
    try { motifs = await chargerMotifs(); }
    catch (e) { return toast(e.message, true); }

    const overlay = document.createElement("div");
    overlay.className = "rp-overlay";
    overlay.innerHTML = `
      <div class="rp-sheet" role="dialog" aria-modal="true" aria-labelledby="rp-titre">
        <div class="rp-head"><h3 id="rp-titre"></h3>
          <button type="button" class="rp-x" aria-label="Fermer">&times;</button></div>
        <p class="rp-sub"></p>
        <div class="rp-list"></div>
        <textarea class="rp-details" maxlength="1000" placeholder="Détails supplémentaires (facultatif)"></textarea>
        <button type="button" class="rp-submit" disabled>Envoyer le signalement</button>
      </div>`;
    overlay.querySelector("h3").textContent = TITRES[type];
    overlay.querySelector(".rp-sub").textContent =
      `Pourquoi signalez-vous ${SUJETS[type]} ? Votre signalement reste anonyme.`;

    const liste = overlay.querySelector(".rp-list");
    const submit = overlay.querySelector(".rp-submit");
    motifs.forEach((m) => {
      const label = document.createElement("label");
      label.className = "rp-opt";
      const radio = document.createElement("input");
      radio.type = "radio"; radio.name = "rp-motif"; radio.value = m.key;
      radio.addEventListener("change", () => { submit.disabled = false; });
      const span = document.createElement("span");
      span.textContent = m.label;
      label.append(radio, span);
      liste.appendChild(label);
    });

    const fermer = () => { overlay.remove(); document.removeEventListener("keydown", onKey); };
    const onKey = (e) => { if (e.key === "Escape") fermer(); };
    document.addEventListener("keydown", onKey);
    overlay.addEventListener("click", (e) => { if (e.target === overlay) fermer(); });
    overlay.querySelector(".rp-x").addEventListener("click", fermer);

    submit.addEventListener("click", async () => {
      const choix = overlay.querySelector('input[name="rp-motif"]:checked');
      if (!choix) return;
      const motif = motifs.find((m) => m.key === choix.value) || { key: choix.value, label: choix.value };
      submit.disabled = true;
      submit.textContent = "Envoi…";
      try {
        await envoyer(type, id, motif, overlay.querySelector(".rp-details").value);
        fermer();
        toast("Signalement envoyé. Merci de nous aider à protéger la communauté.");
      } catch (err) {
        submit.disabled = false;
        submit.textContent = "Envoyer le signalement";
        toast(err.message, true);
      }
    });

    document.body.appendChild(overlay);
  }

  document.addEventListener("click", (e) => {
    const el = e.target.closest("[data-report-type]");
    if (!el) return;
    e.preventDefault();
    ouvrirSignalement(el.dataset.reportType, el.dataset.reportId);
  });

  window.ouvrirSignalement = ouvrirSignalement;

  // ton_page.html : « Signaler » d'un ami -> même modale, type « profile » :
  // le signalement arrive ainsi chez les modérateurs (/moderation/signalements) avec les notifications prévues.
  document.addEventListener("click", (e) => {
    const item = e.target.closest('[data-ami-action="signaler"]');
    if (!item) return;
    const carte = item.closest("[data-ami-id]");
    if (!carte) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    document.querySelectorAll(".amis-dropdown.ouvert").forEach((m) => m.classList.remove("ouvert"));
    document.querySelectorAll('[data-ami-menu-toggle][aria-expanded="true"]').forEach((b) => b.setAttribute("aria-expanded", "false"));
    ouvrirSignalement("profile", carte.getAttribute("data-ami-id"));
  }, true);

  /* ─────────────────────────────────────────────────────────────────────
     AJOUT : les anciens boutons « Signaler » (prompt() du navigateur, motifs figés,
     fonction vide…) ouvrent maintenant cette modale. Rien n'est supprimé dans les
     fichiers HTML : on redirige seulement l'action des fonctions existantes. Chaque
     remplacement n'a lieu que si la fonction existe dans la page courante.
     ───────────────────────────────────────────────────────────────────── */
  function brancherAnciensBoutons() {
    const w = window;
    const existe = (nom) => typeof w[nom] === "function";
    const appeler = (nom) => { try { if (existe(nom)) w[nom](); } catch (e) { /* menu déjà fermé */ } };

    // feed.html — menu ⋮ d'une publication
    if (existe("reportPostFromMenu")) {
      w.reportPostFromMenu = () => {
        appeler("closePostOptions");
        ouvrirSignalement("post", typeof currentPostOptionsId !== "undefined" ? currentPostOptionsId : null);
      };
    }
    // feed.html — visionneuse photo (ne faisait rien jusqu'ici)
    if (existe("reportPhotoViewer")) {
      w.reportPhotoViewer = () => {
        appeler("closePhotoViewerMenu");
        ouvrirSignalement("photo", typeof currentPhotoViewerPubId !== "undefined" ? currentPhotoViewerPubId : null);
      };
    }
    // profile.html — visionneuse photo (appelait /api/signaler_photo, route inexistante)
    if (existe("reportViewerImage")) {
      const ancienne = w.reportViewerImage;
      w.reportViewerImage = function () {
        const pubId = typeof currentViewerPubId !== "undefined" ? currentViewerPubId : null;
        if (!pubId) return ancienne.apply(this, arguments);
        document.querySelectorAll(".photo-quick-dropdown.open").forEach((el) => el.classList.remove("open"));
        ouvrirSignalement("photo", pubId);
      };
    }
    // feed.html et reel.html — commentaire
    if (existe("reportSelectedComment")) {
      w.reportSelectedComment = () => {
        const id = typeof selectedCommentId !== "undefined" ? selectedCommentId : null;
        appeler("closeCommentActions");
        if (id) ouvrirSignalement("comment", id);
      };
    }
    // feed.html — musique
    if (existe("confirmerSignalementMusique")) {
      w.confirmerSignalementMusique = () => {
        const item = typeof musiqueASignalerCourante !== "undefined" ? musiqueASignalerCourante : null;
        appeler("fermerMenuSignalementMusique");
        if (item) ouvrirSignalement("music", item);
      };
    }
    // reel.html — modale d'options de la vidéo
    if (existe("reportReelVideo")) {
      w.reportReelVideo = () => {
        const id = typeof currentOptionsPubId !== "undefined" ? currentOptionsPubId : null;
        try { if (existe("closeModal")) w.closeModal("reel-options-modal"); } catch (e) {}
        ouvrirSignalement("reel", id);
      };
    }
    // reel.html — feuille des trois points : « Signaler un souci » ouvre la modale au lieu des 5 motifs figés
    if (existe("showReelMoreView") && !w.showReelMoreView.__rp) {
      const originale = w.showReelMoreView;
      const nouvelle = function (nom) {
        if (nom === "report" && typeof reelMorePubId !== "undefined" && reelMorePubId) {
          appeler("closeReelMoreSheet");
          ouvrirSignalement("reel", reelMorePubId);
          return;
        }
        return originale.apply(this, arguments);
      };
      nouvelle.__rp = true;
      w.showReelMoreView = nouvelle;
    }
  }
  brancherAnciensBoutons();
})();