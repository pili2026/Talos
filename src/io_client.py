from pymodbus.client import ModbusSerialClient


class ModbusRTUClient:
    def __init__(self, port: str, slave_id: int, baudrate=9600, timeout=1):
        self.slave_id = slave_id
        self.client = ModbusSerialClient(
            port=port, baudrate=baudrate, timeout=timeout, stopbits=1, bytesize=8, parity="N"
        )
        self.client.connect()

    def read(self, reg_type: str, address: int, count: int = 1) -> list[int]:
        if reg_type == "holding":
            result = self.client.read_holding_registers(address=address, count=count, slave=self.slave_id)

        elif reg_type == "input":
            result = self.client.read_input_registers(address=address, count=count, slave=self.slave_id)
        else:
            raise ValueError(f"Unsupported register type: {reg_type}")
        if result.isError():
            raise IOError(f"Modbus read failed: {result}")
        return result.registers

    def write(self, reg_type: str, address: int, value: int):
        if reg_type == "holding":
            result = self.client.write_register(address=address, value=value, slave=self.slave_id)
        else:
            raise ValueError(f"Cannot write to register type: {reg_type}")
        if result.isError():
            raise IOError(f"Modbus write failed: {result}")
