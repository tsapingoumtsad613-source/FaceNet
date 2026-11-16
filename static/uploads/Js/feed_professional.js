```javascript
/* Face Net — amélioration progressive de l'interface.
   Ne remplace pas les fonctions existantes du fil d'actualité. */
(function () {
    'use strict';

    function byId(id) {
        return document.getElementById(id);
    }

    /* =========================================
       APERÇU DE L'ÉVÉNEMENT AVANT PUBLICATION
       ========================================= */

    function updateEventPreview() {
        var preview = byId('event-design-preview');

        if (!preview) return;

        var modeInput = document.querySelector(
            'input[name="event-display-mode"]:checked'
        );

        var mode = modeInput ? modeInput.value : 'simple';

        var colorInput = byId('event-text-color');
        var veilInput = byId('event-overlay');
        var titleInput = byId('event-titre-input');

        var color = colorInput ? colorInput.value : '#ffffff';
        var veil = veilInput ? veilInput.value : '0.55';

        var title = titleInput
            ? titleInput.value.trim()
            : '';

        if (!title) {
            title = 'Votre titre apparaîtra ici';
        }

        var image = window.fnEventImageData || null;

        preview.style.color = color;

        if (mode === 'background' && image) {
            preview.style.backgroundImage =
                'linear-gradient(rgba(0,0,0,' + veil + '),' +
                'rgba(0,0,0,' + veil + ')),' +
                'url("' + image.replace(/"/g, '%22') + '")';

            preview.style.backgroundSize = 'cover';
            preview.style.backgroundPosition = 'center';
        } else {
            preview.style.backgroundImage =
                'linear-gradient(135deg,#2458c6,#7552d6)';
        }

        var titleElement = byId('event-preview-title');

        if (titleElement) {
            titleElement.textContent = title;
        }
    }

    /* =========================================
       SÉLECTION ET APERÇU DE LA PHOTO
       ========================================= */

    function initEventPreview() {
        [
            'event-titre-input',
            'event-text-color',
            'event-overlay'
        ].forEach(function (id) {
            var element = byId(id);

            if (element) {
                element.addEventListener(
                    'input',
                    updateEventPreview
                );
            }
        });

        document.querySelectorAll(
            'input[name="event-display-mode"]'
        ).forEach(function (element) {
            element.addEventListener(
                'change',
                updateEventPreview
            );
        });

        var fileInput = byId('event-image-input');

        if (
            fileInput &&
            !fileInput.dataset.fnProfessionalBound
        ) {
            fileInput.dataset.fnProfessionalBound = '1';

            fileInput.addEventListener('change', function () {
                var file = fileInput.files &&
                    fileInput.files[0];

                if (!file) return;

                if (!/^image\//.test(file.type)) {
                    alert('Choisis un fichier image valide.');
                    fileInput.value = '';
                    return;
                }

                if (file.size > 8 * 1024 * 1024) {
                    alert(
                        'Choisis une image de 8 Mo maximum.'
                    );

                    fileInput.value = '';
                    return;
                }

                var reader = new FileReader();

                reader.onload = function () {
                    window.fnEventImageData = reader.result;

                    var imagePreview =
                        byId('event-image-preview');

                    if (imagePreview) {
                        imagePreview.src = reader.result;
                    }

                    var imageWrap =
                        byId('event-image-preview-wrap');

                    if (imageWrap) {
                        imageWrap.hidden = false;
                    }

                    /* Sélectionner automatiquement le mode
                       avec image lorsqu'une photo est choisie. */
                    var backgroundOption =
                        document.querySelector(
                            'input[name="event-display-mode"]' +
                            '[value="background"]'
                        );

                    if (backgroundOption) {
                        backgroundOption.checked = true;
                    }

                    updateEventPreview();
                };

                reader.onerror = function () {
                    alert(
                        'Impossible de lire cette image.'
                    );
                };

                reader.readAsDataURL(file);
            });
        }

        var removeButton = byId('event-image-remove');

        if (
            removeButton &&
            !removeButton.dataset.fnProfessionalBound
        ) {
            removeButton.dataset.fnProfessionalBound = '1';

            removeButton.addEventListener('click', function () {
                window.fnEventImageData = null;

                if (fileInput) {
                    fileInput.value = '';
                }

                var imageWrap =
                    byId('event-image-preview-wrap');

                if (imageWrap) {
                    imageWrap.hidden = true;
                }

                updateEventPreview();
            });
        }

        updateEventPreview();
    }

    /* =========================================
       INITIALISATION
       ========================================= */

    window.addEventListener('DOMContentLoaded', function () {
        initEventPreview();

        document.querySelectorAll('.poll-option').forEach(
            function (button) {
                button.setAttribute(
                    'aria-pressed',
                    button.classList.contains('mine')
                        ? 'true'
                        : 'false'
                );
            }
        );
    });

    /* =========================================
       GESTION DES RÉPONSES DU SERVEUR
       ========================================= */

    window.fnReadJsonResponse = async function (response) {
        var data;

        try {
            data = await response.json();
        } catch (error) {
            throw new Error(
                'Le serveur a renvoyé une réponse inattendue. ' +
                'Actualise la page et réessaie.'
            );
        }

        if (!response.ok || data.success === false) {
            throw new Error(
                data.error ||
                'La demande a échoué. Réessaie.'
            );
        }

        return data;
    };

})();
```