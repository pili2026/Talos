import asyncio
import json
import logging
import os

import httpx

from sender.legacy.legacy_format_adapter import convert_snapshot_to_legacy_payload

logger = logging.getLogger("LegacySender")


class LegacySenderAdapter:
    def __init__(self, gateway_id: str, serial_no: str, resend_dir: str, ima_url: str):
        self.gateway_id = gateway_id[:11]
        self.serial_no = serial_no
        self.resend_dir = resend_dir
        self.ima_url = ima_url
        os.makedirs(self.resend_dir, exist_ok=True)

    async def send_to_cloud(self, snapshot_map: dict, register_map_dict: dict) -> None:
        payload = convert_snapshot_to_legacy_payload(self.gateway_id, snapshot_map)
        json_data = json.dumps(payload)

        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.post(
                        self.ima_url,
                        data=json_data,
                        headers={"Content-Type": "application/json"},
                    )
                    logger.info(f"[SendToXms] Response: {resp.text}")
                    print(f"[SendToXms] Response: {resp.text}")

                    if "00000" not in resp.text:
                        raise ValueError("Server response error")
                    break  # 成功就跳出 retry

            except Exception as e:
                logger.warning(f"[SendToXms] Attempt {attempt + 1} failed: {e}")
                await asyncio.sleep(1)

                if attempt == 1:
                    filename = os.path.join(self.resend_dir, "manualtest-resend.xms")
                    with open(filename, "w", encoding="utf-8") as f:
                        f.write(json_data)
                    logger.warning(f"[SendToXms] Saved to retry file: {filename}")


if __name__ == "__main__":

    async def main():
        snapshot_map = {
            "IMA_C_6": {"DIn01": "1.0", "DIn02": "0.0", "DOut01": "0.0", "DOut02": "1.0", "ByPass": "1.0"},
            "TECO_VFD_2": {
                "KWH": "12.3",
                "VOLTAGE": "220.0",
                "CURRENT": "15.0",
                "KW": "35.0",
                "HZ": "60.0",
                "ERROR": "0.0",
                "ALERT": "0.0",
                "INVSTATUS": "1.0",
                "RW_HZ": "60.0",
                "RW_ON_OFF": "1.0",
            },
            "SD400_3": {
                "AIn01": "17.810",  # Temp
                "AIn02": "11.560",  # Temp
                "AIn03": "3.425",  # Pressure
                "AIn04": "25.940",  # Temp
                "AIn05": "39.929",  # Temp
                "AIn06": "3.737",  # Pressure
                "AIn07": "33.386",  # Temp
                "AIn08": "42.810",  # Temp
                "AIn09": "0.925",
                "AIn10": "22.754",
                "AIn11": "14.685",
                "AIn12": "1.659",
                "AIn13": "19.373",
                "AIn14": "32.373",
                "AIn15": "1.112",
                "AIn16": "20.667",
            },
        }

        sender = LegacySenderAdapter(
            gateway_id="jeremytalos",
            serial_no="003",
            resend_dir="./logs/resend",
            ima_url="http://imabox-server2.ima-ems.com",
        )
        await sender.send_to_cloud(snapshot_map, {})  # register_map_dict 已不再使用

    asyncio.run(main())
