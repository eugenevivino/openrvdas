def pytest_configure(config):
    config.addinivalue_line("markers", "lead_run: browser or host test the lead runs")
    config.addinivalue_line("markers", "slow: long-running test")
