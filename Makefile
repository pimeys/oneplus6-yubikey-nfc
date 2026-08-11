CC ?= cc
PYTHON ?= python3
CFLAGS ?= -O2 -g
WARNINGS := -Wall -Wextra -Werror
BUILD_DIR := build

LIBFIDO2_VERSION := 1.16.0
LIBFIDO2_ARCHIVE := .deps/libfido2-$(LIBFIDO2_VERSION).tar.gz
LIBFIDO2_SHA256 := 7d86088ef4a48f9faad4ff6f41343328157849153a8dc94d88f4b5461cb29474
LIBFIDO2_DIR := .deps/libfido2-$(LIBFIDO2_VERSION)
LIBFIDO2_CPPFLAGS := -D_FIDO_INTERNAL -D_GNU_SOURCE -D_DEFAULT_SOURCE -DUSE_NFC \
	-DHAVE_GETLINE -DHAVE_GETOPT -DHAVE_GETPAGESIZE -DHAVE_GETRANDOM \
	-DHAVE_STRSEP -DHAVE_UNISTD_H -DHAVE_CLOCK_GETTIME -DHAVE_ASPRINTF \
	-I$(LIBFIDO2_DIR)/src

IFD_DIR := vendor/ifdnlnfc
IFD_BUILD_DIR := $(BUILD_DIR)/ifdnlnfc
IFD_PKG_CONFIG := libpcsclite libnl-3.0 libnl-genl-3.0
IFD_CPPFLAGS := -I$(IFD_BUILD_DIR) -I$(IFD_DIR)/src -I$(IFD_DIR)/src/include \
	$(shell pkg-config --cflags $(IFD_PKG_CONFIG))
IFD_LDLIBS := $(shell pkg-config --libs $(IFD_PKG_CONFIG)) -pthread

PROBE := $(BUILD_DIR)/ykchal-nfc
DRIVER := $(BUILD_DIR)/libnlnfc.so
IFD_TEST := $(BUILD_DIR)/ifd-contract-test

.PHONY: all clean driver prepare probe secrets-test test

all: probe driver

probe: $(PROBE)

driver: $(DRIVER)

prepare: $(LIBFIDO2_DIR)/src/netlink.c $(IFD_BUILD_DIR)/config.h

$(LIBFIDO2_ARCHIVE):
	mkdir -p .deps
	wget -q -O $@ https://github.com/Yubico/libfido2/archive/refs/tags/$(LIBFIDO2_VERSION).tar.gz
	echo "$(LIBFIDO2_SHA256)  $@" | sha256sum -c -

$(LIBFIDO2_DIR)/src/netlink.c: $(LIBFIDO2_ARCHIVE)
	tar -xzf $< -C .deps
	touch $@

$(BUILD_DIR)/netlink.o: $(LIBFIDO2_DIR)/src/netlink.c
	mkdir -p $(BUILD_DIR)
	$(CC) $(LIBFIDO2_CPPFLAGS) $(CFLAGS) $(WARNINGS) -c $< -o $@

$(PROBE): src/ykchal_nfc.c $(BUILD_DIR)/netlink.o
	$(CC) $(LIBFIDO2_CPPFLAGS) $(CFLAGS) $(WARNINGS) $^ -o $@

$(IFD_BUILD_DIR)/config.h:
	mkdir -p $(IFD_BUILD_DIR)
	printf '%s\n' '/* Generated for the direct project build. */' > $@

$(DRIVER): $(IFD_DIR)/src/ifdnlnfc.c $(IFD_DIR)/src/ifdnlnfc.h $(IFD_BUILD_DIR)/config.h
	$(CC) $(IFD_CPPFLAGS) $(CFLAGS) $(WARNINGS) -fPIC -shared \
		-Wl,-soname,libnlnfc.so.0 -Wl,-z,relro,-z,now \
		$< -o $@ $(IFD_LDLIBS)

$(IFD_TEST): tests/ifd_contract.c $(IFD_DIR)/src/ifdnlnfc.c \
		$(IFD_DIR)/src/ifdnlnfc.h $(IFD_BUILD_DIR)/config.h
	$(CC) $(IFD_CPPFLAGS) $(CFLAGS) $(WARNINGS) -DNO_LOG \
		tests/ifd_contract.c $(IFD_DIR)/src/ifdnlnfc.c \
		-o $@ $(IFD_LDLIBS)

secrets-test:
	PYTHONPATH=secrets-overlay $(PYTHON) -m unittest discover -s tests -p 'test_*.py'

test: $(IFD_TEST) secrets-test
	./$(IFD_TEST)

clean:
	rm -rf $(BUILD_DIR) .deps
