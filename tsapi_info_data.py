# -*- coding: utf-8 -*-
"""
Contenu des pages d'information de Tsapi Verified (FaceNet).

 - AVANTAGES      : les 11 avantages des forfaits (page de détail)
 - PAGES_LEGALES  : conditions d'utilisation, confidentialité, remboursement, centre d'aide
 - PLANS          : les 4 forfaits

Tout le texte est ici : tu peux le modifier sans toucher au template ni à la route.
Les textes juridiques sont des modèles complets à faire relire par un juriste avant
la mise en production (délais, adresses e-mail, entité légale, etc.).
"""

DATE_MAJ = "10 novembre 2026"
EMAIL_SUPPORT = "support@facenet.app"          # à adapter
EMAIL_PRIVACY = "confidentialite@facenet.app"  # à adapter

PLANS = [
    {"id": "4500",   "nom": "Standard",  "prix": "4 500 FCFA"},
    {"id": "12000",  "nom": "Premium",   "prix": "12 000 FCFA"},
    {"id": "78000",  "nom": "Max",       "prix": "78 000 FCFA"},
    {"id": "100000", "nom": "Max Plus",  "prix": "100 000 FCFA"},
]


def _svg(alt, inner):
    return (
        '<svg viewBox="0 0 400 240" xmlns="http://www.w3.org/2000/svg" role="img" '
        'aria-label="%s"><rect width="400" height="240" rx="18" fill="var(--placeholder-bg)"/>%s</svg>'
        % (alt, inner)
    )


_CARD = 'fill="var(--white)" stroke="var(--fn-border)" stroke-width="2"'
_BAR = 'fill="var(--fn-border)"'

# ───────────────────────── Illustrations ─────────────────────────
SVG_BADGE = _svg("Profil avec badge bleu vérifié", f"""
<rect x="60" y="50" width="280" height="140" rx="14" {_CARD}/>
<circle cx="110" cy="102" r="28" fill="var(--fn-border)"/>
<circle cx="110" cy="95" r="10" fill="var(--fn-gray)"/>
<path d="M92 120c4-13 32-13 36 0z" fill="var(--fn-gray)"/>
<rect x="155" y="92" width="100" height="12" rx="6" fill="var(--text-dark)"/>
<use href="#fnBadge" x="262" y="86" width="24" height="24"/>
<circle cx="274" cy="98" r="21" fill="none" stroke="var(--fn-blue)" stroke-width="2" stroke-dasharray="4 4"/>
<rect x="155" y="116" width="140" height="8" rx="4" {_BAR}/>
<rect x="80" y="152" width="240" height="10" rx="5" {_BAR}/>
<rect x="80" y="170" width="170" height="10" rx="5" {_BAR}/>
<path d="M330 40l4 9 9 4-9 4-4 9-4-9-9-4 9-4z" fill="var(--fn-blue)"/>
""")

SVG_USURPATION = _svg("Un profil authentique protégé face à une copie", f"""
<rect x="22" y="62" width="150" height="116" rx="12" {_CARD}/>
<circle cx="62" cy="100" r="18" fill="var(--fn-border)"/>
<rect x="88" y="92" width="52" height="9" rx="4" fill="var(--text-dark)"/>
<use href="#fnBadge" x="144" y="87" width="18" height="18"/>
<rect x="40" y="132" width="116" height="8" rx="4" {_BAR}/>
<rect x="40" y="150" width="80" height="8" rx="4" {_BAR}/>
<rect x="228" y="62" width="150" height="116" rx="12" fill="var(--white)" stroke="var(--error-color)" stroke-width="2" stroke-dasharray="6 5"/>
<circle cx="268" cy="100" r="18" fill="var(--fn-border)"/>
<rect x="294" y="92" width="62" height="9" rx="4" fill="var(--fn-gray)"/>
<rect x="246" y="132" width="116" height="8" rx="4" {_BAR}/>
<rect x="246" y="150" width="80" height="8" rx="4" {_BAR}/>
<circle cx="360" cy="70" r="14" fill="var(--error-color)"/>
<path d="M354 64l12 12M366 64l-12 12" stroke="#fff" stroke-width="3" stroke-linecap="round"/>
<path d="M200 84l24 10v20c0 18-11 31-24 36-13-5-24-18-24-36V94z" fill="var(--fn-blue)" stroke="var(--placeholder-bg)" stroke-width="4"/>
<path d="M190 118l7 7 14-15" fill="none" stroke="#fff" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>
""")

SVG_COMMENTAIRES = _svg("Un commentaire vérifié remonte en haut de la liste", f"""
<rect x="40" y="26" width="320" height="58" rx="12" fill="rgba(8,102,255,.10)" stroke="var(--fn-blue)" stroke-width="2"/>
<circle cx="72" cy="55" r="16" fill="var(--fn-border)"/>
<rect x="98" y="43" width="70" height="9" rx="4" fill="var(--text-dark)"/>
<use href="#fnBadge" x="172" y="38" width="18" height="18"/>
<rect x="98" y="60" width="200" height="8" rx="4" {_BAR}/>
<rect x="296" y="12" width="68" height="20" rx="10" fill="var(--fn-blue)"/>
<text x="330" y="26" text-anchor="middle" font-size="11" font-weight="700" fill="#fff" font-family="inherit">En haut</text>
<rect x="40" y="100" width="320" height="50" rx="12" {_CARD}/>
<circle cx="72" cy="125" r="14" fill="var(--fn-border)"/>
<rect x="98" y="113" width="60" height="8" rx="4" fill="var(--fn-gray)"/>
<rect x="98" y="129" width="190" height="8" rx="4" {_BAR}/>
<rect x="40" y="166" width="320" height="50" rx="12" {_CARD}/>
<circle cx="72" cy="191" r="14" fill="var(--fn-border)"/>
<rect x="98" y="179" width="60" height="8" rx="4" fill="var(--fn-gray)"/>
<rect x="98" y="195" width="160" height="8" rx="4" {_BAR}/>
""")

