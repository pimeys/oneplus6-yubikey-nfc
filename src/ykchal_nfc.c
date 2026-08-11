// SPDX-License-Identifier: GPL-3.0-or-later

#include <sys/socket.h>

#include <errno.h>
#include <linux/nfc.h>
#include <poll.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#include "fido.h"
#include "netlink.h"

void fido_log_debug(const char *format, ...)
{
    va_list ap;
    va_start(ap, format);
    fprintf(stderr, "debug: ");
    vfprintf(stderr, format, ap);
    fputc('\n', stderr);
    va_end(ap);
}

void fido_log_error(int error, const char *format, ...)
{
    va_list ap;
    va_start(ap, format);
    fprintf(stderr, "error: ");
    vfprintf(stderr, format, ap);
    fprintf(stderr, ": %s\n", strerror(error));
    va_end(ap);
}

void fido_log_xxd(const void *data, size_t length, const char *format, ...)
{
    (void)data;
    (void)length;
    (void)format;
}

int fido_buf_read(const unsigned char **src, size_t *src_len, void *dst, size_t count)
{
    if (count > *src_len) {
        return -1;
    }
    memcpy(dst, *src, count);
    *src += count;
    *src_len -= count;
    return 0;
}

int fido_buf_write(unsigned char **dst, size_t *dst_len, const void *src, size_t count)
{
    if (count > *dst_len) {
        return -1;
    }
    memcpy(*dst, src, count);
    *dst += count;
    *dst_len -= count;
    return 0;
}

int fido_hid_unix_wait(int fd, int timeout_ms, const fido_sigset_t *mask)
{
    struct pollfd pfd = {.fd = fd, .events = POLLIN};
    (void)mask;
    return poll(&pfd, 1, timeout_ms) > 0 ? 0 : -1;
}

static int decode_hex(const char *hex, uint8_t *out, size_t capacity, size_t *out_len)
{
    size_t n = strlen(hex);
    if (n == 0 || (n & 1) != 0 || n / 2 > capacity) {
        return -1;
    }
    for (size_t i = 0; i < n / 2; i++) {
        unsigned value;
        if (sscanf(hex + i * 2, "%2x", &value) != 1) {
            return -1;
        }
        out[i] = (uint8_t)value;
    }
    *out_len = n / 2;
    return 0;
}

static int transceive(int fd,
                      const uint8_t *command,
                      size_t command_len,
                      uint8_t *response,
                      size_t response_capacity,
                      size_t *response_len)
{
    ssize_t n;
    if (write(fd, command, command_len) != (ssize_t)command_len) {
        return -1;
    }
    n = read(fd, response, response_capacity);
    if (n < 1 || response[0] != 0x00) {
        return -1;
    }
    memmove(response, response + 1, (size_t)n - 1);
    *response_len = (size_t)n - 1;
    return 0;
}

static int response_ok(const uint8_t *response, size_t response_len)
{
    return response_len >= 2 && response[response_len - 2] == 0x90 && response[response_len - 1] == 0x00;
}

int main(int argc, char **argv)
{
    static const uint8_t select_otp[] = {
        0x00, 0xa4, 0x04, 0x00, 0x07, 0xa0, 0x00, 0x00, 0x05, 0x27, 0x20, 0x01, 0x00,
    };
    uint8_t challenge[64], command[70], response[256];
    size_t challenge_len, response_len;
    uint32_t target;
    struct sockaddr_nfc address = {0};
    struct fido_nl *netlink = NULL;
    int fd = -1, rc = 1;

    if (argc != 3 || (strcmp(argv[1], "1") != 0 && strcmp(argv[1], "2") != 0)
        || decode_hex(argv[2], challenge, sizeof(challenge), &challenge_len) < 0) {
        fprintf(stderr, "usage: %s <1|2> <hex-challenge-up-to-64-bytes>\n", argv[0]);
        return 2;
    }

    if ((netlink = fido_nl_new()) == NULL || fido_nl_power_nfc(netlink, 0) < 0) {
        fprintf(stderr, "cannot power nfc0; inspect the preceding netlink status\n");
        goto done;
    }
    fprintf(stderr, "hold the YubiKey against the phone...\n");
    if (fido_nl_get_nfc_target(netlink, 0, &target) < 0) {
        fprintf(stderr, "no ISO-DEP NFC target found\n");
        goto done;
    }

    address.sa_family = AF_NFC;
    address.dev_idx = 0;
    address.target_idx = target;
    address.nfc_protocol = NFC_PROTO_ISO14443;
    if ((fd = socket(AF_NFC, SOCK_SEQPACKET | SOCK_CLOEXEC, NFC_SOCKPROTO_RAW)) < 0
        || connect(fd, (struct sockaddr *)&address, sizeof(address)) < 0) {
        perror("connect NFC target");
        goto done;
    }

    if (transceive(fd, select_otp, sizeof(select_otp), response, sizeof(response), &response_len) < 0
        || !response_ok(response, response_len)) {
        fprintf(stderr, "YubiKey OTP applet selection failed\n");
        goto done;
    }

    command[0] = 0x00;
    command[1] = 0x01;
    command[2] = strcmp(argv[1], "1") == 0 ? 0x30 : 0x38;
    command[3] = 0x00;
    command[4] = (uint8_t)challenge_len;
    memcpy(command + 5, challenge, challenge_len);
    command[5 + challenge_len] = 0x00;

    if (transceive(fd, command, challenge_len + 6, response, sizeof(response), &response_len) < 0
        || !response_ok(response, response_len) || response_len != 22) {
        fprintf(stderr, "challenge-response failed\n");
        goto done;
    }

    for (size_t i = 0; i < 20; i++) {
        printf("%02x", response[i]);
    }
    putchar('\n');
    rc = 0;

done:
    if (fd >= 0) {
        close(fd);
    }
    fido_nl_free(&netlink);
    return rc;
}
