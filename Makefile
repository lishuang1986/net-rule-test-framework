# Makefile for net-rule-test-framework

.PHONY: help clean clean-all test test-firewall test-tc test-rocev2 report

# Default target
help:
	@echo "Available targets:"
	@echo "  make clean         - Remove Python cache and pytest cache (requires sudo)"
	@echo "  make clean-all     - Clean cache + remove reports, assets, and test artifacts (requires sudo)"
	@echo "  make test          - Run all tests with netns backend"
	@echo "  make test-firewall - Run firewall tests only"
	@echo "  make test-tc       - Run TC tests only"
	@echo "  make test-rocev2   - Run RoCEv2 tests (requires libvirt infra)"
	@echo "  make report        - Run all tests and generate HTML report"

# Clean temporary files (cache only, needs sudo because test-generated files are owned by root)
clean:
	@echo "Cleaning Python cache and pytest cache (using sudo)..."
	@sudo find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	@sudo find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	@sudo find . -type f -name "*.pyc" -delete 2>/dev/null || true
	@sudo find . -type f -name "*.bak" -delete 2>/dev/null || true
	@echo "Done."

# More thorough clean (includes reports, assets directory, etc., needs sudo)
clean-all: clean
	@echo "Removing reports and test artifacts..."
	@sudo rm -rf assets report.html
	@echo "Done."

# Run all tests (defaults to netns backend)
test:
	sudo pytest tests/ --infra=netns -v

test-firewall:
	sudo pytest tests/firewall/ --infra=netns -v

test-tc:
	sudo pytest tests/tc/ --infra=netns -v

test-rocev2:
	sudo pytest tests/rocev2/ --infra=libvirt -v

# Generate HTML report
report:
	sudo pytest tests/ --infra=netns -v --html=report.html
	@echo "Report generated: report.html"
