/*
 * test_mctp_packet.c — Unit tests for mctp_packet.h wire format
 *
 * Verifies that mctp_build_request() produces bytes that the Python
 * FmMctpCciServer can decode correctly, and that mctp_get_* accessors
 * correctly read back those fields.
 *
 * Build:
 *   gcc -O2 -Wall -o test_mctp_packet test_mctp_packet.c
 *
 * Usage:
 *   ./test_mctp_packet
 */

#include "mctp_packet.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <assert.h>

/* ── Minimal test framework ─────────────────────────────────────────── */
static int g_pass = 0, g_fail = 0;

#define EXPECT_EQ(a, b, msg) do {                                        \
    if ((a) == (b)) {                                                    \
        printf("  \033[92m✓\033[0m %s\n", msg);                         \
        g_pass++;                                                        \
    } else {                                                             \
        printf("  \033[91m✗\033[0m %s  (got %llu, expected %llu)\n",    \
               msg, (unsigned long long)(a), (unsigned long long)(b));   \
        g_fail++;                                                        \
    }                                                                    \
} while(0)

#define EXPECT_NE(a, b, msg) do {                                        \
    if ((a) != (b)) {                                                    \
        printf("  \033[92m✓\033[0m %s\n", msg);                         \
        g_pass++;                                                        \
    } else {                                                             \
        printf("  \033[91m✗\033[0m %s  (should not be %llu)\n",         \
               msg, (unsigned long long)(a));                            \
        g_fail++;                                                        \
    }                                                                    \
} while(0)

#define SECTION(name) printf("\n\033[1m─── %s ───\033[0m\n", name)

/* ── Tests ──────────────────────────────────────────────────────────── */

static void test_system_header_encoding(void)
{
    SECTION("SystemHeader encoding");
    mctp_pkt_t pkt;
    mctp_build_request(&pkt, OPCODE_IDENTIFY_PBR_SWITCH, 0, NULL, 0, 0);

    /* total = 16 (header only, no payload) */
    EXPECT_EQ(pkt.total_len, 16, "total_len == MCTP_HEADER_SIZE");

    /* payload_type field: bits[3:0] of byte[0] == 4 (CCI_MCTP) */
    uint8_t pt = pkt.data[0] & 0x0F;
    EXPECT_EQ(pt, MCTP_PAYLOAD_TYPE_CCI, "payload_type == CCI_MCTP(4)");

    /* payload_length decoded == total_len */
    uint16_t plen = mctp_get_payload_length(pkt.data);
    EXPECT_EQ(plen, 16, "decoded payload_length == 16");
}

static void test_system_header_with_payload(void)
{
    SECTION("SystemHeader with payload");
    uint8_t payload[10] = {1,2,3,4,5,6,7,8,9,10};
    mctp_pkt_t pkt;
    mctp_build_request(&pkt, OPCODE_SET_DRT, 5, payload, 10, 0);

    EXPECT_EQ(pkt.total_len, 26, "total_len == 16 + 10");
    uint16_t plen = mctp_get_payload_length(pkt.data);
    EXPECT_EQ(plen, 26, "decoded payload_length == 26");
}

static void test_cci_header(void)
{
    SECTION("CciHeader (port_index, msg_class)");
    mctp_pkt_t pkt;
    mctp_build_request(&pkt, OPCODE_IDENTIFY_PBR_SWITCH, 0, NULL, 0, 3 /* port */);

    /* byte[2] = port_index, byte[3] = msg_class */
    EXPECT_EQ(pkt.data[2], 3, "port_index == 3");
    EXPECT_EQ(pkt.data[3], MCTP_MSG_CLASS_REQ, "msg_class == REQ(1)");
    EXPECT_EQ(mctp_get_msg_class(pkt.data), MCTP_MSG_CLASS_REQ, "get_msg_class() == REQ");
}

static void test_message_category(void)
{
    SECTION("CciMessageHeader.message_category");
    mctp_pkt_t pkt;
    mctp_build_request(&pkt, OPCODE_IDENTIFY_PBR_SWITCH, 0, NULL, 0, 0);

    /* bits[3:0] of byte[4] == REQUEST(0) */
    uint8_t cat = mctp_get_msg_category(pkt.data);
    EXPECT_EQ(cat, MCTP_MSG_CATEGORY_REQUEST, "message_category == REQUEST(0)");
}

