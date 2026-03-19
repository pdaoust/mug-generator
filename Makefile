EXTENSION_NAME := mug-generator
VERSION := $(shell git describe --tags --always 2>/dev/null || echo dev)
DIST_DIR := dist
BUNDLE := $(DIST_DIR)/$(EXTENSION_NAME)-$(VERSION).zip

SRC_DIR := inkscape-extension

# Files to include in the bundle
INX := $(SRC_DIR)/mug_generator.inx
PY_MAIN := $(SRC_DIR)/mug_generator.py
LIB_PY := $(wildcard $(SRC_DIR)/lib/*.py)
SCAD := $(wildcard $(SRC_DIR)/scad/*.scad)

SOURCES := $(INX) $(PY_MAIN) $(LIB_PY) $(SCAD)

.PHONY: all clean test

all: $(BUNDLE)

$(BUNDLE): $(SOURCES)
	@mkdir -p $(DIST_DIR)
	@rm -f $@
	cd $(SRC_DIR) && zip -r ../$(BUNDLE) \
		mug_generator.inx \
		mug_generator.py \
		lib/*.py \
		scad/*.scad \
		-x '*/__pycache__/*' '*.pyc'
	@echo "Built $(BUNDLE)"

test:
	.venv/bin/pytest tests/ -q

clean:
	rm -rf $(DIST_DIR)
