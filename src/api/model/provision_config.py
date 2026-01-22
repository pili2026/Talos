import os

from pydantic import BaseModel


class ProvisionConfig(BaseModel):
    """Provisioning service configuration"""

    use_sudo: bool = True
    """Whether to use sudo for system commands (default: True)"""

    timeout_sec: float = 10.0
    """Command execution timeout in seconds"""

    @classmethod
    def from_env(cls) -> "ProvisionConfig":
        """Load configuration from environment variables"""
        return cls(
            use_sudo=os.getenv("TALOS_PROVISION_USE_SUDO", "true").lower() == "true",
            timeout_sec=float(os.getenv("TALOS_PROVISION_TIMEOUT_SECONDS", "10.0")),
        )
