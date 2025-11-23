# Talos 工業物聯網監控系統

[![Python](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-green.svg)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

Talos 是一個基於 Python 的工業物聯網（IIoT）監控與控制系統，專為工業環境中的設備管理、數據採集、條件監控和自動化控制而設計。

## ✨ 主要特性

- 🔌 **多協議支持**：支援 Modbus RTU/TCP 等工業通訊協議
- 📊 **即時監控**：異步架構，實現高效的設備狀態監控
- 🚨 **智能告警**：靈活的告警條件配置，支援多重通知管道
- 🎛️ **自動控制**：基於條件的自動化控制邏輯
- ⏰ **時間排程**：支援時間條件觸發的控制策略
- 🌐 **RESTful API**：完整的 FastAPI 服務，支援 WebSocket 實時通訊
- 📧 **多通道通知**：支援 Email、Telegram 等多種通知方式
- 🔧 **模組化設計**：易於擴展的驅動程式和處理器架構

## 📋 系統需求

- Python 3.8+
- 支援的作業系統：Linux、Windows、macOS
- 網路環境（用於遠端設備連接）

## 🚀 快速開始

### 安裝

1. **克隆專案**
   ```bash
   git clone https://github.com/your-org/talos.git
   cd talos
   ```

2. **安裝依賴**
   ```bash
   pip install -r requirements.txt
   ```

3. **配置環境變數**
   ```bash
   cp .env.example .env
   # 編輯 .env 檔案，設定 SMTP、Telegram 等服務的憑證
   ```

4. **配置設備和條件**
   - 編輯 `res/modbus_device.yml` 設定 Modbus 設備
   - 編輯 `res/alert_condition.yml` 設定告警條件
   - 編輯 `res/control_condition.yml` 設定控制條件
   - 編輯 `res/time_condition.yml` 設定時間條件

### 運行

#### 方式 1: 運行主程式（設備監控）

```bash
python src/main.py \
  --alert_config res/alert_condition.yml \
  --control_config res/control_condition.yml \
  --modbus_device res/modbus_device.yml \
  --instance_config res/device_instance_config.yml \
  --sender_config res/sender_config.yml \
  --mail_config res/mail_config.yml \
  --time_config res/time_condition.yml
```

#### 方式 2: 運行 API 服務（開發模式）

```bash
PYTHONPATH=src PYTHONUNBUFFERED=1 uvicorn api.app:app \
  --reload \
  --host 0.0.0.0 \
  --port 8000 \
  --log-level info
```

#### 方式 3: 運行 API 服務（生產模式）

```bash
PYTHONPATH=src PYTHONUNBUFFERED=1 uvicorn api.app:app \
  --host 0.0.0.0 \
  --port 8000 \
  --log-level debug
```

## 📚 API 文件

啟動 API 服務後，可以訪問以下端點：

- **靜態 API 文件（OpenAPI/Swagger）**
  - http://localhost:8000/docs

- **異步監控 API 文件**
  - http://localhost:8000/api/monitoring/doc

- **Modbus 測試工具（WebSocket）**
  - http://localhost:8000/static/index.html

### 主要 API 端點

- `GET /health` - 健康檢查
- `GET /api/devices` - 取得設備列表
- `POST /api/devices/{device_id}/read` - 讀取設備數據
- `GET /api/monitoring/ws` - WebSocket 即時監控
- `GET /api/constraints` - 取得條件約束
- `POST /api/batch/read` - 批次讀取設備數據
- `GET /api/wifi` - WiFi 相關操作
- `GET /api/parameters` - 取得系統參數

## 🏗️ 專案結構

```
Talos/
├── src/
│   ├── api/              # FastAPI 應用
│   │   ├── router/       # API 路由
│   │   ├── service/      # 業務邏輯
│   │   ├── repository/   # 數據存取層
│   │   ├── middleware/   # 中間件
│   │   ├── model/        # 數據模型
│   │   └── util/         # API 工具
│   ├── device/           # 設備驅動程式
│   │   └── generic/      # 通用設備類型
│   ├── evaluator/        # 條件評估器
│   ├── executor/         # 執行器
│   ├── handler/          # 事件處理器
│   ├── model/            # 核心數據模型
│   ├── schema/           # 配置模式
│   ├── sender/           # 通知發送器
│   └── util/             # 核心工具
│       ├── notifier/     # 通知工具
│       ├── pubsub/       # 發布訂閱系統
│       └── factory/      # 工廠模式
├── res/                  # 資源和配置文件
│   ├── driver/           # 設備驅動配置
│   └── template/         # 模板文件
├── static/               # 靜態網頁資源
├── template/             # Email 等模板
├── test/                 # 測試文件
├── logs/                 # 日誌文件
└── bin/                  # 執行腳本
```

## ⚙️ 配置說明

### 設備配置 (`modbus_device.yml`)

定義 Modbus 設備的連接參數和寄存器映射。

```yaml
devices:
  - name: "device_name"
    type: "modbus_tcp"
    host: "192.168.1.100"
    port: 502
    slave_id: 1
```

### 告警條件 (`alert_condition.yml`)

設定觸發告警的條件規則。

```yaml
alerts:
  - name: "temperature_high"
    device: "sensor_01"
    parameter: "temperature"
    condition: "> 80"
    priority: "high"
```

### 控制條件 (`control_condition.yml`)

配置自動化控制邏輯。

```yaml
controls:
  - name: "auto_cooling"
    trigger_condition: "temperature > 75"
    action: "set_fan_speed"
    value: 100
```

### 時間條件 (`time_condition.yml`)

設定基於時間的控制策略。

```yaml
schedules:
  - name: "night_mode"
    cron: "0 22 * * *"
    action: "switch_mode"
    value: "sleep"
```

## 🔔 通知設定

### Email 配置

在 `.env` 檔案中設定 SMTP 參數：

```env
SMTP_HOST=smtp.office365.com
SMTP_PORT=587
SMTP_USERNAME=your-email@example.com
SMTP_PASSWORD=your-password
EMAIL_FROM=your-email@example.com
```

### Telegram 配置

```env
TELEGRAM_BOT_TOKEN=your-bot-token
TELEGRAM_CHAT_ID=your-chat-id
```

## 🔌 支援的設備驅動

- **Advantech ADAM-4117**: 8 通道類比輸入模組
- **A26A**: 工業級感測器
- **JY-DAM0816D**: 數位 I/O 模組
- 更多驅動程式可在 `res/driver/` 目錄中查看

## 🧪 測試

```bash
# 安裝開發依賴
pip install -r requirements-dev.txt

# 運行測試
pytest test/

# 代碼風格檢查
black src/
pylint src/
```

## 📝 日誌

日誌檔案儲存在 `logs/` 目錄下：

- `talos.log` - 主程式日誌
- `api.log` - API 服務日誌
- `device.log` - 設備通訊日誌

## 🛠️ 開發指南

### 新增設備驅動

1. 在 `src/device/` 中創建新的驅動程式類
2. 繼承 `BaseDevice` 並實作必要的方法
3. 在 `res/driver/` 中添加驅動配置
4. 更新 `modbus_device.yml` 以使用新驅動

### 新增 API 端點

1. 在 `src/api/router/` 中創建或更新路由檔案
2. 在 `src/api/service/` 中實作業務邏輯
3. 更新 `src/api/app.py` 註冊新路由

## 🤝 貢獻

歡迎提交問題報告和功能請求！請遵循以下流程：

1. Fork 本專案
2. 創建你的特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交你的修改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 開啟一個 Pull Request

## 📄 授權

本專案採用 MIT 授權 - 詳見 [LICENSE](LICENSE) 文件

## 📧 聯絡方式

- 專案維護者：[Your Name]
- Email: your-email@example.com
- 專案連結：https://github.com/your-org/talos

## 🙏 致謝

- FastAPI - 現代化的 Python Web 框架
- pymodbus - Python Modbus 函式庫
- 所有貢獻者和使用者

---

**注意**：本系統設計用於工業環境，使用前請確保正確配置所有安全參數。
