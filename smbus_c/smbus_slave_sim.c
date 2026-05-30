/*
 * smbus_slave_sim.c — SMBus Slave simulator
 *
 * Simulates a QEMU SMBus Slave that:
 *   1. Connects to the adapter's Unix socket
 *   2. Sends a sequence of CCI commands (IDENTIFY, CONFIG_PID, GET_DRT, SET_DRT)
 *   3. Prints the responses received back (acting as SMBus Master)
 *
 * This is the integration test for the full stack:
 *   smbus_slave_sim  →  smbus_mctp_adapter  →  TCP:8300  →  FM+Switch
 *
 * Build:
 *   gcc -O2 -Wall -o smbus_slave_sim smbus_slave_sim.c
 *
 * Usage:
 *   ./smbus_slave_sim [unix_socket_path]
 *   ./smbus_slave_sim /tmp/smbus_mctp.sock
 */

#include "mctp_packet.h"
#include "smbus_mctp_adapter.h"   /* for read_exact / write_exact */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>

#include <sys/socket.h>
#include <sys/un.h>

/* ── Colour output ─────────────────────────────────────────────────────── */
#define BOLD    "\033[1m"
#define CYAN    "\033[96m"
#define GREEN   "\033[92m"
#define YELLOW  "\033[93m"
#define RED     "\033[91m"
#define RESET   "\033[0m"

/* ── Connect to adapter Unix socket ────────────────────────────────────── */

static int connect_adapter(const char *path)
{
    struct sockaddr_un addr;
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) {
        perror("socket");
        return -1;
    }
    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, path, sizeof(addr.sun_path) - 1);

    if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        fprintf(stderr, RED "[slave] Cannot connect to %s: %s\n" RESET,
                path, strerror(errno));
        close(fd);
        return -1;
    }
    return fd;
}

/* ── Send one CCI command and receive response ────────────────────────── */

static int send_cci_command(int fd, uint16_t opcode,
                             const void *payload, uint32_t plen,
                             uint8_t tag, mctp_pkt_t *resp_out)
{
    mctp_pkt_t req;
    mctp_build_request(&req, opcode, tag, payload, plen, 0);

    printf(CYAN "  → TX  opcode=0x%04X (%s) tag=%u payload=%u B\n" RESET,
           opcode, mctp_opcode_name(opcode), tag, plen);

    if (write_exact(fd, req.data, req.total_len) != 0) {
        fprintf(stderr, RED "  [slave] send failed\n" RESET);
        return -1;
    }

    /* Read response SystemHeader first */
    uint8_t sys_hdr[2];
    if (read_exact(fd, sys_hdr, 2) != 0) {
        fprintf(stderr, RED "  [slave] adapter disconnected\n" RESET);
        return -1;
    }
    uint16_t resp_len = mctp_get_payload_length(sys_hdr);
    if (resp_len < MCTP_HEADER_SIZE || resp_len > MCTP_MAX_PACKET) {
        fprintf(stderr, RED "  [slave] bad response length %u\n" RESET, resp_len);
        return -1;
    }
    memcpy(resp_out->data, sys_hdr, 2);
    if (read_exact(fd, resp_out->data + 2, resp_len - 2) != 0) {
        fprintf(stderr, RED "  [slave] response truncated\n" RESET);
        return -1;
    }
    mctp_parse(resp_out, resp_len);

    uint16_t rc = mctp_get_return_code(resp_out->data);
    uint8_t  bg = mctp_get_background(resp_out->data);
    printf(GREEN "  ← RX  opcode=0x%04X tag=%u rc=%s(%u) bg=%u payload=%u B\n" RESET,
           mctp_get_opcode(resp_out->data),
           mctp_get_msg_tag(resp_out->data),
           mctp_rc_name(rc), rc, bg, resp_out->payload_len);

    return 0;
}

/* ── Helper: dump response payload as hex ─────────────────────────────── */
static void dump_hex(const char *label, const uint8_t *data, uint32_t len)
{
    printf(YELLOW "     %s [%u bytes]: ", label, len);
    for (uint32_t i = 0; i < len && i < 32; i++)
        printf("%02X ", data[i]);
    if (len > 32) printf("...");
    printf(RESET "\n");
}

/* ── Build CONFIGURE_PID_ASSIGNMENT payload ──────────────────────────── */
/*
 * ConfigurePidAssignment payload (from opencis CCI spec):
 *   operation    : 1 byte  (0=SET, 1=CLEAR)
 *   reserved     : 1 byte
 *   num_entries  : 2 bytes LE
 *   entries[N]:
 *     pid        : 2 bytes LE (12-bit PID in low bits)
 *     target_id  : 2 bytes LE (port index)
 */
