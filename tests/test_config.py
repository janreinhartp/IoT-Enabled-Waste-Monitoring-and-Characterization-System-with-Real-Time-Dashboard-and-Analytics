from app.config import load_config, AppConfig


def test_load_example_config():
    cfg = load_config("config.example.yaml")
    assert isinstance(cfg, AppConfig)
    assert cfg.hardware.use_mock is True
    assert cfg.hardware.scale.slave_address == 1    # Modbus default slave address
    assert cfg.hardware.scale.baud_rate == 9600     # Modbus default baud rate
    assert cfg.events.stability_window >= 2
    assert cfg.events.capacity_kg == 100.0
    assert cfg.web.port == 5000
    assert cfg.database.url.startswith("sqlite:///")


def test_defaults_when_no_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    cfg = load_config()
    assert cfg.hardware.use_mock is True
    assert cfg.ai.backend == "mock"
