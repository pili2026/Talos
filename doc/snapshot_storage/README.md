# Snapshot Storage - SQLite持久化系統

## 📋 概述

Snapshot Storage 是 Talos 系統的持久化層，負責將設備快照（snapshots）存儲到 SQLite 資料庫中，提供歷史資料查詢和維護功能。

### 核心功能

- ✅ **自動持久化**：訂閱 `DEVICE_SNAPSHOT` 事件，自動存儲所有設備快照
- ✅ **高效查詢**：支援設備、時間範圍、參數歷史等多種查詢方式
- ✅ **自動清理**：定期刪除過期資料，執行 VACUUM 回收磁碟空間
- ✅ **在線狀態追蹤**：自動判斷設備通訊狀態（online/offline）
- ✅ **錯誤隔離**：資料庫錯誤不影響其他 subscribers

---

## 🏗️ 架構設計

### 組件架構

```
┌─────────────────────────────────────────────────────────────┐
│                     DeviceMonitor                            │
│            (發布 DEVICE_SNAPSHOT 事件)                       │
└─────────────────────────────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                      PubSub (InMemoryPubSub)                 │
└─────────────────────────────────────────────────────────────┘
                             │
                ┌────────────┴────────────┐
                ▼                         ▼
    ┌───────────────────┐      ┌──────────────────┐
    │  LegacySender     │      │ SnapshotSaver    │
    │  Subscriber       │      │ Subscriber       │
    └───────────────────┘      └──────────────────┘
                                        │
                                        ▼
                          ┌──────────────────────────┐
                          │  SnapshotRepository      │
                          │  (CRUD + 維護操作)       │
                          └──────────────────────────┘
                                        │
                                        ▼
                          ┌──────────────────────────┐
                          │  SQLite Database         │
                          │  (snapshots.db)          │
                          └──────────────────────────┘
                                        ▲
                                        │
                          ┌──────────────────────────┐
                          │  SnapshotCleanupTask     │
                          │  (定期清理 + VACUUM)     │
                          └──────────────────────────┘
```

### 資料流程

1. **寫入流程**：
   ```
   DeviceMonitor → PubSub.publish() → SnapshotSaverSubscriber → Repository.insert_snapshot() → SQLite
   ```

2. **查詢流程**（Phase 2 API 使用）：
   ```
   API Request → Repository.get_*() → SQLite → JSON Response
   ```

3. **維護流程**：
   ```
   SnapshotCleanupTask (定時) → Repository.cleanup_old_snapshots() → SQLite DELETE
                               → Repository.vacuum_database() → SQLite VACUUM
   ```

---

## 💾 資料庫 Schema

### Snapshots Table

| Column         | Type      | Description                    | Index |
|----------------|-----------|--------------------------------|-------|
| `id`           | INTEGER   | Primary Key (auto increment)   | PK    |
| `device_id`    | STRING    | 設備 ID (e.g., "A26A_1")       | ✓     |
| `model`        | STRING    | 設備型號 (e.g., "A26A")        |       |
| `slave_id`     | STRING    | Modbus Slave ID                |       |
| `device_type`  | STRING    | 設備類型 (e.g., "Inverter")    | ✓     |
| `sampling_ts`  | DATETIME  | 採樣時間戳                     | ✓     |
| `created_at`   | DATETIME  | 資料庫寫入時間                 |       |
| `values_json`  | TEXT      | 完整 snapshot JSON 字串        |       |
| `is_online`    | INTEGER   | 通訊狀態 (1=online, 0=offline) |       |

### 複合索引

```sql
CREATE INDEX idx_device_ts ON snapshots (device_id, sampling_ts DESC);
CREATE INDEX idx_ts ON snapshots (sampling_ts DESC);
CREATE INDEX idx_type ON snapshots (device_type);
```

### Online/Offline 判斷邏輯

