.PHONY: install run clean

PYTHON = python3

install:
	$(PYTHON) -m pip install -e .

run:
	GSETTINGS_SCHEMA_DIR=data $(PYTHON) -m kinema.main

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete

lint:
	$(PYTHON) -m flake8 kinema/
	$(PYTHON) -m py_compile kinema/main.py

schema:
	glib-compile-schemas data/

help:
	@echo "Available targets:"
	@echo "  install  - Install the app in development mode"
	@echo "  run      - Run the app directly"
	@echo "  clean    - Remove Python cache files"
	@echo "  lint     - Run linter on the code"
	@echo "  schema   - Compile GSettings schemas"
