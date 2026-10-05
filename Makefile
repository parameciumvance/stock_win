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
