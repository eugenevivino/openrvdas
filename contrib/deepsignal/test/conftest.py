def pytest_configure(config):
    config.addinivalue_line("markers", "lead_run: browser or host test the lead runs outside the cloud sandbox")
    config.addinivalue_line("markers", "slow: long-running test")
