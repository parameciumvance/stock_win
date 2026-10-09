PYTHON ?= python3

.PHONY: test-diagnostics check-diagnostic-inputs diagnostics

test-diagnostics:
	$(PYTHON) -m unittest twse_history.test_asof_revenue test_entry_barriers_v80 twse_history.test_history twse_history.test_multiyear -q

check-diagnostic-inputs:
	$(PYTHON) verify_diagnostic_inputs.py

diagnostics: check-diagnostic-inputs
	$(PYTHON) audit_volatility_baseline_v79.py
	$(PYTHON) audit_entry_barriers_v80.py
	$(PYTHON) audit_volatility_uncertainty_v81.py

.PHONY: test-institutional institutional-diagnostics

test-institutional:
	$(PYTHON) -m unittest twse_history.test_revenue_pilot twse_history.test_institutional twse_history.test_institutional_features test_institutional_increment test_institutional_uncertainty test_institutional_pool test_institutional_resume -q

institutional-diagnostics:
	$(PYTHON) -m twse_history.institutional_features --year 2023 --prices twse_history/output_multiyear_2023_2026_asof_20261002/prices_adjusted_2023_2026.csv.gz --flows inputs/institutional_twse_2023.csv.gz --output inputs/institutional_features_2023.csv.gz
	$(PYTHON) -m twse_history.institutional_features --years 2023 2024 --prices twse_history/output_multiyear_2023_2026_asof_20261002/prices_adjusted_2023_2026.csv.gz --flows inputs/institutional_twse_2023.csv.gz inputs/institutional_twse_2024.csv.gz --output inputs/institutional_features_2023_2024.csv.gz
	$(PYTHON) audit_institutional_increment.py --config configs/institutional_diagnostic_2023.json
	$(PYTHON) audit_institutional_increment.py --config configs/institutional_diagnostic_2024.json


.PHONY: institutional-uncertainty

institutional-uncertainty:
	$(PYTHON) audit_institutional_uncertainty.py --config $(UNCERTAINTY_CONFIG)

UNCERTAINTY_CONFIG ?= configs/institutional_uncertainty_2024.json
POOL_CONFIG ?= configs/institutional_pool_audit_2024.json

.PHONY: institutional-pool-audit

institutional-pool-audit:
	$(PYTHON) audit_institutional_pool.py --config $(POOL_CONFIG)

.PHONY: institutional-source-audit
YEAR ?= 2025

institutional-source-audit:
	$(PYTHON) audit_institutional_acquisition.py --year $(YEAR)