static void test_message_tag(void)
{
    SECTION("CciMessageHeader.message_tag auto-sequence");
    mctp_pkt_t pkt;

    for (uint8_t t = 0; t < 4; t++) {
        mctp_build_request(&pkt, OPCODE_IDENTIFY_PBR_SWITCH, t, NULL, 0, 0);
        uint8_t got = mctp_get_msg_tag(pkt.data);
        char msg[64];
        snprintf(msg, sizeof(msg), "tag=%u round-trips", t);
        EXPECT_EQ(got, t, msg);
    }

    /* tag wraps: 255 → encodes as 0xFF */
    mctp_build_request(&pkt, OPCODE_IDENTIFY_PBR_SWITCH, 255, NULL, 0, 0);
    EXPECT_EQ(mctp_get_msg_tag(pkt.data), 255, "tag=255 round-trips");
}

static void test_opcode_encoding(void)
{
    SECTION("CciMessageHeader.command_opcode");
    struct { uint16_t opcode; const char *name; } cases[] = {
        { OPCODE_IDENTIFY_PBR_SWITCH,       "IDENTIFY_PBR_SWITCH"       },
        { OPCODE_CONFIGURE_PID_ASSIGNMENT,  "CONFIGURE_PID_ASSIGNMENT"  },
        { OPCODE_GET_PID_BINDING,           "GET_PID_BINDING"           },
        { OPCODE_CONFIGURE_PID_BINDING,     "CONFIGURE_PID_BINDING"     },
        { OPCODE_GET_DRT,                   "GET_DRT"                   },
        { OPCODE_SET_DRT,                   "SET_DRT"                   },
        { OPCODE_IDENTIFY_GAE,              "IDENTIFY_GAE"              },
    };
    mctp_pkt_t pkt;
    for (size_t i = 0; i < sizeof(cases)/sizeof(cases[0]); i++) {
        mctp_build_request(&pkt, cases[i].opcode, 0, NULL, 0, 0);
        uint16_t got = mctp_get_opcode(pkt.data);
        char msg[80];
        snprintf(msg, sizeof(msg), "opcode 0x%04X (%s) round-trips",
                 cases[i].opcode, cases[i].name);
        EXPECT_EQ(got, cases[i].opcode, msg);
    }
}

static void test_payload_length_field(void)
{
    SECTION("CciMessageHeader.message_payload_length");
    mctp_pkt_t pkt;
    uint8_t payload[64];
    memset(payload, 0xAB, sizeof(payload));

    mctp_build_request(&pkt, OPCODE_SET_DRT, 0, payload, 64, 0);

    uint32_t got = mctp_get_payload_len(pkt.data);
    EXPECT_EQ(got, 64, "payload_length field == 64");
}

static void test_payload_data_preserved(void)
{
    SECTION("Payload bytes preserved correctly");
    uint8_t in_data[8] = {0xDE, 0xAD, 0xBE, 0xEF, 0x01, 0x02, 0x03, 0x04};
    mctp_pkt_t pkt;
    mctp_build_request(&pkt, OPCODE_GET_DRT, 0, in_data, 8, 0);

    const uint8_t *out_data = mctp_payload(&pkt);
    int match = (memcmp(in_data, out_data, 8) == 0);
    EXPECT_EQ(match, 1, "8-byte payload preserved exactly");
}

static void test_background_bit(void)
{
    SECTION("background_operation bit in response");
    /* Simulate a CONFIGURE_PID_BINDING response from FM with background=1 */
    mctp_pkt_t fake_resp;
    memset(&fake_resp, 0, sizeof(fake_resp));
    mctp_set_system_header(fake_resp.data, MCTP_HEADER_SIZE);
    mctp_set_cci_header(fake_resp.data, 0, MCTP_MSG_CLASS_RSP);
    mctp_set_msg_header(fake_resp.data,
                        MCTP_MSG_CATEGORY_RESPONSE,
                        7,                                 /* tag */
                        OPCODE_CONFIGURE_PID_BINDING,
                        0,                                 /* payload_len */
                        1,                                 /* background = 1 */
                        CCI_RC_BACKGROUND_COMMAND_STARTED);
    mctp_parse(&fake_resp, MCTP_HEADER_SIZE);

    EXPECT_EQ(mctp_get_background(fake_resp.data), 1, "background_operation == 1");
    EXPECT_EQ(mctp_get_return_code(fake_resp.data),
              CCI_RC_BACKGROUND_COMMAND_STARTED, "rc == BACKGROUND_COMMAND_STARTED");
    EXPECT_EQ(mctp_get_msg_tag(fake_resp.data), 7, "tag == 7 in response");
}

