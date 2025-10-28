# Talos(Pending...)
## API Document
* Static API Doc 
    * http://0.0.0.0:8000/docs
* Async API Doc
    * http://0.0.0.0:8000/api/monitoring/doc
## Tool Web
* Modbus Test Tool Web(Websocket)
    * http://0.0.0.0:8000/static/index.html

## Excute Command
* Run Talos(main.py)
```
python src/main.py \
  --alert_config res/alert_condition.yml \
  --control_config res/control_condition.yml \
  --modbus_device res/modbus_device.yml \
  --instance_config res/device_instance_config.yml \
  --sender_config res/sender_config.yml \
  --mail_config res/mail_config.yml \
  --time_config res/time_condition.yml
```
* Run Talos API
```
PYTHONPATH=src PYTHONUNBUFFERED=1 uvicorn api.app:app \
  --reload \
  --host 0.0.0.0 \
  --port 8000 \
  --log-level info
```
* Run Talos API (No Reload)
```
PYTHONPATH=src PYTHONUNBUFFERED=1 uvicorn api.app:app \
  --host 0.0.0.0 \
  --port 8000 \
  --log-level debug
```
* Run Talos API(app.py)
```
PYTHONPATH=src PYTHONUNBUFFERED=1 python src/api/app.py
```