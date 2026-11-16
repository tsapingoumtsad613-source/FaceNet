// --- Moteur de sons (à ne pas modifier) ---
function jouerSon(type) {
    const audio = new Audio(`/static/sounds/${type}.mp3`);
    audio.play().catch(e => console.log("Le son '" + type + "' n'a pas pu être joué (vérifie s'il est bien dans /static/sounds/)", e));
}

// --- Fonctions d'action (Appelle-les dans tes fonctions de succès) ---
function onLikeSuccess() {
    jouerSon('like');
}

function onPostSuccess() {
    jouerSon('post');
}

function onMessageReceived() {
    jouerSon('message');
}

function onMessageSent() {
    jouerSon('message'); 
}

function onNotificationReceived() {
    jouerSon('notification');
}

function onShareSuccess() {
    jouerSon('share');
}

function changerLangueGlobale(langCode) {
    // 1. Sauvegarde locale instantanée
    localStorage.setItem('app_language', langCode);

    // 2. Envoi de la requête au serveur Flask
    fetch('/update-language', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ language: langCode })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // 3. Déclenchement de la voix interactive mondialement adaptée
            jouerExempleLangue(langCode);
            
            // 4. Recharge la page après 1.5 seconde pour laisser le temps d'entendre la voix
            setTimeout(() => {
                location.reload();
            }, 1500);
        } else {
            console.error("Erreur lors de la mise à jour de la langue.");
        }
    })
    .catch(error => {
        console.error('Erreur réseau:', error);
    });
}

// Fonction de synthèse vocale exhaustive pour le monde entier
function jouerExempleLangue(langCode) {
    if (!('speechSynthesis' in window)) return;

    // Dictionnaire des messages de bienvenue par langue/région
    const messages = {
        'fr': { text: "Bienvenue sur FaceNet", lang: "fr-FR" },
        'en': { text: "Welcome to FaceNet", lang: "en-US" },
        'es': { text: "Bienvenido a FaceNet", lang: "es-ES" },
        'de': { text: "Willkommen bei FaceNet", lang: "de-DE" },
        'pt': { text: "Bem-vindo ao FaceNet", lang: "pt-PT" },
        'ar': { text: "أهلاً بك في تطبيقنا", lang: "ar-SA" },
        'zh': { text: "欢迎来到 FaceNet", lang: "zh-CN" },
        'sw': { text: "Karibu FaceNet", lang: "sw-KE" },
        'it': { text: "Benvenuto su FaceNet", lang: "it-IT" },
        'ru': { text: "Добро пожаловать в FaceNet", lang: "ru-RU" },
        'ja': { text: "FaceNetへようこそ", lang: "ja-JP" },
        'ko': { text: "FaceNet에 오신 것을 환영합니다", lang: "ko-KR" },
        'nl': { text: "Welkom bij FaceNet", lang: "nl-NL" },
        'tr': { text: "FaceNet'e hoş geldiniz", lang: "tr-TR" },
        'hi': { text: "FaceNet में आपका स्वागत है", lang: "hi-IN" },
        'fa': { text: "به FaceNet خوش آمدید", lang: "fa-IR" },
        'pl': { text: "Witaj w FaceNet", lang: "pl-PL" },
        'uk': { text: "Ласкаво просимо до FaceNet", lang: "uk-UA" },
        'vi': { text: "Chào mừng đếnกับ FaceNet", lang: "vi-VN" },
        'id': { text: "Selamat datang di FaceNet", lang: "id-ID" }
    };

    // Extraction du code principal (ex: 'fr' de 'fr-cm' ou 'es' de 'esp')
    let cleLang = langCode.split('-')[0].toLowerCase();
    if (cleLang === 'esp') cleLang = 'es';

    let config = messages[cleLang] || { text: "Welcome to FaceNet", lang: "en-US" };

    const utterance = new SpeechSynthesisUtterance(config.text);
    utterance.lang = config.lang;
    utterance.rate = 1.0;

    // Sélection intelligente de la voix si disponible
    const voices = window.speechSynthesis.getVoices();
    const voixTrouvee = voices.find(v => v.lang.startsWith(config.lang.slice(0, 2)));
    if (voixTrouvee) {
        utterance.voice = voixTrouvee;
    }

    window.speechSynthesis.speak(utterance);
}

