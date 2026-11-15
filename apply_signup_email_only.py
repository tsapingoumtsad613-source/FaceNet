#!/usr/bin/env python3
"""
FaceNet - Inscription par e-mail uniquement (téléphone temporairement désactivé).

Usage :  python apply_signup_email_only.py chemin/vers/signup.html

- Modifie UNIQUEMENT le fichier indiqué (jamais login.html, routes.py, modèles).
- Crée une sauvegarde signup.html.bak avant toute écriture.
- Chaque remplacement doit correspondre exactement 1 fois, sinon le script
  s'arrête SANS rien modifier.
"""
import sys, shutil, pathlib

path = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "signup.html")
raw = path.read_bytes().decode("utf-8")
NL = "\r\n" if "\r\n" in raw else "\n"
src = raw


def fix(s):
    return s.replace("\n", NL)


EDITS = []


def edit(name, old, new):
    EDITS.append((name, old, fix(new)))


# 1) CSS
edit("CSS", ".password-strength-bar-container {",
""".phone-signup-note { margin-top: 12px; padding: 12px 14px; background: #e7f3ff; border: 1px solid #cce4ff; border-radius: 8px; font-size: 14px; line-height: 1.4; color: #1c1e21; }
        #toggle-contact.is-disabled { opacity: .55; cursor: not-allowed; pointer-events: none; }

        .password-strength-bar-container {""")

# 2) HTML
edit("sous-titre",
 '<p class="subtitle" id="contact-sub" data-i18n="contact_subtitle">Entrez votre numéro de mobile pour être contacté.</p>',
 '<p class="subtitle" id="contact-sub" data-i18n="contact_subtitle_email">Entrez votre adresse e-mail pour créer votre compte.</p>')

edit("champ téléphone désactivé",
 '<input type="tel" name="tel" id="reg-phone" data-i18n-placeholder="phone_placeholder" placeholder="Numéro de téléphone">',
 '<input type="tel" name="tel" id="reg-phone" data-i18n-placeholder="phone_placeholder" placeholder="Numéro de téléphone" disabled>')

edit("champ e-mail obligatoire",
 '<input type="email" name="email" id="reg-email" data-i18n-placeholder="email_placeholder" placeholder="Adresse e-mail">',
 '<input type="email" name="email" id="reg-email" data-i18n-placeholder="email_placeholder" placeholder="Adresse e-mail" required aria-required="true">')

edit("bouton bascule + message",
 '<span class="link-toggle" id="toggle-contact" role="button" tabindex="0" onclick="toggleContactMode()" data-i18n="toggle_contact_to_email">S\'inscrire avec une adresse e-mail</span>',
 '''<span class="link-toggle is-disabled" id="toggle-contact" role="button" aria-disabled="true" tabindex="-1" data-i18n="toggle_contact_to_phone">S'inscrire avec un numéro de mobile</span>
        <div class="phone-signup-note" id="phone-signup-note" role="note" data-i18n="phone_signup_disabled">L'inscription par numéro de téléphone n'est pas encore disponible (bientôt disponible). Veuillez vous inscrire avec votre adresse e-mail.</div>''')

# 3) JS
edit("mode par défaut", "let isPhoneMode = true;",
 "let isPhoneMode = false; // inscription par téléphone désactivée temporairement")

edit("badge pays", "function updateDetectedCountryBadge() {",
 """function updateDetectedCountryBadge() {
        if (!isPhoneMode) { document.getElementById('detected-country-badge').style.display = 'none'; return; }""")

edit("toggleContactMode", "isPhoneMode = !isPhoneMode;",
 "isPhoneMode = false; // téléphone indisponible : on reste sur l'e-mail")

edit("validation e-mail", "if (input.value.trim().length < 5) {",
 "if (!/^\\S+@\\S+\\.\\S+$/.test(input.value.trim())) {")

edit("message e-mail invalide", "errEl.innerText = t('err_contact_generic');",
 "errEl.innerText = t('err_email_invalid');")

# 4) Traductions
edit("i18n fr", "var fr = {",
 """var fr = {
        phone_signup_disabled: "L'inscription par numéro de téléphone n'est pas encore disponible (bientôt disponible). Veuillez vous inscrire avec votre adresse e-mail.",
        contact_subtitle_email: "Entrez votre adresse e-mail pour créer votre compte.",
        err_email_invalid: "Entrez une adresse e-mail valide.",""")

edit("i18n en", "var en = {",
 """var en = {
        phone_signup_disabled: "Phone number sign-up isn't available yet (coming soon). Please sign up with your email address.",
        contact_subtitle_email: "Enter your email address to create your account.",
        err_email_invalid: "Enter a valid email address.",""")

# Vérification : 1 seule occurrence chacune, sinon on arrête sans rien écrire
for name, old, new in EDITS:
    n = src.count(old)
    if n != 1:
        sys.exit(f"ARRÊT : « {name} » trouvé {n} fois (attendu : 1). Fichier NON modifié.")

for name, old, new in EDITS:
    src = src.replace(old, new, 1)

shutil.copyfile(path, str(path) + ".bak")
path.write_bytes(src.encode("utf-8"))
print(f"OK : {len(EDITS)} modifications appliquées à {path} (sauvegarde : {path}.bak)")
