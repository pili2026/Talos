from logging import Logger
from typing import Iterable

from device.generic.scales import ScaleService


class HookManager:
    def __init__(self, hook_list: list, logger: Logger, scale_service: ScaleService = None):
        self.hook_list = hook_list or []
        self.logger = logger
        self.scale_service = scale_service

    def on_write(self, pin_name: str, pin_cfg: dict):
        hook_list = self.hook_list
        if isinstance(hook_list, dict):
            hook_list = [hook_list]

        for hook in hook_list:
            # simple string style
            if isinstance(hook, str):
                if hook == pin_name:
                    self._invalidate(None)
                    return
                continue

            if not isinstance(hook, dict):
                continue

            regs: Iterable[str] = hook.get("registers", [])
            offs: Iterable[int] = hook.get("offsets", [])
            hit = pin_name in regs or (offs and ("offset" in pin_cfg) and (pin_cfg["offset"] in offs))
            if not hit:
                continue

            inv = hook.get("invalidate")
            if inv:
                keys = [s.split(".", 1)[1] for s in inv if isinstance(s, str) and s.startswith("scales.")]
                self._invalidate(keys or None)
            else:
                self._invalidate(None)
            return

    def _invalidate(self, keys: list[str] | None):
        if self.scale_service:
            self.scale_service.invalidate(keys)