typedef struct __attribute__((packed)) {
    uint8_t  operation;      /* 0 = SET */
    uint8_t  reserved;
    uint16_t num_entries;
    struct __attribute__((packed)) {
        uint16_t pid;        /* 12-bit PID */
        uint16_t target_id;  /* switch port index */
    } entries[1];
} pbr_cfg_pid_req_t;

/* ── Build GET_PID_BINDING payload ──────────────────────────────────── */
typedef struct __attribute__((packed)) {
    uint8_t  vcs_id;
    uint8_t  vppb_id;
} pbr_get_bind_req_t;

/* ── Build SET_DRT payload ──────────────────────────────────────────── */
/*
 * SetDrt payload:
 *   pid          : 2 bytes LE
 *   num_entries  : 1 byte
 *   reserved     : 1 byte
 *   entries[N]:
 *     entry_type : 1 byte (0=PHYSICAL_PORT, 1=LOGICAL_DEVICE)
 *     reserved   : 1 byte
 *     target     : 2 bytes LE (port index or LD index)
 */
typedef struct __attribute__((packed)) {
    uint16_t pid;
    uint8_t  num_entries;
    uint8_t  reserved;
    struct __attribute__((packed)) {
        uint8_t  entry_type;   /* 0 = PHYSICAL_PORT */
        uint8_t  reserved;
        uint16_t target;       /* port index */
    } entries[1];
} pbr_set_drt_req_t;

/* ── Test suite ─────────────────────────────────────────────────────── */

