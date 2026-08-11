// SPDX-License-Identifier: GPL-2.0-only

#include <arpa/inet.h>
#include <ifdhandler.h>
#include <reader.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

static int failures;

#define CHECK_EQ(actual, expected) check_eq(__LINE__, #actual, (actual), (expected))

static void check_eq(int line, const char *expression, unsigned long actual,
		unsigned long expected)
{
	if (actual == expected)
		return;

	fprintf(stderr, "line %d: %s returned 0x%lx, expected 0x%lx\n",
		line, expression, actual, expected);
	failures++;
}

int main(void)
{
	unsigned char buffer[32] = {0};
	PCSC_TLV_STRUCTURE tlv;
	SCARD_IO_HEADER recv_pci = {0};
	DWORD length;
	DWORD returned;
	void *polling = NULL;

	CHECK_EQ(IFDHCloseChannel(0), IFD_COMMUNICATION_ERROR);
	CHECK_EQ(IFDHICCPresence(0), IFD_COMMUNICATION_ERROR);
	CHECK_EQ(IFDHSetCapabilities(0, 0, 0, NULL), IFD_ERROR_VALUE_READ_ONLY);
	CHECK_EQ(IFDHSetProtocolParameters(0, SCARD_PROTOCOL_T1, 0, 0, 0, 0),
		IFD_SUCCESS);
	CHECK_EQ(IFDHSetProtocolParameters(0, SCARD_PROTOCOL_T0, 0, 0, 0, 0),
		IFD_PROTOCOL_NOT_SUPPORTED);

	length = 1;
	CHECK_EQ(IFDHGetCapabilities(0, TAG_IFD_THREAD_SAFE, &length, buffer),
		IFD_SUCCESS);
	CHECK_EQ(length, 1);
	CHECK_EQ(buffer[0], 0);

	length = sizeof(void *) - 1;
	CHECK_EQ(IFDHGetCapabilities(0, TAG_IFD_POLLING_THREAD_WITH_TIMEOUT,
		&length, buffer), IFD_ERROR_INSUFFICIENT_BUFFER);
	length = sizeof(void *);
	CHECK_EQ(IFDHGetCapabilities(0, TAG_IFD_POLLING_THREAD_WITH_TIMEOUT,
		&length, buffer), IFD_SUCCESS);
	memcpy(&polling, buffer, sizeof(polling));
	CHECK_EQ(polling != NULL, 1);

	CHECK_EQ(IFDHPowerICC(0, IFD_POWER_UP, buffer, NULL),
		IFD_COMMUNICATION_ERROR);
	CHECK_EQ(IFDHTransmitToICC(0, (SCARD_IO_HEADER){SCARD_PROTOCOL_T1, 0},
		buffer, 1, buffer, NULL, &recv_pci), IFD_COMMUNICATION_ERROR);

	CHECK_EQ(IFDHControl(0, CM_IOCTL_GET_FEATURE_REQUEST, NULL, 0,
		buffer, sizeof(buffer), NULL), IFD_COMMUNICATION_ERROR);
	returned = 99;
	CHECK_EQ(IFDHControl(0, CM_IOCTL_GET_FEATURE_REQUEST, NULL, 0,
		buffer, sizeof(PCSC_TLV_STRUCTURE) - 1, &returned),
		IFD_ERROR_INSUFFICIENT_BUFFER);
	CHECK_EQ(returned, 0);
	CHECK_EQ(IFDHControl(0, CM_IOCTL_GET_FEATURE_REQUEST, NULL, 0,
		buffer, sizeof(buffer), &returned), IFD_SUCCESS);
	CHECK_EQ(returned, sizeof(PCSC_TLV_STRUCTURE));
	memcpy(&tlv, buffer, sizeof(tlv));
	CHECK_EQ(tlv.tag, FEATURE_GET_TLV_PROPERTIES);
	CHECK_EQ(tlv.length, 4);
	CHECK_EQ(ntohl(tlv.value),
		SCARD_CTL_CODE(FEATURE_GET_TLV_PROPERTIES + 0x330000));

	returned = 99;
	CHECK_EQ(IFDHControl(0,
		SCARD_CTL_CODE(FEATURE_GET_TLV_PROPERTIES + 0x330000), NULL, 0,
		buffer, 5, &returned), IFD_ERROR_INSUFFICIENT_BUFFER);
	CHECK_EQ(returned, 0);
	CHECK_EQ(IFDHControl(0,
		SCARD_CTL_CODE(FEATURE_GET_TLV_PROPERTIES + 0x330000), NULL, 0,
		buffer, sizeof(buffer), &returned), IFD_SUCCESS);
	CHECK_EQ(returned, 6);
	CHECK_EQ(buffer[0], PCSCv2_PART10_PROPERTY_dwMaxAPDUDataSize);
	CHECK_EQ(buffer[1], 4);
	CHECK_EQ(buffer[2], 0xff);
	CHECK_EQ(buffer[3], 0xff);
	CHECK_EQ(buffer[4], 0);
	CHECK_EQ(buffer[5], 0);

	if (failures) {
		fprintf(stderr, "%d IFD contract check(s) failed\n", failures);
		return 1;
	}

	puts("IFD contract checks passed");
	return 0;
}
