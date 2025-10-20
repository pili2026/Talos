// ===== WebSocket Module =====

let ws = null;
let messageCount = 0;
let sentCount = 0;
let errorCount = 0;
let latestData = {};

/**
 * Connect to WebSocket server
 */
function connect() {
    const mode = document.getElementById('monitorMode').value;
    const baseUrl = document.getElementById('wsUrl').value;
    const interval = document.getElementById('interval').value;
    const parameters = document.getElementById('parameters').value;

    let url;
    if (mode === 'single') {
        const deviceId = document.getElementById('deviceId').value.trim();
        if (!deviceId) {
            addLog(t('messages.enterDeviceId'), 'error');
            return;
        }
        url = `${baseUrl}/api/monitoring/device/${deviceId}?interval=${interval}`;
    } else {
        const deviceIds = document.getElementById('deviceIds').value.trim();
        if (!deviceIds) {
            addLog(t('messages.enterDeviceIds'), 'error');
            return;
        }
        url = `${baseUrl}/api/monitoring/devices?device_ids=${deviceIds}&interval=${interval}`;
    }

    if (parameters) {
        url += `&parameters=${parameters}`;
    }

    addLog(`${t('messages.connecting')}: ${url}`, 'info');

    try {
        ws = new WebSocket(url);

        ws.onopen = function() {
            addLog(t('messages.connected'), 'success');
            updateConnectionStatus(true);
        };

        ws.onmessage = function(event) {
            messageCount++;
            updateStats();
            
            try {
                const data = JSON.parse(event.data);
                handleMessage(data);
            } catch (e) {
                addLog(`${t('messages.parseError')}: ${e.message}`, 'error');
            }
        };

        ws.onerror = function(error) {
            errorCount++;
            updateStats();
            addLog(`${t('messages.error')}: ${error}`, 'error');
        };

        ws.onclose = function() {
            addLog(t('messages.disconnected'), 'warning');
            updateConnectionStatus(false);
        };

    } catch (e) {
        addLog(`${t('messages.connectionError')}: ${e.message}`, 'error');
        errorCount++;
        updateStats();
    }
}

/**
 * Disconnect from WebSocket server
 */
function disconnect() {
    if (ws) {
        ws.close();
        ws = null;
        addLog(t('messages.manualDisconnect'), 'info');
        updateConnectionStatus(false);
    }
}

/**
 * Write parameter to device
 */
function writeParameter() {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
        addLog(t('messages.connectFirst'), 'error');
        return;
    }

    const parameter = document.getElementById('controlParam').value.trim().toUpperCase();
    const value = parseFloat(document.getElementById('controlValue').value);
    const force = document.getElementById('forceWrite').checked;

    if (!parameter || isNaN(value)) {
        addLog(t('messages.enterValidParams'), 'error');
        return;
    }

    const message = {
        action: 'write',
        parameter: parameter,
        value: value,
        force: force
    };

    ws.send(JSON.stringify(message));
    sentCount++;
    updateStats();
    addLog(`${t('messages.sendingWrite')}: ${parameter} = ${value} (force=${force})`, 'info');
}

/**
 * Send ping to server
 */
function sendPing() {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
        addLog(t('messages.connectFirst'), 'error');
        return;
    }

    ws.send(JSON.stringify({ action: 'ping' }));
    sentCount++;
    updateStats();
    addLog(t('messages.sendingPing'), 'info');
}

/**
 * Handle incoming WebSocket message
 * @param {Object} data - Parsed message data
 */
function handleMessage(data) {
    const type = data.type;

    switch(type) {
        case 'connected':
            addLog(`${t('messages.deviceConnected')}: ${JSON.stringify(data.device_id || data.device_ids)}`, 'success');
            addLog(`${t('messages.monitoringParams')}: ${JSON.stringify(data.parameters)}`, 'info');
            break;

        case 'data':
            updateDataDisplay(data);
            break;

        case 'write_result':
            if (data.success) {
                addLog(`${t('messages.writeSuccess')}: ${data.parameter} = ${data.new_value}`, 'success');
            } else {
                addLog(`${t('messages.writeFailed')}: ${data.error}`, 'error');
                errorCount++;
                updateStats();
            }
            break;

        case 'pong':
            addLog(t('messages.receivedPong'), 'success');
            break;

        case 'error':
            addLog(`${t('messages.error')}: ${data.message}`, 'error');
            errorCount++;
            updateStats();
            break;

        default:
            addLog(`${t('messages.unknownMessage')}: ${type}`, 'warning');
    }
}

/**
 * Get WebSocket statistics
 * @returns {Object} Statistics object
 */
function getStats() {
    return {
        messageCount,
        sentCount,
        errorCount
    };
}

/**
 * Reset statistics
 */
function resetStats() {
    messageCount = 0;
    sentCount = 0;
    errorCount = 0;
    updateStats();
}

// Export to global scope for HTML onclick handlers
window.ws = ws;
window.connect = connect;
window.disconnect = disconnect;
window.writeParameter = writeParameter;
window.sendPing = sendPing;