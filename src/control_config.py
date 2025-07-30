from pydantic import BaseModel, Field

from model.control_model import ControlConditionModel


class ControlInstanceConfig(BaseModel):
    use_default_controls: bool = False
    controls: list[ControlConditionModel] = Field(default_factory=list)


class ControlModelConfig(BaseModel):
    default_controls: list[ControlConditionModel] = Field(default_factory=list)
    instances: dict[str, ControlInstanceConfig]


class ControlConfig(BaseModel):
    root: dict[str, ControlModelConfig]

    def get_control_list(self, model: str, slave_id: str) -> list[ControlConditionModel]:
        model_cfg = self.root.get(model)
        if not model_cfg:
            return []

        instance_cfg = model_cfg.instances.get(str(slave_id))
        if not instance_cfg:
            return []

        result = []
        if instance_cfg.use_default_controls:
            result += model_cfg.default_controls
        result += instance_cfg.controls
        return result
