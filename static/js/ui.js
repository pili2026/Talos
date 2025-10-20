// ===== UI Update Module =====

/**
 * Update connection status display
 * @param {boolean} connected - Connection status
 */
function updateConnectionStatus(connected) {
    const status = document.getElementById('connectionStatus');
    const disconnectBtn = document.getElementById('disconnectBtn');
    const writeBtn = document.getElementById('writeBtn');
    const pingBtn = document.getElementById('pingBtn');

    if (connected) {
        status.textContent = t('header.connected');
        status.className = 'status connected';
        disconnectBtn.disabled = false;
        writeBtn.disabled = false;
        pingBtn.disabled = false;
    } else {
        status.textContent = t('header.disconnected');
        status.className = 'status disconnected';
        disconnectBtn.disabled = true;
        writeBtn.disabled = true;
        pingBtn.disabled = true;
    }
}

/**
 * Update statistics display
 */
function updateStats() {
    const stats = getStats();
    document.getElementById('messageCount').textContent = stats.messageCount;
    document.getElementById('sentCount').textContent = stats.sentCount;
    document.getElementById('errorCount').textContent = stats.errorCount;
}

/**
 * Update real-time data display
 * @param {Object} data - Data from WebSocket
 */
function updateDataDisplay(data) {
    const display = document.getElementById('dataDisplay');
    
    // Store latest data
    if (data.device_id) {
        latestData[data.device_id] = data.data;
    } else if (data.devices) {
        latestData = data.devices;
    }

    // Render
    let html = '';
    for (const [deviceId, params] of Object.entries(latestData)) {
        html += `<div class="data-item">`;
        html += `<div class="timestamp">${new Date().toLocaleTimeString(getLocale())}</div>`;
        html += `<div class="device-id">${deviceId}</div>`;
        
        for (const [paramName, paramData] of Object.entries(params)) {
            html += `<div class="param">`;
            html += `<span class="param-name">${paramName}</span>`;
            html += `<span class="param-value">${paramData.value} ${paramData.unit || ''}</span>`;
            html += `</div>`;
        }
        
        html += `</div>`;
    }

    display.innerHTML = html || `<p style="color: #9ca3af;">${t('data.noData')}</p>`;
    // display.scrollTop = display.scrollHeight;
}

/**
 * Add log entry
 * @param {string} message - Log message
 * @param {string} type - Log type (info, success, error, warning)
 */
function addLog(message, type = 'info') {
    const logs = document.getElementById('logs');
    const timestamp = new Date().toLocaleTimeString(getLocale());
    const log = document.createElement('div');
    log.className = `log-entry ${type}`;
    log.textContent = `[${timestamp}] ${message}`;
    logs.appendChild(log);
    logs.scrollTop = logs.scrollHeight;
}

/**
 * Clear data display
 */
function clearData() {
    latestData = {};
    document.getElementById('dataDisplay').innerHTML = `<p style="color: #9ca3af;">${t('messages.dataCleared')}</p>`;
}

/**
 * Clear logs
 */
function clearLogs() {
    document.getElementById('logs').innerHTML = '';
    addLog(t('logs.cleared'), 'info');
}

// Export to global scope for HTML onclick handlers
window.updateConnectionStatus = updateConnectionStatus;
window.updateStats = updateStats;
window.updateDataDisplay = updateDataDisplay;
window.addLog = addLog;
window.clearData = clearData;
window.clearLogs = clearLogs;