// Fonction pour afficher la notification et prononcer le message d'accueil
// Fonction pour afficher la notification et prononcer le message d'accueil
function saluerNouvelUtilisateur(nomUtilisateur) {
    // 1. Affichage de la notification visuelle
    afficherNotificationBienvenue(nomUtilisateur);

    // 2. Synthèse vocale
    if (!('speechSynthesis' in window)) return;

    const langueActive = localStorage.getItem('app_language') || 'fr-cm';
    let bcpLang = "fr-FR";
    let messageBienvenue = `Bienvenue ${nomUtilisateur} sur FaceNet`;

    if (langueActive.includes('en')) {
        bcpLang = "en-US";
        messageBienvenue = `Welcome ${nomUtilisateur} to FaceNet`;
    } else if (langueActive.includes('es') || langueActive.includes('esp')) {
        bcpLang = "es-ES";
        messageBienvenue = `Bienvenido ${nomUtilisateur} a FaceNet`;
    }

    const utterance = new SpeechSynthesisUtterance(messageBienvenue);
    utterance.lang = bcpLang;
    utterance.rate = 1.0;
    window.speechSynthesis.speak(utterance);
}

// Fonction utilitaire pour créer et afficher un encadré de notification élégant
function afficherNotificationBienvenue(nom) {
    const existingNotification = document.getElementById('welcome-notification');
    if (existingNotification) existingNotification.remove();

    const notif = document.createElement('div');
    notif.id = 'welcome-notification';
    notif.innerHTML = `🎉 Bienvenue, <strong>${nom}</strong> sur FaceNet !`;
    
    // Style de la notification (discret, moderne, en haut à droite)
    notif.style.position = 'fixed';
    notif.style.top = '75px;'; // Placé juste sous votre header de 60px
    notif.style.right = '20px';
    notif.style.backgroundColor = '#1877f2'; // Utilise le bleu officiel FaceNet de votre CSS
    notif.style.color = 'white';
    notif.style.padding = '12px 20px';
    notif.style.borderRadius = '8px';
    notif.style.boxShadow = '0 4px 12px rgba(0,0,0,0.15)';
    notif.style.zIndex = '9999';
    notif.style.fontFamily = "'Inter', sans-serif";
    notif.style.fontSize = '14px';
    notif.style.transition = 'opacity 0.5s ease';

    document.body.appendChild(notif);

    // Disparaît automatiquement après 4 secondes
    setTimeout(() => {
        notif.style.opacity = '0';
        setTimeout(() => notif.remove(), 500);
    }, 4000);
}

// Fonction utilitaire pour créer et afficher un encadré de notification élégant
function afficherNotificationBienvenue(nom) {
    // Évite de superposer plusieurs notifications
    const existingNotification = document.getElementById('welcome-notification');
    if (existingNotification) existingNotification.remove();

    const notif = document.createElement('div');
    notif.id = 'welcome-notification';
    notif.innerHTML = `🎉 Bienvenue, <strong>${nom}</strong> sur FaceNet !`;
    
    // Style de la notification (discret, moderne, en haut de l'écran)
    notif.style.position = 'fixed';
    notif.style.top = '20px';
    notif.style.right = '20px';
    notif.style.backgroundColor = '#4CAF50';
    notif.style.color = 'white';
    notif.style.padding = '12px 20px';
    notif.style.borderRadius = '8px';
    notif.style.boxShadow = '0 4px 12px rgba(0,0,0,0.15)';
    notif.style.zIndex = '9999';
    notif.style.fontFamily = 'sans-serif';
    notif.style.transition = 'opacity 0.5s ease';

    document.body.appendChild(notif);

    // Disparaît automatiquement après 4 secondes
    setTimeout(() => {
        notif.style.opacity = '0';
        setTimeout(() => notif.remove(), 500);
    }, 4000);
}