// ===== Application Configuration =====

// i18n translations
const i18n = {
    'zh-TW': {
        header: {
            title: 'WebSocket 設備監控測試',
            connected: '● 已連接',
            disconnected: '● 未連接'
        },
        connection: {
            title: '連接設定',
            mode: '監控模式',
            singleDevice: '單一設備監控',
            multipleDevices: '多設備監控',
            wsUrl: 'WebSocket URL',
            deviceId: '設備 ID',
            deviceIdPlaceholder: '例如: IMA_C_5',
            deviceIds: '設備 ID 列表 (逗號分隔)',
            deviceIdsPlaceholder: '例如: IMA_C_5,SD400_3',
            parameters: '參數列表 (可選，逗號分隔)',
            parametersPlaceholder: '留空=監控所有參數',
            interval: '更新間隔 (秒)',
            connect: '連接',
            disconnect: '中斷連接'
        },
        control: {
            title: '設備控制',
            parameter: '參數名稱',
            parameterPlaceholder: '例如: DOut01',
            value: '設定值',
            valuePlaceholder: '例如: 1',
            force: '強制寫入 (force)',
            write: '寫入參數',
            ping: '發送 Ping'
        },
        stats: {
            title: '統計資訊',
            messageCount: '收到訊息',
            sentCount: '發送命令',
            errorCount: '錯誤次數'
        },
        data: {
            title: '即時數據',
            clear: '清除',
            waiting: '等待連接...',
            noData: '無數據'
        },
        logs: {
            title: '系統日誌',
            clear: '清除',
            cleared: '日誌已清除',
            pageLoaded: 'WebSocket 測試頁面已載入'
        },
        messages: {
            enterDeviceId: '請輸入設備 ID',
            enterDeviceIds: '請輸入設備 ID 列表',
            connecting: '正在連接',
            connected: '✓ WebSocket 連接成功',
            disconnected: '連接已關閉',
            manualDisconnect: '手動中斷連接',
            error: '✗ WebSocket 錯誤',
            connectionError: '連接失敗',
            parseError: '解析訊息失敗',
            connectFirst: '請先連接 WebSocket',
            enterValidParams: '請輸入有效的參數名稱和值',
            sendingWrite: '→ 發送寫入命令',
            writeSuccess: '✓ 寫入成功',
            writeFailed: '✗ 寫入失敗',
            writeException: '寫入異常',
            sendingPing: '→ 發送 Ping',
            receivedPong: '← 收到 Pong',
            unknownMessage: '收到未知訊息類型',
            deviceConnected: '已連接設備',
            monitoringParams: '監控參數',
            dataCleared: '已清除數據'
        }
    },
    'en': {
        header: {
            title: 'WebSocket Device Monitor Test',
            connected: '● Connected',
            disconnected: '● Disconnected'
        },
        connection: {
            title: 'Connection Settings',
            mode: 'Monitor Mode',
            singleDevice: 'Single Device',
            multipleDevices: 'Multiple Devices',
            wsUrl: 'WebSocket URL',
            deviceId: 'Device ID',
            deviceIdPlaceholder: 'e.g., IMA_C_5',
            deviceIds: 'Device IDs (comma separated)',
            deviceIdsPlaceholder: 'e.g., IMA_C_5,SD400_3',
            parameters: 'Parameters (optional, comma separated)',
            parametersPlaceholder: 'Leave empty to monitor all',
            interval: 'Update Interval (seconds)',
            connect: 'Connect',
            disconnect: 'Disconnect'
        },
        control: {
            title: 'Device Control',
            parameter: 'Parameter Name',
            parameterPlaceholder: 'e.g., DOut01',
            value: 'Value',
            valuePlaceholder: 'e.g., 1',
            force: 'Force Write',
            write: 'Write Parameter',
            ping: 'Send Ping'
        },
        stats: {
            title: 'Statistics',
            messageCount: 'Messages Received',
            sentCount: 'Commands Sent',
            errorCount: 'Errors'
        },
        data: {
            title: 'Real-time Data',
            clear: 'Clear',
            waiting: 'Waiting for connection...',
            noData: 'No data'
        },
        logs: {
            title: 'System Logs',
            clear: 'Clear',
            cleared: 'Logs cleared',
            pageLoaded: 'WebSocket test page loaded'
        },
        messages: {
            enterDeviceId: 'Please enter device ID',
            enterDeviceIds: 'Please enter device IDs',
            connecting: 'Connecting to',
            connected: '✓ WebSocket connected successfully',
            disconnected: 'Connection closed',
            manualDisconnect: 'Manually disconnected',
            error: '✗ WebSocket error',
            connectionError: 'Connection failed',
            parseError: 'Failed to parse message',
            connectFirst: 'Please connect WebSocket first',
            enterValidParams: 'Please enter valid parameter name and value',
            sendingWrite: '→ Sending write command',
            writeSuccess: '✓ Write successful',
            writeFailed: '✗ Write failed',
            writeException: 'Write exception',
            sendingPing: '→ Sending Ping',
            receivedPong: '← Received Pong',
            unknownMessage: 'Received unknown message type',
            deviceConnected: 'Connected to device',
            monitoringParams: 'Monitoring parameters',
            dataCleared: 'Data cleared'
        }
    }
};

// Application constants
const CONFIG = {
    DEFAULT_WS_URL: 'ws://192.168.213.197:8000',
    DEFAULT_INTERVAL: 1.0,
    MIN_INTERVAL: 0.5,
    MAX_INTERVAL: 60.0,
    STORAGE_KEYS: {
        LANGUAGE: 'language'
    }
};