SVG_RECHERCHE = _svg("Un profil vérifié apparaît en premier dans la recherche", f"""
<rect x="50" y="26" width="300" height="38" rx="19" {_CARD}/>
<circle cx="76" cy="44" r="8" fill="none" stroke="var(--fn-gray)" stroke-width="3"/>
<path d="M82 50l7 7" stroke="var(--fn-gray)" stroke-width="3" stroke-linecap="round"/>
<rect x="100" y="39" width="110" height="10" rx="5" {_BAR}/>
<rect x="50" y="80" width="300" height="52" rx="12" fill="rgba(8,102,255,.10)" stroke="var(--fn-blue)" stroke-width="2"/>
<circle cx="84" cy="106" r="17" fill="var(--fn-border)"/>
<rect x="112" y="94" width="80" height="9" rx="4" fill="var(--text-dark)"/>
<use href="#fnBadge" x="196" y="89" width="18" height="18"/>
<rect x="112" y="111" width="130" height="8" rx="4" {_BAR}/>
<circle cx="322" cy="106" r="13" fill="var(--fn-blue)"/>
<text x="322" y="111" text-anchor="middle" font-size="14" font-weight="800" fill="#fff" font-family="inherit">1</text>
<rect x="50" y="144" width="300" height="46" rx="12" {_CARD}/>
<circle cx="84" cy="167" r="14" fill="var(--fn-border)"/>
<rect x="112" y="157" width="80" height="8" rx="4" fill="var(--fn-gray)"/>
<rect x="112" y="172" width="120" height="8" rx="4" {_BAR}/>
<rect x="50" y="198" width="300" height="30" rx="12" {_CARD}/>
<circle cx="84" cy="213" r="9" fill="var(--fn-border)"/>
<rect x="112" y="209" width="90" height="8" rx="4" {_BAR}/>
""")

SVG_NOTORIETE = _svg("Deux files d'attente : réponse standard et réponse rapide", f"""
<text x="40" y="62" font-size="13" font-weight="700" fill="var(--fn-gray)" font-family="inherit">Réponse standard</text>
<rect x="40" y="74" width="320" height="22" rx="11" {_BAR}/>
<rect x="40" y="74" width="190" height="22" rx="11" fill="var(--fn-gray)" opacity=".55"/>
<circle cx="344" cy="85" r="15" fill="var(--white)" stroke="var(--fn-gray)" stroke-width="2"/>
<path d="M344 76v10l6 4" fill="none" stroke="var(--fn-gray)" stroke-width="2.5" stroke-linecap="round"/>
<text x="40" y="146" font-size="13" font-weight="700" fill="var(--fn-blue)" font-family="inherit">Réponse rapide</text>
<rect x="40" y="158" width="320" height="22" rx="11" {_BAR}/>
<rect x="40" y="158" width="90" height="22" rx="11" fill="var(--fn-blue)"/>
<circle cx="344" cy="169" r="15" fill="var(--fn-blue)"/>
<path d="M348 158l-10 14h7l-3 11 11-15h-7z" fill="#fff"/>
<path d="M40 205h320" stroke="var(--fn-border)" stroke-width="2" stroke-dasharray="4 5"/>
<text x="40" y="224" font-size="11" fill="var(--fn-gray)" font-family="inherit">Votre message</text>
<text x="360" y="224" text-anchor="end" font-size="11" fill="var(--fn-gray)" font-family="inherit">Réponse</text>
""")

SVG_VISIBILITE_MAX = _svg("Portée maximale pour les posts, reels et stories", f"""
<rect x="150" y="20" width="100" height="200" rx="18" {_CARD}/>
<circle cx="176" cy="48" r="11" fill="none" stroke="var(--fn-blue)" stroke-width="3"/>
<circle cx="200" cy="48" r="11" fill="none" stroke="var(--fn-blue)" stroke-width="3"/>
<circle cx="224" cy="48" r="11" fill="none" stroke="var(--fn-blue)" stroke-width="3"/>
<rect x="164" y="72" width="72" height="62" rx="8" fill="var(--fn-blue)" opacity=".9"/>
<path d="M192 92v22l20-11z" fill="#fff"/>
<rect x="164" y="144" width="72" height="9" rx="4" {_BAR}/>
<rect x="164" y="160" width="50" height="9" rx="4" {_BAR}/>
<rect x="164" y="180" width="72" height="26" rx="8" fill="rgba(8,102,255,.12)"/>
<path d="M122 90q-26 30 0 60M100 74q-42 46 0 92M78 58q-56 62 0 124" fill="none" stroke="var(--fn-blue)" stroke-width="4" stroke-linecap="round" opacity=".7"/>
<path d="M278 90q26 30 0 60M300 74q42 46 0 92M322 58q56 62 0 124" fill="none" stroke="var(--fn-blue)" stroke-width="4" stroke-linecap="round" opacity=".7"/>
""")

SVG_SUPPORT_EMAIL = _svg("Un e-mail prioritaire passe devant la file d'attente", f"""
<rect x="40" y="60" width="90" height="12" rx="6" {_BAR}/>
<rect x="40" y="86" width="70" height="12" rx="6" {_BAR}/>
<rect x="40" y="112" width="80" height="12" rx="6" {_BAR}/>
<rect x="150" y="70" width="210" height="130" rx="14" {_CARD}/>
<path d="M150 86l105 66 105-66" fill="none" stroke="var(--fn-blue)" stroke-width="4" stroke-linejoin="round"/>
<circle cx="352" cy="70" r="18" fill="var(--fn-blue)"/>
<path d="M352 60v12" stroke="#fff" stroke-width="4" stroke-linecap="round"/>
<circle cx="352" cy="79" r="2.4" fill="#fff"/>
<path d="M128 150h-24m0 0l9-9m-9 9l9 9" fill="none" stroke="var(--fn-blue)" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
""")

