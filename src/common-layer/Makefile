# SAM BuildMethod: makefile invokes this from a temp dir, not from src/common-layer.
# So relative paths like ../common don't work. We use the makefile's own absolute
# location (resolved at parse time via MAKEFILE_LIST) to find src/common.
MAKEFILE_DIR := $(dir $(realpath $(lastword $(MAKEFILE_LIST))))
COMMON_SRC := $(MAKEFILE_DIR)../common

build-AccelyaCommonLayer:
	@echo "Copying $(COMMON_SRC) -> $(ARTIFACTS_DIR)/python/common"
	mkdir -p "$(ARTIFACTS_DIR)/python"
	cp -r "$(COMMON_SRC)" "$(ARTIFACTS_DIR)/python/common"
	find "$(ARTIFACTS_DIR)/python/common" -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@ls "$(ARTIFACTS_DIR)/python/common/" | head -10
