.PHONY: help install collect normalize preview push clean test lint

month ?= $(shell date +%Y-%m)

help:
	@echo "Targets (month=YYYY-MM, default: courant) :"
	@echo "  make collect month=2026-06    # collecte toutes sources → cache/2026-06/raw/"
	@echo "  make normalize month=2026-06  # Claude API → cache/2026-06/normalized.json"
	@echo "  make preview month=2026-06    # CSV preview pour validation manuelle"
	@echo "  make push month=2026-06       # gspread → Google Sheet"
	@echo "  make month=2026-06            # collect + normalize + preview (sans push)"
	@echo "  make clean month=2026-06      # supprime cache/2026-06/"

install:
	pip install -e ".[dev]"
	playwright install chromium

# Pipeline complet (sans push)
all: collect normalize preview

# Default target = pipeline preview
.DEFAULT_GOAL := all

collect:
	tapageur collect --month $(month)

normalize:
	tapageur normalize --month $(month)

preview:
	tapageur preview --month $(month)

push:
	tapageur push --month $(month)

clean:
	rm -rf cache/$(month)

test:
	pytest -v

lint:
	ruff check tapageur/ tests/
	mypy tapageur/
