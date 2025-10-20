// ===== Main Application Entry Point =====

/**
 * Initialize application
 */
function init() {
    // Initialize language
    updateLanguage();
    
    // Set initial button states
    const lang = localStorage.getItem(CONFIG.STORAGE_KEYS.LANGUAGE) || 'zh-TW';
    document.getElementById('btnZhTW').classList.toggle('active', lang === 'zh-TW');
    document.getElementById('btnEn').classList.toggle('active', lang === 'en');
    
    // Set up event listeners
    setupEventListeners();
    
    // Log initialization
    addLog(t('logs.pageLoaded'), 'info');
}

/**
 * Set up event listeners
 */
function setupEventListeners() {
    // Monitor mode toggle
    const modeSelect = document.getElementById('monitorMode');
    if (modeSelect) {
        modeSelect.addEventListener('change', function(e) {
            if (e.target.value === 'single') {
                document.getElementById('singleDeviceSettings').style.display = 'block';
                document.getElementById('multipleDeviceSettings').style.display = 'none';
            } else {
                document.getElementById('singleDeviceSettings').style.display = 'none';
                document.getElementById('multipleDeviceSettings').style.display = 'block';
            }
        });
    }
}

// Export to global scope
window.changeLanguage = changeLanguage;

// Initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}