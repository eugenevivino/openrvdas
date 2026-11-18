class OpenVDMCSVParser:
    def __init__(self, filename, parser_options=None):
        self.filename = filename
        self.parser_options = parser_options or {}
        self.output = {"visualizerData": [], "qualityTests": [], "stats": {}}

    def add_visualization_data(self, value):
        self.output["visualizerData"].append(value)

    def _quality(self, name, result):
        self.output["qualityTests"].append({"testName": name, "results": result})

    def add_quality_test_passed(self, name):
        self._quality(name, "Passed")

    def add_quality_test_warning(self, name):
        self._quality(name, "Warning")

    def add_quality_test_failed(self, name):
        self._quality(name, "Failed")

    def add_row_validity_stat(self, valid, total):
        self.output["stats"]["rowValidity"] = {"valid": valid, "total": total}

    def add_time_bounds_stat(self, start, end):
        self.output["stats"]["timeBounds"] = {"start": start, "end": end}

    def add_bounds_stat(self, value, name, uom):
        self.output["stats"].setdefault("bounds", []).append(
            {"value": value, "name": name, "uom": uom})

    def add_total_value_stat(self, value):
        self.output["stats"]["totalValue"] = value


class OpenVDMPlugin:
    pass
