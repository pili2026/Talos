// ===== i18n (Internationalization) Module =====

let currentLang = localStorage.getItem(CONFIG.STORAGE_KEYS.LANGUAGE) || 'zh-TW';

/**
 * Get translated text by key
 * @param {string} key - Translation key (e.g., 'header.title')
 * @returns {string} Translated text
 */
function t(key) {
    const keys = key.split('.');
    let value = i18n[currentLang];
    
    for (const k of keys) {
        value = value[k];
        if (!value) return key;
    }
    
    return value;
}

/**
 * Change application language
 * @param {string} lang - Language code ('zh-TW' or 'en')
 */
function changeLanguage(lang) {
    currentLang = lang;
    localStorage.setItem(CONFIG.STORAGE_KEYS.LANGUAGE, lang);
    updateLanguage();
    
    // Update language button states
    document.getElementById('btnZhTW').classList.toggle('active', lang === 'zh-TW');
    document.getElementById('btnEn').classList.toggle('active', lang === 'en');
}

/**
 * Update all UI text elements with current language
 */
function updateLanguage() {
    // Update all elements with data-i18n attribute
    document.querySelectorAll('[data-i18n]').forEach(element => {
        const key = element.getAttribute('data-i18n');
        const text = t(key);
        
        if (element.tagName === 'OPTION') {
            element.textContent = text;
        } else if (element.hasAttribute('data-i18n-placeholder')) {
            // Skip, will be handled separately
        } else {
            element.textContent = text;
        }
    });

    // Update placeholders
    document.querySelectorAll('[data-i18n-placeholder]').forEach(element => {
        const key = element.getAttribute('data-i18n-placeholder');
        element.placeholder = t(key);
    });

    // Update select options
    const modeSelect = document.getElementById('monitorMode');
    if (modeSelect) {
        modeSelect.options[0].textContent = t('connection.singleDevice');
        modeSelect.options[1].textContent = t('connection.multipleDevices');
    }

    // Update connection status if needed
    if (window.ws) {
        updateConnectionStatus(window.ws.readyState === WebSocket.OPEN);
    }
}

/**
 * Get locale string for date/time formatting
 * @returns {string} Locale string
 */
function getLocale() {
    return currentLang === 'zh-TW' ? 'zh-TW' : 'en-US';
}