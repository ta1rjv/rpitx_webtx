# Builds webtx_iq and webtx-sendiq against librpitx.
#
# webtx_iq (native/webtx_iq.cpp) is the primary, recommended low-latency
# transmitter. webtx-sendiq is a build of the vendored, low-latency-patched
# copy of rpitx's own sendiq.cpp (../vendor/rpitx-src/sendiq.cpp - see
# ../vendor/NOTICE.md and ../docs/DECISIONS.md ADR-010), a stock-compatible
# fallback sink that also needs zero external download. It is named
# "webtx-sendiq", not "sendiq", so it never collides with a system-installed
# rpitx's own /opt/rpitx/sendiq.
#
# librpitx is vendored in this repository (../vendor/librpitx, see
# ../vendor/NOTICE.md) and is built automatically if no system-wide install
# is found - no separate clone of any rpitx/librpitx repository is required.
# A system-wide install (from rpitx's own install.sh) or an RPITX_PATH
# checkout is still preferred when present, so a system librpitx you have
# already patched or customized takes priority over the vendored copy.
#
# This only builds on a Raspberry Pi (or another ARM Linux target rpitx
# supports): librpitx compiles against Broadcom's VideoCore headers/libs
# (/opt/vc/include, -lbcm_host), which do not exist elsewhere.
#
# Usage:
#   make                      # auto-detect librpitx; builds the vendored
#                              # copy automatically if nothing else is found
#   make RPITX_PATH=/opt/rpitx
#   make check                # report what would be used, without building
#   sudo make install         # install to /usr/local/bin

RPITX_PATH ?= /opt/rpitx
PREFIX ?= /usr/local
VENDOR_DIR := ../vendor/librpitx
RPITX_SRC_DIR := ../vendor/rpitx-src

CXX ?= c++
CXXFLAGS ?= -std=c++11 -Wall -O2 -Wno-unused-variable
LDFLAGS ?= -L/opt/vc/lib -lm -lrt -lpthread -lbcm_host

# System-wide locations to prefer over the vendored copy, in order: the
# normal result of rpitx's own install.sh ("make install" inside
# librpitx/src), then an RPITX_PATH checkout that was built but not installed.
SYSTEM_LIB_CANDIDATES := \
	/usr/local/lib/librpitx.a \
	/usr/lib/librpitx.a \
	$(RPITX_PATH)/src/librpitx/src/librpitx.a

SYSTEM_HEADER_CANDIDATES := \
	/usr/local/include/librpitx/librpitx.h \
	/usr/include/librpitx/librpitx.h \
	$(RPITX_PATH)/src/librpitx/src/librpitx.h

SYSTEM_LIB := $(firstword $(wildcard $(SYSTEM_LIB_CANDIDATES)))
SYSTEM_HEADER := $(firstword $(wildcard $(SYSTEM_HEADER_CANDIDATES)))

VENDOR_LIB := $(VENDOR_DIR)/librpitx.a
VENDOR_HEADER := $(VENDOR_DIR)/librpitx.h

ifneq (,$(SYSTEM_LIB))
ifneq (,$(SYSTEM_HEADER))
LIBRPITX_LIB := $(SYSTEM_LIB)
ifneq (,$(findstring /usr/local/include/librpitx/librpitx.h,$(SYSTEM_HEADER)))
INCLUDE_DIR := /usr/local/include
else ifneq (,$(findstring /usr/include/librpitx/librpitx.h,$(SYSTEM_HEADER)))
INCLUDE_DIR := /usr/include
else
INCLUDE_DIR := $(RPITX_PATH)/src/librpitx/src/..
endif
LIBRPITX_SOURCE := system install ($(SYSTEM_LIB))
endif
endif

ifeq (,$(LIBRPITX_LIB))
LIBRPITX_LIB := $(VENDOR_LIB)
# NOT $(VENDOR_DIR) itself: webtx_iq.cpp and sendiq.cpp both say
# #include <librpitx/librpitx.h>, so the compiler needs the *parent* of the
# librpitx/ directory on -I (matching the /usr/local/include and
# RPITX_PATH/.../librpitx/src/.. cases above, which both also point one
# level above the directory that directly contains librpitx.h).
INCLUDE_DIR := $(dir $(VENDOR_DIR))
LIBRPITX_SOURCE := vendored copy (built automatically from $(VENDOR_DIR))
endif

UNAME_M := $(shell uname -m)

.PHONY: all check install clean

all: check-arch webtx_iq webtx-sendiq

check-arch:
ifeq (,$(filter arm% aarch64,$(UNAME_M)))
	@echo "webtx_iq only builds on a Raspberry Pi (ARM). Detected arch: $(UNAME_M)."
	@echo "Nothing to do on this host; the server falls back to stock sendiq"
	@echo "or the null sink automatically (see docs/DECISIONS.md ADR-003)."
	@exit 1
endif

check:
	@echo "RPITX_PATH  = $(RPITX_PATH)"
	@echo "arch        = $(UNAME_M)"
	@echo "librpitx    = $(LIBRPITX_SOURCE)"
	@echo "include dir = $(INCLUDE_DIR)"

# Only invoked when no system librpitx was found above, and only when the
# vendored .a does not already exist - a real build (webtx_iq's own
# prerequisite below), never as a side effect of `make check`.
$(VENDOR_LIB):
	@echo "No system librpitx found; building the vendored copy in $(VENDOR_DIR)..."
	$(MAKE) -C $(VENDOR_DIR)

webtx_iq: webtx_iq.cpp $(LIBRPITX_LIB)
	$(CXX) $(CXXFLAGS) -I$(INCLUDE_DIR) -o webtx_iq webtx_iq.cpp $(LIBRPITX_LIB) $(LDFLAGS)

# Builds the vendored, low-latency-patched copy of rpitx's own sendiq.cpp
# (see $(RPITX_SRC_DIR)/sendiq.cpp, ../vendor/NOTICE.md and
# ../patches/sendiq-lowlatency.patch) against the same resolved librpitx
# used for webtx_iq above - the detection logic is not re-derived.
webtx-sendiq: $(RPITX_SRC_DIR)/sendiq.cpp $(LIBRPITX_LIB)
	$(CXX) $(CXXFLAGS) -I$(INCLUDE_DIR) -o webtx-sendiq $(RPITX_SRC_DIR)/sendiq.cpp $(LIBRPITX_LIB) $(LDFLAGS)

install: webtx_iq webtx-sendiq
	install -m 0755 webtx_iq $(PREFIX)/bin/webtx_iq
	install -m 0755 webtx-sendiq $(PREFIX)/bin/webtx-sendiq

clean:
	rm -f webtx_iq webtx-sendiq
	@if [ -f $(VENDOR_LIB) ]; then $(MAKE) -C $(VENDOR_DIR) clean; fi
