.PHONY: install run clean

PYTHON = python3

install:
	$(PYTHON) -m pip install -e .

run:
	GSETTINGS_SCHEMA_DIR=data DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib:$(DYLD_FALLBACK_LIBRARY_PATH) $(PYTHON) -m showberry.main

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -name "._*" -delete
	rm -rf build dist *.egg-info .pytest_cache uv.lock

test:
	DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib:$(DYLD_FALLBACK_LIBRARY_PATH) $(PYTHON) -m pytest tests/ -v

build:
	$(PYTHON) -m build --wheel --no-isolation

pkg:
	makepkg -si

flatpak:
	flatpak-builder --user --install --force-clean build-dir data/io.github.Dackerie.Showberry.json

lint:
	$(PYTHON) -m py_compile showberry/*.py showberry/*/*.py

schema:
	glib-compile-schemas --strict data/

help:
	@echo "Available targets:"
	@echo "  run      - Run the app directly with local schema"
	@echo "  test     - Run automated test suite"
	@echo "  build    - Build Python wheel"
	@echo "  pkg      - Build & install native Arch package via makepkg"
	@echo "  flatpak  - Build & install user Flatpak bundle"
	@echo "  clean    - Remove build artifacts and Python cache"
	@echo "  schema   - Compile GSettings schemas strictly"