static void test_header_size_constant(void)
{
    SECTION("MCTP_HEADER_SIZE constant");
    /* SystemHeader(2) + CciHeader(2) + CciMessageHeader(12) = 16 */
    EXPECT_EQ(MCTP_HEADER_SIZE, 16, "MCTP_HEADER_SIZE == 16");
}

static void test_exact_wire_bytes_identify(void)
{
    SECTION("Exact wire bytes — IDENTIFY_PBR_SWITCH with tag=0");
    /*
     * Expected bytes for a minimal IDENTIFY_PBR_SWITCH (no payload):
     *
     * Byte 0: payload_type=4 (bits[3:0]), payload_length low nibble (bits[7:4])
     *         payload_length = 16 = 0x010
     *         bits[7:4] of byte[0] = 0x010[3:0] = 0x0
     *         bits[3:0] of byte[0] = 4 (payload_type)
     *         byte[0] = 0x04
     * Byte 1: payload_length[11:4] = 0x010 >> 4 = 0x01
     *         byte[1] = 0x01
     * Byte 2: port_index = 0
     * Byte 3: msg_class = REQ = 1
     * Byte 4: message_category=REQUEST(0) in bits[3:0], reserved in [7:4]
     *         = 0x00
     * Byte 5: message_tag = 0
     * Byte 6: reserved1 = 0
     * Byte 7: opcode_low = 0x5700 & 0xFF = 0x00
     * Byte 8: opcode_high = 0x5700 >> 8 = 0x57
     * Bytes 9-15: zeros (length=0, rc=0, etc.)
     */
    uint8_t expected[16] = {
        0x04, 0x01,  /* SystemHeader: type=4, length=16 */
        0x00, 0x01,  /* CciHeader: port=0, class=REQ(1) */
        0x00, 0x00, 0x00,  /* msg_category=REQUEST(0), tag=0, rsvd */
        0x00, 0x57,  /* opcode LE: 0x5700 → [0x00, 0x57] */
        0x00, 0x00,  /* payload_length_low = 0 */
        0x00,        /* payload_length_high[4:0], rsvd[6:5], bg[7] */
        0x00, 0x00,  /* return_code = 0 */
        0x00, 0x00,  /* vendor_status = 0 */
    };

    mctp_pkt_t pkt;
    mctp_build_request(&pkt, OPCODE_IDENTIFY_PBR_SWITCH, 0, NULL, 0, 0);

    int match = (memcmp(pkt.data, expected, 16) == 0);
    if (!match) {
        printf("  Got:      ");
        for (int i = 0; i < 16; i++) printf("%02X ", pkt.data[i]);
        printf("\n  Expected: ");
        for (int i = 0; i < 16; i++) printf("%02X ", expected[i]);
        printf("\n");
    }
    EXPECT_EQ(match, 1, "Exact wire bytes match Python-generated packet");
}

/* ── main ─────────────────────────────────────────────────────────────── */

int main(void)
{
    printf("\033[1m\033[96m"
           "╔═════════════════════════════════════════╗\n"
           "║  mctp_packet.h  Unit Test Suite         ║\n"
           "╚═════════════════════════════════════════╝\033[0m\n");

    test_header_size_constant();
    test_system_header_encoding();
    test_system_header_with_payload();
    test_cci_header();
    test_message_category();
    test_message_tag();
    test_opcode_encoding();
    test_payload_length_field();
    test_payload_data_preserved();
    test_background_bit();
    test_exact_wire_bytes_identify();

    printf("\n\033[1m═══ Results: %d passed, %d failed ═══\033[0m\n\n",
           g_pass, g_fail);

    return (g_fail == 0) ? 0 : 1;
}