```python
# 通用規則（適用所有設備類型）
numeric_values = [v for v in values.values() if isinstance(v, (int, float))]
is_online = not all(v == -1 for v in numeric_values)

# 說明：
# - 全部參數都是 -1 → 離線（通訊失敗）
# - 部分參數是 -1 → 在線（AI/DI 腳位未使用或感測器故障）
```

---

## ⚙️ 配置說明

### 配置檔案位置

```
res/snapshot_storage.yml
```

### 配置參數

```yaml
# 啟用/停用 snapshot storage
enabled: true

# 資料庫檔案路徑
db_path: "/home/talos/data/snapshots.db"

# 資料保留天數（預設 7 天）
retention_days: 7

# 清理間隔（預設每 6 小時執行一次 DELETE）
cleanup_interval_hours: 6

# VACUUM 間隔（預設每 7 天執行一次）
vacuum_interval_days: 7
```

### 參數說明

| 參數                      | 類型    | 預設值                          | 說明                          |
|---------------------------|---------|--------------------------------|-------------------------------|
| `enabled`                 | bool    | `true`                         | 啟用/停用 snapshot storage    |
| `db_path`                 | string  | `/home/talos/data/snapshots.db`| SQLite 資料庫檔案路徑         |
| `retention_days`          | int     | `7`                            | 保留資料天數（≥1）            |
| `cleanup_interval_hours`  | int     | `6`                            | DELETE 操作間隔（小時）       |
| `vacuum_interval_days`    | int     | `7`                            | VACUUM 操作間隔（天）         |

### 調整建議

#### 開發/測試環境
```yaml
retention_days: 1              # 只保留 1 天
cleanup_interval_hours: 1      # 每小時清理
vacuum_interval_days: 1        # 每天 VACUUM
```

#### 生產環境（高頻採樣）
```yaml
retention_days: 3              # 保留 3 天（減少磁碟使用）
cleanup_interval_hours: 4      # 每 4 小時清理
vacuum_interval_days: 7        # 每週 VACUUM
```

#### 生產環境（長期資料保存）
```yaml
retention_days: 30             # 保留 30 天
cleanup_interval_hours: 12     # 每 12 小時清理
vacuum_interval_days: 14       # 每 2 週 VACUUM
```

---

## 🚀 部署指南

### 首次部署

1. **安裝依賴**：
   ```bash
   pip install -r requirements.txt
   ```

2. **配置檔案**：
   - 編輯 `res/snapshot_storage.yml`
   - 設定 `db_path`（確保目錄有寫入權限）

3. **啟動系統**：
   ```bash
   python src/main.py
   ```

4. **驗證啟動**：
   查看 log 中是否出現：
   ```
   [SnapshotStorage] Initializing (retention=7d, db_path=...)
   [SnapshotStorage] Enabled and initialized successfully
   SnapshotSaverSubscriber started
   ```

### 目錄結構

```
/home/talos/
├── data/
│   └── snapshots.db          # SQLite 資料庫檔案
│   └── snapshots.db-shm      # WAL mode 共享記憶體
│   └── snapshots.db-wal      # WAL mode write-ahead log
└── logs/
    └── talos.log             # 應用程式 log
```

### 權限設定

```bash
# 確保資料目錄存在並有寫入權限
mkdir -p /home/talos/data
chmod 755 /home/talos/data

# 如果使用非 root 用戶運行
chown talos:talos /home/talos/data
```

---

## 📊 監控與維護

### 磁碟空間監控

#### 估算資料庫大小

```python
# 假設：
# - 5 個設備
# - 每 10 秒採樣一次
# - 每個 snapshot 約 500 bytes
# - 保留 7 天

snapshots_per_day = 5 * (86400 / 10) = 43,200
total_snapshots = 43,200 * 7 = 302,400
estimated_size = 302,400 * 500 bytes ≈ 145 MB
```

#### 監控命令

```bash
# 檢查資料庫檔案大小
ls -lh /home/talos/data/snapshots.db

# 檢查可用磁碟空間
df -h /home/talos/data
```

