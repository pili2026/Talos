# 新增 API 功能說明

本次更新新增了兩個主要的 API 功能模塊：

## 1. 裝置上下限 API (Device Constraints API)

### 功能說明
提供讀取裝置參數上下限（constraints）的 API，資料來源為 `device_instance_config.yml` 配置檔。

### API Endpoints

#### 1.1 獲取所有裝置的上下限
```http
GET /api/constraints/
```

**回應範例：**
```json
[
  {
    "status": "success",
    "timestamp": "2025-11-18T10:00:00",
    "device_id": "TECO_VFD_3",
    "model": "TECO_VFD",
    "slave_id": "3",
    "constraints": {
      "RW_HZ": {
        "parameter_name": "RW_HZ",
        "min": 40.0,
        "max": 52.0
      }
    },
    "has_custom_constraints": true
  }
]
```

#### 1.2 獲取特定裝置的上下限
```http
GET /api/constraints/{device_id}
```

**參數：**
- `device_id`: 裝置識別碼（格式：`model_slaveId`，例如 `TECO_VFD_3`）

**回應範例：**
```json
{
  "status": "success",
  "timestamp": "2025-11-18T10:00:00",
  "device_id": "TECO_VFD_3",
  "model": "TECO_VFD",
  "slave_id": "3",
  "constraints": {
    "RW_HZ": {
      "parameter_name": "RW_HZ",
      "min": 40.0,
      "max": 52.0
    }
  },
  "has_custom_constraints": true
}
```

### 約束優先級
系統會按照以下優先級合併約束配置：

1. **實例特定約束** (最高優先級) - `instances[slave_id].constraints`
2. **裝置型號預設約束** - `devices[model].default_constraints`
3. **全局預設約束** (最低優先級) - `global_defaults.default_constraints`

---

## 2. WiFi 管理 API (WiFi Management API)

### 功能說明
提供 WiFi 網路掃描、連線、斷線和狀態查詢功能，使用 Linux NetworkManager (nmcli) 實現。

### 系統需求
- Linux 作業系統
- 已安裝 NetworkManager
- `nmcli` 命令可用

### API Endpoints

#### 2.1 掃描 WiFi 網路
```http
GET /api/wifi/scan
```

**回應範例：**
```json
{
  "status": "success",
  "timestamp": "2025-11-18T10:00:00",
  "networks": [
    {
      "ssid": "MyWiFiNetwork",
      "signal_strength": 85,
      "security": "WPA2",
      "in_use": true,
      "bssid": "AA:BB:CC:DD:EE:FF"
    },
    {
      "ssid": "GuestNetwork",
      "signal_strength": 60,
      "security": "Open",
      "in_use": false,
      "bssid": "11:22:33:44:55:66"
    }
  ],
  "total_count": 2,
  "current_ssid": "MyWiFiNetwork"
}
```

#### 2.2 連線至 WiFi 網路
```http
POST /api/wifi/connect
Content-Type: application/json
```

**請求範例：**
```json
{
  "ssid": "MyWiFiNetwork",
  "password": "mypassword123"
}
```

**回應範例：**
```json
{
  "status": "success",
  "timestamp": "2025-11-18T10:00:00",
  "ssid": "MyWiFiNetwork",
  "connected": true,
  "ip_address": "192.168.1.100",
  "message": "Successfully connected to WiFi network"
}
```

**注意：**
- `password` 欄位為選填，用於開放網路時可省略
- 連線逾時時間為 30 秒

#### 2.3 斷開 WiFi 連線
```http
POST /api/wifi/disconnect
```

**回應範例：**
```json
{
  "status": "success",
  "message": "Disconnected from MyWiFiNetwork",
  "previous_ssid": "MyWiFiNetwork"
}
```

#### 2.4 查詢 WiFi 連線狀態
```http
GET /api/wifi/status
```

**回應範例：**
```json
{
  "connected": true,
  "ssid": "MyWiFiNetwork",
  "ip_address": "192.168.1.100"
}
```

---

## 實作細節

### 新增檔案
1. **Service 層**
   - `src/api/service/constraint_service.py` - 約束資料處理
   - `src/api/service/wifi_service.py` - WiFi 操作處理

2. **Router 層**
   - `src/api/router/constraints.py` - 約束 API 路由
   - `src/api/router/wifi.py` - WiFi API 路由

3. **Model 層**
   - `src/api/model/responses.py` - 新增回應模型：
     - `ConstraintInfo`
     - `DeviceConstraintResponse`
     - `WiFiNetwork`
     - `WiFiListResponse`
     - `WiFiConnectionResponse`
   - `src/api/model/requests.py` - 新增請求模型：
     - `WiFiConnectRequest`

### 修改檔案
1. `src/api/app.py` - 註冊新的路由
2. `src/api/dependency.py` - 新增 service 依賴注入
3. `src/api/lifecycle.py` - 保存 `constraint_schema` 至 app.state

---

## 測試建議

### 裝置約束 API 測試
```bash
# 測試獲取所有裝置約束
curl http://localhost:8000/api/constraints/

# 測試獲取特定裝置約束
curl http://localhost:8000/api/constraints/TECO_VFD_3
```

### WiFi API 測試
```bash
# 掃描 WiFi
curl http://localhost:8000/api/wifi/scan

# 查詢狀態
curl http://localhost:8000/api/wifi/status

# 連線 WiFi
curl -X POST http://localhost:8000/api/wifi/connect \
  -H "Content-Type: application/json" \
  -d '{"ssid": "MyNetwork", "password": "password123"}'

# 斷開連線
curl -X POST http://localhost:8000/api/wifi/disconnect
```

---

## 前端整合建議 (Orpheus FE)

### 裝置約束使用場景
1. 在參數設定頁面顯示允許的最小/最大值
2. 在表單驗證中使用約束限制
3. 顯示裝置是否有自訂約束

### WiFi 功能使用場景
1. 設定頁面提供 WiFi 網路列表
2. 顯示當前連線狀態和信號強度
3. 提供網路切換界面
4. 顯示連線後的 IP 地址

### 範例前端代碼 (Vue/React)
```javascript
// 獲取裝置約束
async function getDeviceConstraints(deviceId) {
  const response = await fetch(`/api/constraints/${deviceId}`);
  const data = await response.json();
  return data;
}

// 掃描 WiFi
async function scanWiFi() {
  const response = await fetch('/api/wifi/scan');
  const data = await response.json();
  return data.networks;
}

// 連線 WiFi
async function connectWiFi(ssid, password) {
  const response = await fetch('/api/wifi/connect', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ ssid, password })
  });
  const data = await response.json();
  return data;
}
```

---

## 注意事項

### 裝置約束
- 確保 `device_instance_config.yml` 格式正確
- 約束合併邏輯按照優先級自動處理
- 如果裝置不存在或無約束，將返回 404 錯誤

### WiFi 管理
- 需要 root 權限或 NetworkManager 權限
- 連線操作可能需要較長時間（最多 30 秒）
- 建議在前端實作連線逾時提示
- 不同 Linux 發行版的 NetworkManager 行為可能略有差異

---

## API 文件
啟動 API 服務後，可以訪問自動生成的 Swagger 文件：
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