SVG_SUPPORT_247 = _svg("Assistance disponible à toute heure", f"""
<circle cx="130" cy="120" r="62" fill="var(--white)" stroke="var(--fn-blue)" stroke-width="8"/>
<text x="130" y="131" text-anchor="middle" font-size="32" font-weight="800" fill="var(--fn-blue)" font-family="inherit">24/7</text>
<rect x="226" y="56" width="140" height="52" rx="16" fill="var(--fn-blue)"/>
<circle cx="264" cy="82" r="5" fill="#fff"/><circle cx="286" cy="82" r="5" fill="#fff"/><circle cx="308" cy="82" r="5" fill="#fff"/>
<path d="M246 108l-10 14 22-8z" fill="var(--fn-blue)"/>
<rect x="208" y="132" width="130" height="48" rx="16" {_CARD}/>
<rect x="226" y="150" width="70" height="8" rx="4" {_BAR}/>
<rect x="226" y="164" width="44" height="8" rx="4" {_BAR}/>
""")

SVG_STATS = _svg("Tableau de bord des statistiques du profil", f"""
<rect x="50" y="34" width="300" height="172" rx="14" {_CARD}/>
<rect x="76" y="140" width="34" height="42" rx="6" fill="var(--fn-blue)" opacity=".35"/>
<rect x="124" y="118" width="34" height="64" rx="6" fill="var(--fn-blue)" opacity=".5"/>
<rect x="172" y="96" width="34" height="86" rx="6" fill="var(--fn-blue)" opacity=".7"/>
<rect x="220" y="72" width="34" height="110" rx="6" fill="var(--fn-blue)" opacity=".9"/>
<path d="M66 190h160" stroke="var(--fn-border)" stroke-width="2"/>
<path d="M93 122L141 98L189 80L237 54" fill="none" stroke="var(--success-color)" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>
<circle cx="237" cy="54" r="6" fill="var(--success-color)"/>
<rect x="272" y="62" width="64" height="28" rx="14" fill="var(--fn-blue)"/>
<text x="304" y="81" text-anchor="middle" font-size="13" font-weight="700" fill="#fff" font-family="inherit">Vues</text>
<rect x="272" y="104" width="64" height="28" rx="14" fill="rgba(8,102,255,.12)"/>
<text x="304" y="123" text-anchor="middle" font-size="12" font-weight="700" fill="var(--fn-blue)" font-family="inherit">Portée</text>
<rect x="272" y="146" width="64" height="28" rx="14" fill="rgba(8,102,255,.12)"/>
<text x="304" y="165" text-anchor="middle" font-size="12" font-weight="700" fill="var(--fn-blue)" font-family="inherit">Abonnés</text>
""")

SVG_PROTECTION_RENFORCEE = _svg("Bouclier de sécurité et contrôles supplémentaires", f"""
<path d="M130 36l64 27v52c0 46-27 77-64 91-37-14-64-45-64-91V63z" fill="var(--fn-blue)"/>
<rect x="107" y="104" width="46" height="38" rx="7" fill="#fff"/>
<path d="M115 104v-9a15 15 0 0130 0v9" fill="none" stroke="#fff" stroke-width="6" stroke-linecap="round"/>
<circle cx="130" cy="122" r="5" fill="var(--fn-blue)"/>
<circle cx="246" cy="78" r="12" fill="var(--success-color)"/><path d="M240 78l5 5 8-9" fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
<rect x="268" y="72" width="96" height="10" rx="5" {_BAR}/>
<circle cx="246" cy="120" r="12" fill="var(--success-color)"/><path d="M240 120l5 5 8-9" fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
<rect x="268" y="114" width="80" height="10" rx="5" {_BAR}/>
<circle cx="246" cy="162" r="12" fill="var(--success-color)"/><path d="M240 162l5 5 8-9" fill="none" stroke="#fff" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
<rect x="268" y="156" width="90" height="10" rx="5" {_BAR}/>
""")

SVG_EVENEMENTS = _svg("Invitation à un événement exclusif", f"""
<rect x="50" y="68" width="300" height="104" rx="16" fill="var(--fn-blue)"/>
<circle cx="50" cy="120" r="16" fill="var(--placeholder-bg)"/>
<circle cx="350" cy="120" r="16" fill="var(--placeholder-bg)"/>
<path d="M268 76v88" stroke="#fff" stroke-width="3" stroke-dasharray="6 6" opacity=".8"/>
<text x="150" y="132" text-anchor="middle" font-size="38" font-weight="800" fill="#fff" font-family="inherit" letter-spacing="2">VIP</text>
<polygon points="308,98 315,113 331,115 319,126 322,142 308,134 294,142 297,126 285,115 301,113" fill="#ffd700"/>
<path d="M70 40l4 9 9 4-9 4-4 9-4-9-9-4 9-4z" fill="var(--fn-blue)"/>
<path d="M330 196l3 7 7 3-7 3-3 7-3-7-7-3 7-3z" fill="var(--fn-blue)"/>
""")