### 資料庫健康檢查

#### 使用 Python (透過 Repository)

```python
from db.engine import create_snapshot_engine
from repository.snapshot_repository import SnapshotRepository

engine = create_snapshot_engine("/home/talos/data/snapshots.db")
repo = SnapshotRepository(engine)

# 取得統計資訊
stats = await repo.get_db_stats("/home/talos/data/snapshots.db")
print(f"Total snapshots: {stats['total_count']}")
print(f"Database size: {stats['file_size_mb']} MB")
print(f"Time range: {stats['earliest_ts']} to {stats['latest_ts']}")
```

#### 使用 SQLite CLI

```bash
# 進入資料庫
sqlite3 /home/talos/data/snapshots.db

# 檢查記錄數
SELECT COUNT(*) FROM snapshots;

# 檢查最早/最晚時間
SELECT
    MIN(sampling_ts) as earliest,
    MAX(sampling_ts) as latest,
    COUNT(*) as total
FROM snapshots;

# 檢查各設備記錄數
SELECT
    device_id,
    COUNT(*) as count
FROM snapshots
GROUP BY device_id;

# 檢查資料庫完整性
PRAGMA integrity_check;
```

### Log 檢查

```bash
# 查看 snapshot storage 相關 log
grep "SnapshotStorage\|SnapshotSaver\|SnapshotCleanup" /home/talos/logs/talos.log

# 查看清理操作 log
grep "Cleanup cycle completed" /home/talos/logs/talos.log

# 查看 VACUUM 操作 log
grep "VACUUM" /home/talos/logs/talos.log
```

---

## 🔧 故障排查

### 常見問題

#### 1. 資料庫檔案無法建立

**症狀**：
```
PermissionError: [Errno 13] Permission denied: '/home/talos/data/snapshots.db'
```

**解決方案**：
```bash
# 確保目錄存在
mkdir -p /home/talos/data

# 設定權限
chmod 755 /home/talos/data
chown talos:talos /home/talos/data
```

#### 2. 資料庫檔案被鎖定

**症狀**：
```
sqlite3.OperationalError: database is locked
```

**原因**：
- 有其他程序正在訪問資料庫
- WAL mode 未正確啟用

**解決方案**：
```bash
# 檢查是否有其他程序使用資料庫
lsof /home/talos/data/snapshots.db

# 重新啟動應用程式
systemctl restart talos

# 如果問題持續，檢查 WAL mode
sqlite3 /home/talos/data/snapshots.db "PRAGMA journal_mode;"
# 應該返回: wal
```

#### 3. 磁碟空間不足

**症狀**：
```
[SnapshotCleanup] Cleanup cycle completed (deleted 0 records)
```
但資料庫持續增長

**解決方案**：
```bash
# 手動執行清理
sqlite3 /home/talos/data/snapshots.db "DELETE FROM snapshots WHERE sampling_ts < datetime('now', '-7 days');"
sqlite3 /home/talos/data/snapshots.db "VACUUM;"

# 調整 retention_days
# 在 res/snapshot_storage.yml 中減少 retention_days
```

#### 4. Subscriber 未啟動

**症狀**：
Log 中沒有 "SnapshotSaverSubscriber started"

**檢查步驟**：
1. 確認 `snapshot_storage.yml` 中 `enabled: true`
2. 檢查配置檔案路徑是否正確
3. 查看 log 中是否有錯誤訊息

#### 5. VACUUM 操作過久

**症狀**：
VACUUM 執行超過預期時間，影響系統效能

**解決方案**：
```yaml
# 增加 VACUUM 間隔
vacuum_interval_days: 14  # 改為 2 週

# 或在低流量時段手動執行
# 在 crontab 中設定夜間執行
0 2 * * 0 sqlite3 /home/talos/data/snapshots.db "VACUUM;"
```

### 手動清理資料

