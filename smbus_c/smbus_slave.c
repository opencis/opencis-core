/*
 * smbus_slave.c — SMBus Slave: sends CCI requests to the adapter
 *
 * Represents the QEMU SMBus Slave device that generates MCTP CCI packets.
 * Connects to the adapter's SLAVE socket, sends a sequence of CCI commands,
 * then disconnects. The adapter forwards each request to FM:8300 and routes
 * the response to the SMBus Master (separate process/connection).
 *
 * This program does NOT read back any response — that is the Master's job.
 *
 * Build:
 *   gcc -O2 -Wall -o smbus_slave smbus_slave.c
 *
 * Usage:
 *   ./smbus_slave [slave_socket_path]
 *   ./smbus_slave /tmp/smbus_slave.sock
 *
 * Run order:
 *   Terminal 1: ./smbus_mctp_adapter
 *   Terminal 2: ./smbus_master        ← connects first
 *   Terminal 3: ./smbus_slave         ← connects second, triggers relay
 */

#include "mctp_packet.h"
#include "smbus_mctp_adapter.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>
#include <sys/socket.h>
#include <sys/un.h>

/* ── Colours ─────────────────────────────────────────────────────────── */
#define BOLD    "\033[1m"
#define CYAN    "\033[96m"
#define GREEN   "\033[92m"
#define YELLOW  "\033[93m"
#define RED     "\033[91m"
#define RESET   "\033[0m"

/* ── Connect to adapter slave socket ─────────────────────────────────── */
static int connect_slave_sock(const char *path)
{
    struct sockaddr_un addr;
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) { perror("socket"); return -1; }

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

/* ── Send one CCI request (does NOT read back response) ─────────────── */
static int send_request(int fd, uint16_t opcode,
                         const void *payload, uint32_t plen, uint8_t tag)
{
    mctp_pkt_t pkt;
    mctp_build_request(&pkt, opcode, tag, payload, plen, 0);

    printf(YELLOW "  [slave TX] opcode=0x%04X (%s) tag=%u payload=%u B\n" RESET,
           opcode, mctp_opcode_name(opcode), tag, plen);

    if (write_exact(fd, pkt.data, pkt.total_len) != 0) {
        fprintf(stderr, RED "[slave] write failed: %s\n" RESET, strerror(errno));
        return -1;
    }
    return 0;
}

/* ── CCI payload structs ─────────────────────────────────────────────── */

/* ConfigurePidAssignment */
typedef struct __attribute__((packed)) {
    uint8_t  operation;      /* 0=SET, 1=CLEAR */
    uint8_t  reserved;
    uint16_t num_entries;
    struct __attribute__((packed)) {
        uint16_t pid;
        uint16_t target_id;
    } entries[1];
} pbr_cfg_pid_req_t;

/* GetPidBinding */
typedef struct __attribute__((packed)) {
    uint8_t vcs_id;
    uint8_t vppb_id;
} pbr_get_bind_req_t;

/* SetDrt */
typedef struct __attribute__((packed)) {
    uint16_t pid;
    uint8_t  num_entries;
    uint8_t  reserved;
    struct __attribute__((packed)) {
        uint8_t  entry_type;   /* 0=PHYSICAL_PORT */
        uint8_t  reserved;
        uint16_t target;
    } entries[1];
} pbr_set_drt_req_t;

/* GetDrt */
typedef struct __attribute__((packed)) {
    uint16_t pid;
} pbr_get_drt_req_t;

/* ConfigurePidBinding */
typedef struct __attribute__((packed)) {
    uint8_t  operation;   /* 0=BIND, 1=UNBIND */
    uint8_t  vcs_id;
    uint8_t  vppb_id;
    uint8_t  reserved;
    uint16_t pid;
} pbr_cfg_bind_req_t;