static int run_pbr_test_sequence(int fd)
{
    mctp_pkt_t resp;
    uint8_t tag = 0;
    int rc;

    printf(BOLD "\n╔══════════════════════════════════════════╗\n" RESET);
    printf(BOLD "║  PBR Switch CCI Integration Test Suite  ║\n" RESET);
    printf(BOLD "╚══════════════════════════════════════════╝\n\n" RESET);

    /* ── Test 1: IDENTIFY_PBR_SWITCH ──────────────────────────────── */
    printf(BOLD "─── Test 1: IDENTIFY_PBR_SWITCH (0x5700) ───\n" RESET);
    rc = send_cci_command(fd, OPCODE_IDENTIFY_PBR_SWITCH, NULL, 0, tag++, &resp);
    if (rc != 0) return -1;
    if (resp.payload_len > 0)
        dump_hex("PBR caps", mctp_payload(&resp), resp.payload_len);

    /* ── Test 2: CONFIGURE_PID_ASSIGNMENT ─────────────────────────── */
    printf(BOLD "\n─── Test 2: CONFIGURE_PID_ASSIGNMENT (0x5704) ───\n" RESET);
    pbr_cfg_pid_req_t cfg_pid = {0};
    cfg_pid.operation  = 0;   /* SET */
    cfg_pid.num_entries = 1;
    cfg_pid.entries[0].pid       = 0x010;  /* PID = 0x010 */
    cfg_pid.entries[0].target_id = 1;      /* target DSP port 1 */

    rc = send_cci_command(fd, OPCODE_CONFIGURE_PID_ASSIGNMENT,
                          &cfg_pid, sizeof(cfg_pid), tag++, &resp);
    if (rc != 0) return -1;

    /* ── Test 3: GET_PID_BINDING (before binding) ─────────────────── */
    printf(BOLD "\n─── Test 3: GET_PID_BINDING before bind (0x5705) ───\n" RESET);
    pbr_get_bind_req_t get_bind = { .vcs_id = 0, .vppb_id = 0 };
    rc = send_cci_command(fd, OPCODE_GET_PID_BINDING,
                          &get_bind, sizeof(get_bind), tag++, &resp);
    if (rc != 0) return -1;
    if (resp.payload_len >= 2) {
        uint16_t bound_pid = (uint16_t)mctp_payload(&resp)[0]
                           | ((uint16_t)mctp_payload(&resp)[1] << 8);
        printf(YELLOW "     Bound PID = 0x%03X (%s)\n" RESET,
               bound_pid,
               (bound_pid == 0xFFF) ? "UNBOUND (expected)" : "BOUND");
    }

    /* ── Test 4: SET_DRT ───────────────────────────────────────────── */
    printf(BOLD "\n─── Test 4: SET_DRT (0x5709) ───\n" RESET);
    pbr_set_drt_req_t set_drt = {0};
    set_drt.pid         = 0x010;
    set_drt.num_entries = 1;
    set_drt.entries[0].entry_type = 0; /* PHYSICAL_PORT */
    set_drt.entries[0].target     = 1; /* port index 1 */

    rc = send_cci_command(fd, OPCODE_SET_DRT,
                          &set_drt, sizeof(set_drt), tag++, &resp);
    if (rc != 0) return -1;

    /* ── Test 5: GET_DRT ───────────────────────────────────────────── */
    printf(BOLD "\n─── Test 5: GET_DRT (0x5708) ───\n" RESET);
    uint8_t get_drt_req[2] = { 0x10, 0x00 }; /* PID = 0x010 little-endian */
    rc = send_cci_command(fd, OPCODE_GET_DRT,
                          get_drt_req, 2, tag++, &resp);
    if (rc != 0) return -1;
    if (resp.payload_len > 0)
        dump_hex("DRT entry", mctp_payload(&resp), resp.payload_len);

    /* ── Test 6: CONFIGURE_PID_BINDING (background command) ────────── */
    printf(BOLD "\n─── Test 6: CONFIGURE_PID_BINDING (0x5706, background) ───\n" RESET);
    /*
     * ConfigurePidBinding payload:
     *   operation : 1 byte (0=BIND, 1=UNBIND)
     *   vcs_id    : 1 byte
     *   vppb_id   : 1 byte
     *   reserved  : 1 byte
     *   pid       : 2 bytes LE
     */
    uint8_t bind_req[6] = {
        0,       /* BIND */
        0,       /* vcs_id = 0 */
        0,       /* vppb_id = 0 */
        0,       /* reserved */
        0x10, 0x00 /* PID = 0x010 LE */
    };
    rc = send_cci_command(fd, OPCODE_CONFIGURE_PID_BINDING,
                          bind_req, sizeof(bind_req), tag++, &resp);
    if (rc != 0) return -1;
    /* Expect BACKGROUND_COMMAND_STARTED */
    if (mctp_get_background(resp.data)) {
        printf(GREEN "     ✓ Background command started as expected\n" RESET);
    }

    /* ── Test 7: GET_PID_BINDING (after binding) ──────────────────── */
    printf(BOLD "\n─── Test 7: GET_PID_BINDING after bind (0x5705) ───\n" RESET);
    rc = send_cci_command(fd, OPCODE_GET_PID_BINDING,
                          &get_bind, sizeof(get_bind), tag++, &resp);
    if (rc != 0) return -1;
    if (resp.payload_len >= 2) {
        uint16_t bound_pid = (uint16_t)mctp_payload(&resp)[0]
                           | ((uint16_t)mctp_payload(&resp)[1] << 8);
        printf(YELLOW "     Bound PID = 0x%03X\n" RESET, bound_pid);
    }

    /* ── Test 8: IDENTIFY_GAE ─────────────────────────────────────── */
    printf(BOLD "\n─── Test 8: IDENTIFY_GAE (0x5800) ───\n" RESET);
    rc = send_cci_command(fd, OPCODE_IDENTIFY_GAE, NULL, 0, tag++, &resp);
    if (rc != 0) return -1;
    if (resp.payload_len > 0)
        dump_hex("GAE caps", mctp_payload(&resp), resp.payload_len);

    printf(BOLD GREEN "\n✓ All tests sent successfully.\n\n" RESET);
    return 0;
}

/* ── main ─────────────────────────────────────────────────────────────── */

int main(int argc, char *argv[])
{
    const char *unix_path = (argc > 1) ? argv[1] : ADAPTER_DEFAULT_UNIX_PATH;

    printf(BOLD CYAN
           "\n╔═══════════════════════════════════════════════╗\n"
           "║  SMBus Slave Simulator + Integration Tester  ║\n"
           "╚═══════════════════════════════════════════════╝\n\n"
           RESET);

    printf("Connecting to adapter: %s\n", unix_path);

    int fd = connect_adapter(unix_path);
    if (fd < 0) {
        fprintf(stderr,
            RED "Cannot connect.\n"
            "Make sure the adapter is running:\n"
            "  ./smbus_mctp_adapter %s\n"
            "And the FM is up:\n"
            "  python run_pbr_env.py --smbus-bridge %s\n" RESET,
            unix_path, unix_path);
        return 1;
    }

    printf(GREEN "Connected to adapter.\n\n" RESET);

    int rc = run_pbr_test_sequence(fd);

    close(fd);
    return (rc == 0) ? 0 : 1;
}