```bash
# 備份資料庫
cp /home/talos/data/snapshots.db /home/talos/data/snapshots.db.backup

# 刪除 7 天前的資料
sqlite3 /home/talos/data/snapshots.db <<EOF
DELETE FROM snapshots WHERE sampling_ts < datetime('now', '-7 days');
VACUUM;
EOF

# 檢查結果
sqlite3 /home/talos/data/snapshots.db "SELECT COUNT(*) FROM snapshots;"
```

### 資料庫重建

```bash
# 停止應用程式
systemctl stop talos

# 備份舊資料庫
mv /home/talos/data/snapshots.db /home/talos/data/snapshots.db.old

# 重新啟動（會自動建立新資料庫）
systemctl start talos

# 驗證
ls -lh /home/talos/data/snapshots.db
```

---

## 🧪 測試

### 運行測試

```bash
# 運行所有 snapshot storage 測試
pytest test/repository/test_snapshot_repository.py -v
pytest test/subscriber/test_snapshot_saver_subscriber.py -v
pytest test/task/test_snapshot_cleanup_task.py -v
pytest test/integration/test_snapshot_storage_integration.py -v

# 運行所有測試
pytest test/ -v -k snapshot
```

### 測試覆蓋率

```bash
# 安裝 coverage
pip install pytest-cov

# 運行測試並生成覆蓋率報告
pytest test/ --cov=src/repository --cov=src/db --cov=src/task \
  --cov=src/util/pubsub/subscriber/snapshot_saver_subscriber.py \
  --cov-report=html

# 查看報告
open htmlcov/index.html
```

---

## 🔮 Phase 2 預覽

Phase 2 將新增以下功能（目前未包含在 Phase 1）：

- ✨ **REST API**：提供 HTTP 端點查詢歷史資料
- ✨ **WebSocket**：即時推送 snapshot 更新
- ✨ **資料匯出**：支援 CSV/JSON 格式匯出
- ✨ **進階查詢**：支援聚合查詢（平均值、最大值等）
- ✨ **效能優化**：批次寫入、讀取快取

---

## 📚 API Reference

### Repository API

詳見 `src/repository/snapshot_repository.py`

#### 寫入方法

```python
async def insert_snapshot(snapshot: dict) -> None
    """單筆插入 snapshot"""
```

#### 查詢方法

```python
async def get_latest_by_device(device_id: str, limit: int = 100) -> list[dict]
    """取得設備最新 N 筆 snapshot"""

async def get_time_range(
    device_id: str,
    start_time: datetime,
    end_time: datetime,
    limit: int = 1000
) -> list[dict]
    """時間範圍查詢"""

async def get_parameter_history(
    device_id: str,
    parameter: str,
    start_time: datetime,
    end_time: datetime,
    limit: int = 1000
) -> list[dict]
    """查詢特定參數的歷史"""

async def get_all_recent(minutes: int) -> list[dict]
    """取得所有設備最近 N 分鐘的 snapshot"""
```

#### 維護方法

```python
async def cleanup_old_snapshots(retention_days: int) -> int
    """刪除過期資料，返回刪除筆數"""

async def vacuum_database() -> None
    """執行 VACUUM 回收空間"""

async def get_db_stats(db_path: str) -> dict
    """取得資料庫統計資訊"""
```

---

## 📝 變更歷史

### Phase 1 (Current)
- ✅ SQLite async engine with WAL mode
- ✅ SnapshotRepository with CRUD operations
- ✅ SnapshotSaverSubscriber (PubSub integration)
- ✅ SnapshotCleanupTask (background maintenance)
- ✅ Configuration schema and YAML
- ✅ Unit tests and integration tests
- ✅ Documentation

---

## 🤝 貢獻

如需修改或擴展 snapshot storage 功能：

1. 修改代碼並確保通過所有測試
2. 更新相關文檔
3. 提交 Pull Request

---

## 📧 聯絡資訊

如有問題或建議，請聯繫 Talos 開發團隊。