/* ── Main CCI command sequence ──────────────────────────────────────── */
static int run_cci_sequence(int fd)
{
    uint8_t tag = 0;

    printf(BOLD CYAN
           "\n╔═══════════════════════════════════════════╗\n"
           "║  SMBus Slave — Sending CCI Command Set   ║\n"
           "╚═══════════════════════════════════════════╝\n\n"
           RESET);

#define SEND(opcode, payload, plen) \
    do { \
        if (send_request(fd, opcode, payload, plen, tag++) != 0) return -1; \
        usleep(10000); /* 10ms gap between commands */ \
    } while(0)

    /* 1. IDENTIFY_PBR_SWITCH */
    printf(BOLD "── Cmd 1: IDENTIFY_PBR_SWITCH ──\n" RESET);
    SEND(OPCODE_IDENTIFY_PBR_SWITCH, NULL, 0);

    /* 2. CONFIGURE_PID_ASSIGNMENT — assign PID 0x010 to port 1 */
    printf(BOLD "── Cmd 2: CONFIGURE_PID_ASSIGNMENT ──\n" RESET);
    pbr_cfg_pid_req_t cfg_pid = {0};
    cfg_pid.operation   = 0;   /* SET */
    cfg_pid.num_entries = 1;
    cfg_pid.entries[0].pid       = 0x010;
    cfg_pid.entries[0].target_id = 1;
    SEND(OPCODE_CONFIGURE_PID_ASSIGNMENT, &cfg_pid, sizeof(cfg_pid));

    /* 3. GET_PID_BINDING — before binding (expect 0xFFF = UNBOUND) */
    printf(BOLD "── Cmd 3: GET_PID_BINDING (before bind) ──\n" RESET);
    pbr_get_bind_req_t get_bind = { .vcs_id = 0, .vppb_id = 0 };
    SEND(OPCODE_GET_PID_BINDING, &get_bind, sizeof(get_bind));

    /* 4. SET_DRT — DRT[PID=0x010] = physical port 1 */
    printf(BOLD "── Cmd 4: SET_DRT ──\n" RESET);
    pbr_set_drt_req_t set_drt = {0};
    set_drt.pid         = 0x010;
    set_drt.num_entries = 1;
    set_drt.entries[0].entry_type = 0;  /* PHYSICAL_PORT */
    set_drt.entries[0].target     = 1;
    SEND(OPCODE_SET_DRT, &set_drt, sizeof(set_drt));

    /* 5. GET_DRT — read back what we programmed */
    printf(BOLD "── Cmd 5: GET_DRT ──\n" RESET);
    pbr_get_drt_req_t get_drt = { .pid = 0x010 };
    SEND(OPCODE_GET_DRT, &get_drt, sizeof(get_drt));

    /* 6. CONFIGURE_PID_BINDING — bind VPPB 0 to PID 0x010 (background cmd) */
    printf(BOLD "── Cmd 6: CONFIGURE_PID_BINDING ──\n" RESET);
    pbr_cfg_bind_req_t bind_req = {0};
    bind_req.operation = 0;     /* BIND */
    bind_req.vcs_id    = 0;
    bind_req.vppb_id   = 0;
    bind_req.pid       = 0x010;
    SEND(OPCODE_CONFIGURE_PID_BINDING, &bind_req, sizeof(bind_req));

    /* 7. GET_PID_BINDING — after binding (expect 0x010 = bound) */
    printf(BOLD "── Cmd 7: GET_PID_BINDING (after bind) ──\n" RESET);
    SEND(OPCODE_GET_PID_BINDING, &get_bind, sizeof(get_bind));

    /* 8. IDENTIFY_GAE */
    printf(BOLD "── Cmd 8: IDENTIFY_GAE ──\n" RESET);
    SEND(OPCODE_IDENTIFY_GAE, NULL, 0);

    /* 9. GET_PID_ACCESS_VECTORS */
    printf(BOLD "── Cmd 9: GET_PID_ACCESS_VECTORS ──\n" RESET);
    SEND(OPCODE_GET_PID_ACCESS_VECTORS, NULL, 0);

#undef SEND

    printf(BOLD GREEN
           "\n✓ All %u CCI commands sent to adapter.\n"
           "  Check smbus_master output for responses.\n\n"
           RESET, tag);
    return 0;
}

/* ── main ─────────────────────────────────────────────────────────────── */
int main(int argc, char *argv[])
{
    const char *sock_path = (argc > 1) ? argv[1] : ADAPTER_SLAVE_SOCK_PATH;

    printf(BOLD CYAN
           "\n SMBus Slave Simulator\n"
           " Slave socket: %s\n\n" RESET, sock_path);

    printf("Connecting to adapter slave socket...\n");
    int fd = connect_slave_sock(sock_path);
    if (fd < 0) {
        fprintf(stderr,
            RED "  Tip: start adapter first:\n"
            "    ./smbus_mctp_adapter\n"
            "  Then start master:\n"
            "    ./smbus_master\n"
            "  Then run this slave.\n" RESET);
        return 1;
    }
    printf(GREEN "  Connected.\n\n" RESET);

    int rc = run_cci_sequence(fd);
    close(fd);
    return (rc == 0) ? 0 : 1;
}