# ───────────────────────── Avantages ─────────────────────────
# plans : identifiants des forfaits qui incluent l'avantage
AVANTAGES = [
    {
        "slug": "badge-bleu",
        "titre": "Badge bleu vérifié",
        "accroche": "Montrez que votre compte est authentique.",
        "icone": "fa-circle-check",
        "svg": SVG_BADGE,
        "plans": ["4500", "12000", "78000", "100000"],
        "intro": "Le badge bleu s’affiche à côté de votre nom sur votre profil, dans vos publications, vos commentaires et la messagerie. Il indique à tout le monde que FaceNet a vérifié qu’une vraie personne, clairement identifiée, se trouve derrière le compte.",
        "etapes": [
            ("Vous choisissez un forfait et réglez", "Le paiement est le premier pas du parcours de vérification : forfait et paiement, profil, photo, pièce d’identité, puis scan."),
            ("Vous confirmez votre identité", "Vous renseignez votre profil, prenez une photo et fournissez une pièce d’identité en cours de validité. Le nom indiqué doit correspondre à celui du document."),
            ("Un scan du visage est comparé à la pièce", "Cette étape vérifie que la personne qui demande le badge est bien le titulaire de la pièce. Elle se fait en quelques secondes depuis votre téléphone."),
            ("Notre équipe valide, le badge s’affiche", "Une fois la demande validée, le badge apparaît automatiquement sur votre profil et partout où votre nom est affiché."),
        ],
        "points": [
            ("Ce que le badge garantit", "L’identité du titulaire a été contrôlée par FaceNet à partir d’une pièce officielle et d’une vérification du visage."),
            ("Ce que le badge ne garantit pas", "Il ne s’agit pas d’un label de qualité ni d’une approbation des propos tenus : il atteste de l’authenticité du compte, pas du contenu."),
            ("Durée du badge", "Il reste actif tant que votre forfait est actif et que votre compte respecte les Conditions d’utilisation."),
        ],
        "faq": [
            ("Mon badge est-il retiré si je change de nom ?", "Un changement de nom sur un compte vérifié nécessite une nouvelle vérification, afin que le badge reste fiable."),
            ("Que se passe-t-il si ma demande est refusée ?", "Vous êtes informé du motif et pouvez soumettre de nouveaux documents. Les conditions de remboursement sont décrites dans la Politique de remboursement."),
        ],
    },
    {
        "slug": "protection-usurpation",
        "titre": "Protection contre l’usurpation d’identité",
        "accroche": "Nous aidons à empêcher que quelqu’un se fasse passer pour vous.",
        "icone": "fa-shield-halved",
        "svg": SVG_USURPATION,
        "plans": ["4500", "12000", "78000", "100000"],
        "intro": "Une fois votre compte vérifié, FaceNet surveille la création de nouveaux comptes et les signalements qui pourraient copier votre identité : même nom, photo reprise, publications recopiées. Cette page explique comment cette surveillance fonctionne.",
        "etapes": [
            ("Votre identité de référence est enregistrée", "Au moment de la vérification, votre nom, votre photo et les informations de votre pièce servent de référence officielle pour votre compte."),
            ("Les nouveaux comptes sont comparés", "Quand un compte est créé ou modifié, nous le comparons aux comptes vérifiés : noms très proches, photos identiques ou retouchées, biographies recopiées."),
            ("Les cas suspects sont examinés", "Un compte qui ressemble trop à un compte vérifié est mis en file de revue. Un membre de l’équipe examine les éléments avant toute décision."),
            ("Vous êtes prévenu et le faux compte est traité", "Si une usurpation est confirmée, le compte copie est limité ou supprimé, et vous êtes informé. Vous pouvez aussi signaler vous-même un faux compte à tout moment."),
        ],
        "points": [
            ("Détection automatique", "Des contrôles automatiques repèrent les ressemblances de noms et de photos dès la création des comptes."),
            ("Revue humaine", "Une personne tranche sur les cas douteux : nous évitons de sanctionner un homonyme qui n’usurpe rien."),
            ("Signalement prioritaire", "Un signalement venant d’un compte vérifié est traité en priorité par rapport aux signalements ordinaires."),
        ],
        "limites": "Aucun système ne peut empêcher à 100 % la création d’un faux compte. L’objectif est de les détecter vite et de les retirer rapidement. Si vous repérez une copie de votre profil, signalez-la depuis le profil concerné.",
        "faq": [
            ("Combien de temps faut-il pour retirer un faux compte ?", "Les cas évidents sont traités rapidement ; les cas ambigus demandent une revue humaine. Les forfaits supérieurs bénéficient d’un support plus rapide."),
            ("Un homonyme peut-il être bloqué à tort ?", "Non, sauf s’il reprend votre photo ou se présente comme vous. La revue humaine sert justement à éviter ces erreurs."),
        ],
    },
    {
        "slug": "visibilite-commentaires",
        "titre": "Boost de visibilité dans les commentaires",
        "accroche": "Vos commentaires sont mis en avant pour être vus par plus de monde.",
        "icone": "fa-comments",
        "svg": SVG_COMMENTAIRES,
        "plans": ["4500", "12000", "78000", "100000"],
        "intro": "Sous une publication, les commentaires de comptes vérifiés remontent plus haut dans la liste. Vos réponses sont donc lues plus souvent, ce qui renforce votre présence dans les discussions.",
        "etapes": [
            ("Vous commentez comme d’habitude", "Rien à activer : le boost s’applique automatiquement à tous vos commentaires dès que votre badge est actif."),
            ("Votre commentaire reçoit un rang plus élevé", "Dans le classement des commentaires, l’authenticité du compte est prise en compte en plus de la pertinence et de la date."),
            ("Il apparaît parmi les premiers", "Votre commentaire est affiché plus haut, accompagné du badge bleu, ce qui attire l’attention des lecteurs."),
        ],
        "points": [
            ("Un coup de pouce, pas une garantie", "Le boost augmente vos chances d’être vu mais ne remplace pas la qualité du commentaire : un contenu signalé ou hors sujet perd son avantage."),
            ("Les règles de la communauté restent les mêmes", "Spam, insultes ou liens abusifs ne sont jamais mis en avant, même avec un badge."),
        ],
        "faq": [
            ("Le boost fonctionne-t-il sur toutes les publications ?", "Oui, sur les publications où les commentaires sont ouverts. Le propriétaire de la publication peut toujours masquer un commentaire."),
        ],
    },
    {
        "slug": "recherche-prioritaire",
        "titre": "Recherche prioritaire dans FaceNet",
        "accroche": "Votre profil remonte dans les résultats de recherche.",
        "icone": "fa-magnifying-glass",
        "svg": SVG_RECHERCHE,
        "plans": ["12000", "78000", "100000"],
        "intro": "Quand quelqu’un tape votre nom dans la recherche, votre profil vérifié est placé avant les profils qui portent un nom proche. Les personnes vous retrouvent vite, sans se tromper de compte.",
        "etapes": [
            ("Quelqu’un lance une recherche", "Il saisit votre nom ou une partie de votre nom dans la barre de recherche de FaceNet."),
            ("Les résultats sont classés", "FaceNet classe d’abord les correspondances les plus exactes, puis donne la priorité aux comptes vérifiés disposant de cet avantage."),
            ("Votre profil s’affiche en tête", "Il apparaît avec son badge bleu, avec le bouton Suivre ou Envoyer une invitation selon la relation."),
        ],
        "points": [
            ("Priorité, pas exclusivité", "Le classement tient aussi compte de l’exactitude du nom et de vos relations : une correspondance exacte reste toujours bien placée."),
            ("Effet immédiat", "La priorité est active dès que votre forfait l’inclut."),
        ],
        "faq": [
            ("Cet avantage me fait-il apparaître dans les suggestions d’amis ?", "Il agit sur la recherche. Les suggestions suivent leurs propres règles."),
        ],
    },
    {
        "slug": "reponse-rapide",
        "titre": "Réponse plus rapide à tous vos problèmes",
        "accroche": "Vos demandes passent devant les autres.",
        "icone": "fa-bolt",
        "svg": SVG_NOTORIETE,
        "plans": ["78000", "100000"],
        "intro": "Accès au compte, paiement, faux compte, signalement, bug : quel que soit votre problème, votre demande entre dans une file prioritaire et reçoit une première réponse plus vite que les demandes ordinaires.",
        "etapes": [
            ("Vous signalez votre problème", "Depuis le Centre d’aide ou le bouton de signalement, en étant connecté à votre compte."),
            ("Votre demande entre dans la file rapide", "Le système reconnaît votre forfait et place la demande devant les demandes standard."),
            ("Vous recevez une première réponse plus vite", "Un conseiller prend votre dossier en charge et vous répond avant les demandes ordinaires."),
            ("Le suivi continue jusqu’à la résolution", "Vous restez dans la file rapide jusqu’à ce que le problème soit réglé."),
        ],
        "points": [
            ("Tous les types de problèmes", "Compte, paiement, usurpation, contenu signalé, question technique : l’avantage s’applique à l’ensemble de vos demandes."),
            ("Plus rapide, pas instantané", "Nous ne promettons pas un délai précis : il dépend de la complexité du problème. Ce qui change, c’est que vous passez avant les autres."),
        ],
        "faq": [
            ("Quelle différence avec le support 24/7 ?", "Le support 24/7 vous permet de contacter l’aide à toute heure. Cet avantage fait passer votre demande devant les autres une fois qu’elle est ouverte. Les deux se complètent."),
            ("Dois-je préciser que je suis en forfait supérieur ?", "Non, la priorité est appliquée automatiquement depuis votre compte."),
        ],
    },
    {
        "slug": "visibilite-maximale",
        "titre": "Visibilité maximale (posts, reels, stories)",
        "accroche": "Plus de portée pour vos publications, reels et stories.",
        "icone": "fa-bullhorn",
        "svg": SVG_VISIBILITE_MAX,
        "plans": ["100000"],
        "intro": "Vos publications, reels et stories bénéficient d’une distribution renforcée : elles sont proposées à davantage de personnes, y compris hors de votre cercle d’abonnés habituel.",
        "etapes": [
            ("Vous publiez normalement", "Aucun réglage supplémentaire : l’avantage s’applique à vos posts, reels et stories."),
            ("La distribution est élargie", "FaceNet propose votre contenu à un public plus large, en plus de vos abonnés."),
            ("Le contenu continue à être diffusé selon son accueil", "Si votre contenu plaît, il reste diffusé plus longtemps ; sinon la diffusion ralentit comme pour tout contenu."),
        ],
        "points": [
            ("Une portée accrue, pas fixe", "Nous ne promettons pas un nombre de vues : la portée dépend aussi de la qualité et de l’intérêt du contenu."),
            ("Contenus conformes uniquement", "Un contenu qui enfreint les règles de la communauté n’est pas mis en avant."),
        ],
        "faq": [
            ("Puis-je suivre l’effet du boost ?", "Les statistiques de vos publications vous permettent de comparer la portée avant et après activation."),
        ],
    },
    {
        "slug": "support-email",
        "titre": "Support prioritaire par e-mail",
        "accroche": "Vos demandes passent en priorité.",
        "icone": "fa-envelope",
        "svg": SVG_SUPPORT_EMAIL,
        "plans": ["12000", "78000", "100000"],
        "intro": "Quand vous écrivez au support depuis votre compte vérifié, votre message est étiqueté prioritaire et traité avant les demandes ordinaires.",
        "etapes": [
            ("Vous écrivez depuis votre compte", "Utilisez le formulaire du Centre d’aide ou l’adresse de support en étant connecté."),
            ("Votre demande est étiquetée prioritaire", "Le système reconnaît votre forfait et place le message en tête de file."),
            ("Un conseiller vous répond par e-mail", "Vous recevez une réponse dans l’ordre de priorité, avec un suivi jusqu’à la résolution."),
        ],
        "points": [
            ("Un seul fil par demande", "Toutes les réponses restent regroupées dans la même conversation."),
            ("Précisez votre problème", "Plus votre message est précis (captures, heure, appareil), plus la résolution est rapide."),
        ],
        "faq": [
            ("Quel est le délai de réponse ?", "Les demandes prioritaires sont traitées avant les autres ; le délai exact dépend de la complexité du dossier."),
        ],
    },
    {
        "slug": "support-24-7",
        "titre": "Support 24/7",
        "accroche": "Une aide disponible à toute heure.",
        "icone": "fa-headset",
        "svg": SVG_SUPPORT_247,
        "plans": ["78000", "100000"],
        "variantes": [
            ("Forfait Max", "Assistant IA", "Un assistant IA répond à toute heure, instantanément, aux questions courantes et vous guide dans les démarches. Pour les cas complexes, il transmet votre dossier à l’équipe."),
            ("Forfait Max Plus", "Conseiller humain", "Un conseiller humain vous répond à toute heure, y compris la nuit et les jours fériés."),
        ],
        "intro": "Un problème n’attend pas les heures de bureau. Ce support est joignable jour et nuit : par un assistant IA avec le forfait Max, par un conseiller humain avec le forfait Max Plus.",
        "etapes": [
            ("Vous ouvrez la conversation d’aide", "Depuis le Centre d’aide de votre compte vérifié."),
            ("Vous êtes pris en charge", "Selon votre forfait : assistant IA (Max) ou conseiller humain (Max Plus)."),
            ("Votre demande est résolue ou escaladée", "Si l’assistant ne peut pas résoudre, il transmet à l’équipe avec le contexte pour éviter de répéter."),
        ],
        "points": [
            ("Transparence", "Quand vous parlez à un assistant IA, c’est clairement indiqué."),
            ("Confidentialité", "Les échanges servent uniquement à traiter votre demande, selon la Politique de confidentialité."),
        ],
        "faq": [
            ("Puis-je demander un humain avec le forfait Max ?", "L’assistant peut escalader les cas complexes vers l’équipe. Le conseiller humain disponible à toute heure est inclus dans Max Plus."),
        ],
    },
    {
        "slug": "statistiques-avancees",
        "titre": "Statistiques avancées de votre profil",
        "accroche": "Comprenez qui vous voit et ce qui fonctionne.",
        "icone": "fa-chart-line",
        "svg": SVG_STATS,
        "plans": ["100000"],
        "intro": "Un tableau de bord détaillé sur votre profil : combien de personnes vous voient, combien vous suivent, et quelles publications, reels et stories marchent le mieux.",
        "etapes": [
            ("Vous ouvrez votre tableau de bord", "Il est accessible depuis votre profil dès que le forfait Max Plus est actif."),
            ("Vous consultez vos chiffres", "Vues du profil, portée de vos publications, nouveaux abonnés et interactions, jour après jour."),
            ("Vous comparez les périodes", "Vous voyez ce qui progresse ou baisse d’une semaine ou d’un mois à l’autre."),
            ("Vous ajustez votre contenu", "Vous repérez les publications qui plaisent le plus et publiez davantage dans ce sens."),
        ],
        "points": [
            ("Des totaux, pas des identités", "Vous voyez des chiffres globaux. FaceNet ne révèle pas quelles personnes précises ont consulté votre profil."),
            ("Des données sur votre compte uniquement", "Les statistiques portent sur votre activité et vos contenus, jamais sur ceux d’autres comptes."),
        ],
        "faq": [
            ("Les chiffres sont-ils en temps réel ?", "Ils sont mis à jour régulièrement ; un léger décalage est possible."),
            ("Depuis quand les statistiques sont-elles disponibles ?", "À partir de l’activation du forfait."),
        ],
    },
    {
        "slug": "protection-renforcee",
        "titre": "Protection renforcée du compte",
        "accroche": "Une sécurité supplémentaire pour votre compte.",
        "icone": "fa-user-shield",
        "svg": SVG_PROTECTION_RENFORCEE,
        "plans": ["78000", "100000"],
        "intro": "Un compte vérifié est une cible. Cette protection ajoute des contrôles de sécurité pour réduire le risque de piratage et vous alerter vite en cas d’activité inhabituelle.",
        "etapes": [
            ("Surveillance des connexions", "Les connexions depuis un nouvel appareil ou un lieu inhabituel sont repérées."),
            ("Confirmation en cas de doute", "Une connexion suspecte déclenche une vérification supplémentaire avant d’accorder l’accès."),
            ("Alerte et récupération facilitée", "Vous êtes alerté et guidé pour sécuriser votre compte si besoin."),
        ],
        "points": [
            ("Alertes de sécurité", "Vous êtes prévenu en cas de changement sensible : mot de passe, e-mail, numéro de téléphone."),
            ("Récupération assistée", "En cas de perte d’accès, votre statut vérifié accélère la récupération du compte."),
        ],
        "limites": "Cette protection réduit les risques mais ne remplace pas les bonnes pratiques : mot de passe unique et solide, ne jamais partager vos codes de vérification.",
        "faq": [
            ("Dois-je activer quelque chose ?", "Les protections s’appliquent automatiquement avec le forfait. Vous pouvez aussi renforcer votre mot de passe dans les paramètres."),
        ],
    },
    {
        "slug": "evenements-exclusifs",
        "titre": "Invitations à des événements exclusifs",
        "accroche": "Accès à des événements réservés.",
        "icone": "fa-ticket",
        "svg": SVG_EVENEMENTS,
        "plans": ["100000"],
        "intro": "Les membres Max Plus sont invités à des rencontres organisées par FaceNet : lancements, ateliers pour créateurs, rencontres avec l’équipe.",
        "etapes": [
            ("Vous recevez une invitation", "Dans vos notifications et par e-mail, avec la date, le lieu ou le lien."),
            ("Vous confirmez votre présence", "Les places peuvent être limitées : la confirmation réserve votre accès."),
            ("Vous participez", "Sur place ou en ligne selon l’événement."),
        ],
        "points": [
            ("Nombre d’événements variable", "Les événements dépendent de notre programmation ; nous ne garantissons pas un nombre fixe par mois."),
            ("Accès réservé", "L’invitation est personnelle et liée à votre compte vérifié."),
        ],
        "faq": [
            ("Les frais de déplacement sont-ils pris en charge ?", "Sauf mention contraire dans l’invitation, ils restent à la charge du participant."),
        ],
    },
]

