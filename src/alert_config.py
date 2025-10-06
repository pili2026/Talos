from pydantic import BaseModel

from schema.alert_schema import AlertConditionModel, ModelConfig


class AlertConfig(BaseModel):

    root: dict[str, ModelConfig]

    def get_instance_alerts(self, model: str, slave_id: str) -> list[AlertConditionModel]:
        model_conf = self.root.get(model)
        if not model_conf:
            return []

        instance_conf = model_conf.instances.get(slave_id)
        if not instance_conf:
            return []

        if instance_conf.alerts:
            return instance_conf.alerts

        if instance_conf.use_default_alerts:
            return model_conf.default_alerts

        return []
