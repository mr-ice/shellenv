# Patched bash for discovery (see patches/bash-sourcetrace.patch, patches/README.md)
BASH_VERSION ?= 5.2
BASH_DIR := bash-src/bash-$(BASH_VERSION)
BASH_TAR := bash-src/bash-$(BASH_VERSION).tar.gz
BASH_URL := https://ftp.gnu.org/gnu/bash/bash-$(BASH_VERSION).tar.gz
BASH_PATCH := $(CURDIR)/patches/bash-sourcetrace.patch
BASH_BUILT := $(BASH_DIR)/bash
BASH_INSTALL := bash-src/bash
BASH_ABS_DIR := $(CURDIR)/$(BASH_DIR)
BASH_ABS_TAR := $(CURDIR)/$(BASH_TAR)
BASH_ABS_INSTALL := $(CURDIR)/$(BASH_INSTALL)

# Patched tcsh for discovery/tracing (output: tcsh-src/tcsh)
TCSH_REPO ?= https://github.com/tcsh-org/tcsh.git
TCSH_DIR := tcsh-src/tcsh-git
TCSH_BUILT := $(TCSH_DIR)/tcsh
TCSH_INSTALL := tcsh-src/tcsh
TCSH_ABS_DIR := $(CURDIR)/$(TCSH_DIR)
TCSH_ABS_INSTALL := $(CURDIR)/$(TCSH_INSTALL)
TCSH_PATCH_XTRACEFD := $(CURDIR)/patches/tcsh-TCSH_XTRACEFD.patch
TCSH_PATCH_CLOSEM_XTRACE := $(CURDIR)/patches/tcsh-closem-preserve-xtracefd.patch
TCSH_PATCH_XTRACE_PATH := $(CURDIR)/patches/tcsh-xtrace-filepath.patch
TCSH_PATCH_ALLOW_L := $(CURDIR)/patches/tcsh-allow-l-with-args.patch
TCSH_PATCH_SOURCETRACE := $(CURDIR)/patches/tcsh-sourcetrace.patch

help:  ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m\033[0m\n"} \
    /^[a-zA-Z][a-zA-Z0-9_.\/-]* *:.*##/ { printf "  \033[36m%-22s\033[0m %s\n", $$1,$$2 } \
    /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

style:  ## Format code with ruff (same version as CI via uv dev group)
	uv run ruff format .

lint:  ## Check code with ruff
	uv run ruff check .

test:  ## Run pytest
	PYTHONPATH=src pytest -q

test-cov:  ## Run pytest with coverage
	PYTHONPATH=src pytest -q --cov=src --cov-report=term --cov-report=xml:coverage.xml

ptw:  ## Run pytest-watch (if installed)
	ptw

clean:  ## Remove pycache and build artifacts
	rm -rf build dist *.egg-info .pytest_cache **/__pycache__

##@ Patched bash (for shellenv tracing; output: bash-src/bash)

bash-src/bash: $(BASH_BUILT) ## Fetch, patch, build, copy to bash-src/bash
	mkdir -p bash-src
	cp $(BASH_ABS_DIR)/bash $(BASH_ABS_INSTALL)
	chmod +x $(BASH_ABS_INSTALL)

$(BASH_BUILT): $(BASH_DIR)/Makefile
	$(MAKE) -C $(BASH_ABS_DIR)

$(BASH_DIR)/Makefile: $(BASH_DIR)/.patch-applied
	cd $(BASH_ABS_DIR) && ./configure

$(BASH_DIR)/.patch-applied: $(BASH_DIR)/.extracted
	test -d $(BASH_ABS_DIR)
	test -f $@ || (cd $(BASH_ABS_DIR) && patch -p1 -i $(BASH_PATCH))
	grep -q xtrace_source_trace $(BASH_ABS_DIR)/externs.h
	touch $@

$(BASH_DIR)/.extracted: $(BASH_TAR)
	mkdir -p bash-src
	test -d $(BASH_ABS_DIR) || tar xzf $(BASH_ABS_TAR) -C $(CURDIR)/bash-src
	test -d $(BASH_ABS_DIR)
	touch $@

$(BASH_TAR):
	mkdir -p bash-src
	curl -fL -o $@.part $(BASH_URL) && mv $@.part $@

.PHONY: clean-bash
clean-bash:  ## Remove downloaded bash tarball, build tree, and bash-src/bash
	rm -rf $(BASH_DIR) $(BASH_TAR) $(BASH_INSTALL)

##@ Patched tcsh (for shellenv tracing; output: tcsh-src/tcsh)

tcsh-src/tcsh: $(TCSH_BUILT) ## Clone, patch, build, copy to tcsh-src/tcsh
	mkdir -p tcsh-src
	cp $(TCSH_ABS_DIR)/tcsh $(TCSH_ABS_INSTALL)
	chmod +x $(TCSH_ABS_INSTALL)

$(TCSH_BUILT): $(TCSH_DIR)/Makefile
	$(MAKE) -C $(TCSH_ABS_DIR)

$(TCSH_DIR)/Makefile: $(TCSH_DIR)/.patch-applied
	cd $(TCSH_ABS_DIR) && ./configure

$(TCSH_DIR)/.patch-applied: $(TCSH_DIR)/.cloned
	test -d $(TCSH_ABS_DIR)
	test -f $@ || (cd $(TCSH_ABS_DIR) && patch -p1 -i $(TCSH_PATCH_XTRACEFD))
	test -f $@ || (cd $(TCSH_ABS_DIR) && patch -p1 -i $(TCSH_PATCH_CLOSEM_XTRACE))
	test -f $@ || (cd $(TCSH_ABS_DIR) && patch -p1 -i $(TCSH_PATCH_XTRACE_PATH))
	test -f $@ || (cd $(TCSH_ABS_DIR) && patch -p1 -i $(TCSH_PATCH_ALLOW_L))
	test -f $@ || (cd $(TCSH_ABS_DIR) && patch -p1 -i $(TCSH_PATCH_SOURCETRACE))
	grep -q TCSH_XTRACEFD $(TCSH_ABS_DIR)/sh.c
	grep -q "case 'l'" $(TCSH_ABS_DIR)/sh.c
	grep -q tcsh_xtrace_sourcetrace $(TCSH_ABS_DIR)/sh.exec.c
	touch $@

$(TCSH_DIR)/.cloned:
	mkdir -p tcsh-src
	test -d $(TCSH_ABS_DIR) || git clone --depth 1 $(TCSH_REPO) $(TCSH_ABS_DIR)
	test -d $(TCSH_ABS_DIR)
	touch $@

refresh-shelltree:  ## Refresh the shelltree directory with random files
	PYTHONPATH=libexec python3 libexec/refresh-shelltree.py

validate-discovery:  ## Validate discovery of startup files
	env - $$(which uv) run  python3 libexec/validate-discovery.py

.PHONY: clean-tcsh
clean-tcsh:  ## Remove tcsh source tree and tcsh-src/tcsh
	rm -rf $(TCSH_DIR) $(TCSH_INSTALL)

coverage:  ## Run coverage
	env - $$(which uv) run pytest --cov=src --cov-report=term --cov-report=xml:coverage.xml