AVANTAGES_PAR_SLUG = {a["slug"]: a for a in AVANTAGES}


# ───────────────────────── Pages légales ─────────────────────────
# Chaque section : (titre, [paragraphes], [puces] ou None)
PAGES_LEGALES = {
    "conditions": {
        "titre": "Conditions d’utilisation",
        "icone": "fa-file-contract",
        "resume": "Les règles qui s’appliquent à l’utilisation de FaceNet et du service Tsapi Verified.",
        "sections": [
            ("1. Objet et acceptation", [
                "Les présentes Conditions encadrent l’utilisation de FaceNet et du service d’abonnement Tsapi Verified (badge de vérification et avantages associés). En continuant vers le paiement, vous déclarez avoir lu et accepté ces Conditions, la Politique de confidentialité et la Politique de remboursement.",
            ], None),
            ("2. Conditions pour souscrire", [
                "Pour souscrire à un forfait Tsapi Verified, vous devez :",
            ], [
                "avoir l’âge légal de conclure un contrat dans votre pays, ou disposer de l’accord de votre représentant légal ;",
                "détenir un compte FaceNet à votre véritable identité ;",
                "fournir des informations exactes, complètes et à jour ;",
                "utiliser un moyen de paiement dont vous êtes le titulaire ou que vous êtes autorisé à utiliser.",
            ]),
            ("3. Les forfaits", [
                "Quatre forfaits sont proposés : Standard (4 500 FCFA/mois), Premium (12 000 FCFA/mois), Max (78 000 FCFA/mois) et Max Plus (100 000 FCFA/mois). Le contenu de chaque forfait est détaillé sur la page de souscription et dans la page de détail de chaque avantage.",
                "Nous pouvons faire évoluer le contenu des forfaits ; en cas de modification défavorable, vous en êtes informé à l’avance et pouvez résilier sans frais supplémentaires.",
            ], None),
            ("4. Vérification d’identité", [
                "L’attribution du badge dépend d’un processus de vérification : informations de profil, photo, pièce d’identité et scan du visage. Le paiement d’un forfait n’emporte pas attribution automatique du badge : celui-ci n’est accordé que si la vérification aboutit.",
                "Nous pouvons refuser ou retirer un badge si les documents sont falsifiés, si les informations sont inexactes, ou si le compte enfreint les règles de la communauté.",
            ], None),
            ("5. Paiement et renouvellement", [
                "Les prix sont indiqués en francs CFA (XAF/XOF selon le pays). Le paiement est effectué par Mobile Money, carte bancaire ou PayPal via des prestataires de paiement tiers.",
                "Le forfait est mensuel. Sauf résiliation avant la date de renouvellement, il se renouvelle à la même date chaque mois. Vous pouvez résilier à tout moment ; la résiliation prend effet à la fin de la période déjà payée.",
            ], None),
            ("6. Votre responsabilité", [
                "Vous êtes responsable de l’usage de votre compte et de la confidentialité de vos identifiants. Vous vous engagez à ne pas :",
            ], [
                "usurper l’identité d’une autre personne ou fournir de faux documents ;",
                "revendre, louer ou transférer votre badge ou votre compte ;",
                "utiliser le badge pour tromper, harceler ou escroquer d’autres membres ;",
                "contourner les mesures de sécurité de la plateforme.",
            ]),
            ("7. Nos engagements et leurs limites", [
                "Nous mettons en œuvre des moyens raisonnables pour fournir les avantages décrits. Certains avantages (visibilité, portée, délai de traitement) dépendent de facteurs hors de notre contrôle et ne constituent pas des résultats garantis.",
                "Le service est fourni « en l’état » dans la mesure permise par la loi. Notre responsabilité est limitée aux dommages directs et prévisibles, sans que le total puisse dépasser les sommes payées au cours des douze derniers mois, sauf disposition légale contraire.",
            ], None),
            ("8. Suspension et fin du service", [
                "Nous pouvons suspendre ou retirer un forfait en cas de violation grave des Conditions, de fraude ou d’obligation légale. Sauf faute de votre part, la période déjà payée et non utilisée peut donner lieu à remboursement selon la Politique de remboursement.",
            ], None),
            ("9. Propriété intellectuelle", [
                "La marque FaceNet, le badge Tsapi Verified, le logo et les éléments du service sont protégés. Vous conservez vos droits sur vos contenus et nous accordez la licence nécessaire à leur affichage dans le service.",
            ], None),
            ("10. Droit applicable et litiges", [
                "Les présentes Conditions sont régies par le droit applicable au Cameroun, sans préjudice des règles impératives de protection des consommateurs de votre pays de résidence. Avant toute action, nous vous invitons à contacter le support pour rechercher une solution amiable.",
            ], None),
            ("11. Modification et contact", [
                "Nous pouvons mettre à jour ces Conditions. Les changements importants vous sont notifiés avant leur entrée en vigueur. Pour toute question : " + EMAIL_SUPPORT + ".",
            ], None),
        ],
    },
    "confidentialite": {
        "titre": "Politique de confidentialité",
        "icone": "fa-user-lock",
        "resume": "Quelles données nous collectons, pourquoi, combien de temps, et comment les protéger.",
        "sections": [
            ("1. Qui est responsable de vos données", [
                "FaceNet est responsable du traitement des données collectées dans le cadre de Tsapi Verified. Pour toute demande liée à vos données : " + EMAIL_PRIVACY + ".",
            ], None),
            ("2. Les données que nous collectons", [], [
                "Compte et profil : nom, nom d’utilisateur, e-mail, numéro de téléphone, photo de profil.",
                "Vérification d’identité : photo, copie de la pièce d’identité, données extraites du document, images du scan du visage.",
                "Paiement : forfait choisi, montant, devise, opérateur Mobile Money, numéro de téléphone, adresse e-mail PayPal, adresse de facturation. Les données complètes de carte bancaire sont traitées par le prestataire de paiement ; FaceNet ne conserve pas votre numéro complet ni votre code CVV.",
                "Utilisation et sécurité : journaux de connexion, appareil, adresse IP, signalements.",
            ]),
            ("3. Pourquoi nous les utilisons", [], [
                "Vérifier votre identité et attribuer le badge ;",
                "Traiter vos paiements et gérer votre abonnement ;",
                "Détecter les usurpations d’identité, la fraude et les abus ;",
                "Vous fournir le support et les avantages de votre forfait ;",
                "Respecter nos obligations légales.",
            ]),
            ("4. Données de vérification : un traitement renforcé", [
                "Votre pièce d’identité et votre scan du visage sont des données particulièrement sensibles. Ils servent uniquement à la vérification et à la lutte contre l’usurpation, ne sont jamais affichés publiquement et ne sont jamais utilisés à des fins publicitaires. Leur accès est limité au personnel habilité.",
            ], None),
            ("5. Avec qui nous les partageons", [
                "Nous partageons des données uniquement lorsque c’est nécessaire : prestataires de paiement (Mobile Money, cartes, PayPal), prestataires techniques d’hébergement ou de vérification, et autorités lorsque la loi l’exige. Nous ne vendons pas vos données personnelles.",
            ], None),
            ("6. Durée de conservation", [
                "Les documents de vérification sont conservés le temps nécessaire à la vérification, puis pendant une durée limitée pour la sécurité et le respect des obligations légales, avant suppression ou anonymisation. Les données de paiement et de facturation sont conservées selon les obligations comptables.",
            ], None),
            ("7. Sécurité", [
                "Nous utilisons le chiffrement des échanges, un accès restreint aux données sensibles et des contrôles de sécurité réguliers. Aucun système n’est infaillible : en cas d’incident affectant vos données, nous vous informerons conformément à la loi.",
            ], None),
            ("8. Vos droits", [
                "Vous pouvez demander l’accès à vos données, leur rectification, leur suppression, la limitation ou l’opposition à certains traitements, ainsi que la portabilité, dans les conditions prévues par la loi applicable. Écrivez à " + EMAIL_PRIVACY + " ; nous répondons dans un délai raisonnable après vérification de votre identité.",
            ], None),
            ("9. Cookies", [
                "Nous utilisons des cookies et technologies similaires nécessaires au fonctionnement (session, sécurité, préférences comme le thème clair ou sombre). Vous pouvez les gérer dans votre navigateur.",
            ], None),
            ("10. Mises à jour", [
                "Cette politique peut évoluer. La date de dernière mise à jour figure en haut de la page.",
            ], None),
        ],
    },
    "remboursement": {
        "titre": "Politique de remboursement",
        "icone": "fa-rotate-left",
        "resume": "Dans quels cas vous êtes remboursé, comment en faire la demande et sous quel délai.",
        "sections": [
            ("1. Principe", [
                "Tsapi Verified est un abonnement mensuel. Nous voulons que la règle soit simple : vous êtes remboursé lorsque le service payé n’a pas pu vous être fourni de notre fait, ou en cas d’erreur de facturation.",
            ], None),
            ("2. Cas de remboursement intégral", [], [
                "Votre vérification est refusée pour un motif qui ne vous est pas imputable (par exemple erreur technique de notre côté) ;",
                "Vous avez été débité deux fois, ou d’un montant incorrect ;",
                "Le service n’a pas pu être activé après paiement alors que votre dossier est complet ;",
                "Une suppression ou suspension du badge intervient alors que vous n’avez commis aucune violation des Conditions.",
            ]),
            ("3. Cas sans remboursement", [], [
                "Refus de vérification dû à des documents falsifiés, des informations fausses ou une usurpation d’identité ;",
                "Retrait du badge pour violation des Conditions ou des règles de la communauté ;",
                "Changement d’avis après l’attribution du badge et l’utilisation des avantages durant la période payée ;",
                "Résultats non atteints sur des avantages non garantis (portée, nombre de vues, délai précis).",
            ]),
            ("4. Résiliation", [
                "Vous pouvez résilier à tout moment. La résiliation arrête les renouvellements futurs ; l’accès aux avantages reste actif jusqu’à la fin de la période déjà payée. Une période entamée n’est pas remboursée au prorata, sauf cas prévus à l’article 2.",
            ], None),
            ("5. Comment demander un remboursement", [
                "Écrivez à " + EMAIL_SUPPORT + " depuis l’adresse liée à votre compte en indiquant :",
            ], [
                "votre nom d’utilisateur ;",
                "la date et le montant du paiement ;",
                "le moyen de paiement utilisé (Mobile Money, carte, PayPal) ;",
                "le motif de votre demande.",
            ]),
            ("6. Délais et mode de remboursement", [
                "Nous répondons à votre demande dans un délai raisonnable. Le remboursement approuvé est effectué par le même moyen de paiement que celui utilisé à l’origine. Le délai d’arrivée des fonds dépend ensuite de l’opérateur Mobile Money, de la banque ou de PayPal.",
            ], None),
            ("7. Litiges de paiement", [
                "Avant d’ouvrir une contestation auprès de votre banque ou de votre opérateur, nous vous invitons à nous contacter : nous pourrons souvent régler le problème plus rapidement.",
            ], None),
        ],
    },
    "aide": {
        "titre": "En savoir plus et aide",
        "icone": "fa-circle-question",
        "resume": "Comprendre Tsapi Verified, le parcours de vérification et comment obtenir de l’aide.",
        "sections": [
            ("Qu’est-ce que Tsapi Verified ?", [
                "Tsapi Verified est le service de vérification de FaceNet. Il confirme que votre compte appartient bien à vous et vous donne un badge bleu visible par tous, ainsi que des avantages selon le forfait choisi.",
            ], None),
            ("Le parcours en 5 étapes", [], [
                "1. Forfait et paiement : choisissez votre forfait et réglez par Mobile Money, carte ou PayPal.",
                "2. Profil : vérifiez les informations de votre profil.",
                "3. Photo : fournissez une photo claire de votre visage.",
                "4. Pièce : présentez une pièce d’identité en cours de validité.",
                "5. Scan : un scan du visage confirme que vous êtes bien le titulaire de la pièce.",
            ]),
            ("Quel forfait choisir ?", [
                "Standard suffit pour obtenir le badge et la protection contre l’usurpation. Premium ajoute la recherche prioritaire et le support e-mail. Max apporte la réponse plus rapide à tous vos problèmes, le support 24/7 par assistant IA et la protection renforcée. Max Plus inclut tous les avantages, dont la visibilité maximale, le support 24/7 par conseiller humain, les statistiques avancées et les événements exclusifs.",
            ], None),
            ("Moyens de paiement acceptés", [], [
                "Mobile Money (MTN, Orange Money, Moov, Wave, Airtel Money… selon le pays) ;",
                "Cartes Visa, Mastercard, American Express et Discover ;",
                "PayPal.",
            ]),
            ("Sécurité de vos informations", [
                "Les paiements sont chiffrés. Vos documents d’identité ne sont jamais affichés publiquement. Pour le détail, consultez la Politique de confidentialité.",
            ], None),
            ("Besoin de contacter quelqu’un ?", [
                "Écrivez-nous à " + EMAIL_SUPPORT + ". Selon votre forfait, vous bénéficiez d’un support prioritaire par e-mail, d’un support 24/7 ou d’une réponse plus rapide à vos problèmes.",
            ], None),
        ],
    },
}

ORDRE_PAGES_LEGALES = ["conditions", "confidentialite", "remboursement", "aide"]