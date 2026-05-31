/*
 * smbus_master.c — SMBus Master: receives and displays CCI responses
 *
 * Represents the QEMU SMBus Master device that consumes MCTP CCI responses
 * from the CXL Fabric Manager.
 *
 * Connects to the adapter's MASTER socket.
 * Waits in a loop:
 *   - Reads each CciPayloadPacket as it arrives
 *   - Decodes all header fields
 *   - Pretty-prints the response with full field breakdown
 *   - Exits when the adapter closes the connection (slave done)
 *
 * This program does NOT send anything — only receives.
 *
 * Build:
 *   gcc -O2 -Wall -o smbus_master smbus_master.c
 *
 * Usage:
 *   ./smbus_master [master_socket_path]
 *   ./smbus_master /tmp/smbus_master.sock
 *
 * Run order:
 *   Terminal 1: python run_pbr_env.py --smbus-bridge /tmp/smbus_bridge.sock
 *               (or) ./smbus_mctp_adapter
 *   Terminal 2: ./smbus_master         ← start BEFORE slave
 *   Terminal 3: ./smbus_slave          ← sends commands, master prints responses
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
#include <time.h>

/* ── Colours ─────────────────────────────────────────────────────────── */
#define BOLD    "\033[1m"
#define CYAN    "\033[96m"
#define GREEN   "\033[92m"
#define YELLOW  "\033[93m"
#define RED     "\033[91m"
#define MAGENTA "\033[95m"
#define DIM     "\033[2m"
#define RESET   "\033[0m"

/* ── Timestamp helper ────────────────────────────────────────────────── */
static void print_timestamp(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    struct tm *t = localtime(&ts.tv_sec);
    printf(DIM "%02d:%02d:%02d.%03ld" RESET,
           t->tm_hour, t->tm_min, t->tm_sec, ts.tv_nsec / 1000000L);
}

/* ── Connect to adapter master socket ────────────────────────────────── */
static int connect_master_sock(const char *path)
{
    struct sockaddr_un addr;
    int fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) { perror("socket"); return -1; }

    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, path, sizeof(addr.sun_path) - 1);

    if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        fprintf(stderr, RED "[master] Cannot connect to %s: %s\n" RESET,
                path, strerror(errno));
        close(fd);
        return -1;
    }
    return fd;
}

/* ── Hex dump ────────────────────────────────────────────────────────── */
static void hex_dump(const uint8_t *data, uint32_t len, const char *indent)
{
    if (len == 0) { printf("%s(no payload)\n", indent); return; }

    for (uint32_t i = 0; i < len; i += 16) {
        printf("%s%04X  ", indent, i);
        /* hex */
        for (uint32_t j = i; j < i + 16; j++) {
            if (j < len) printf("%02X ", data[j]);
            else         printf("   ");
            if (j == i + 7) printf(" ");
        }
        printf(" |");
        /* ASCII */
        for (uint32_t j = i; j < i + 16 && j < len; j++)
            printf("%c", (data[j] >= 32 && data[j] < 127) ? data[j] : '.');
        printf("|\n");
    }
}

/* ── Decode and print well-known response payloads ───────────────────── */
static void decode_identify_pbr(const uint8_t *p, uint32_t len)
{
    if (len < 4) return;
    /* IdentifyPbrSwitch response (approximate layout from Python impl):
     *   bytes[0-1] : num_drts (uint16 LE)
     *   bytes[2-3] : capabilities flags
     */
    uint16_t num_drts = (uint16_t)p[0] | ((uint16_t)p[1] << 8);
    printf(CYAN "     num_drts    : %u\n" RESET, num_drts);
    if (len > 2)
        printf(CYAN "     capabilities : 0x%02X%02X\n" RESET, p[3], p[2]);
}

static void decode_get_pid_binding(const uint8_t *p, uint32_t len)
{
    if (len < 2) return;
    uint16_t pid = (uint16_t)p[0] | ((uint16_t)p[1] << 8);
    if (pid == 0xFFF)
        printf(YELLOW "     bound_pid : 0xFFF  (UNBOUND)\n" RESET);
    else
        printf(GREEN  "     bound_pid : 0x%03X  (BOUND)\n" RESET, pid);
}

static void decode_get_drt(const uint8_t *p, uint32_t len)
{
    if (len < 4) return;
    /* DRT entry: entry_type(1) + reserved(1) + target(2) */
    uint8_t  etype  = p[0];
    uint16_t target = (uint16_t)p[2] | ((uint16_t)p[3] << 8);
    const char *etype_name = (etype == 0) ? "PHYSICAL_PORT"
                           : (etype == 1) ? "LOGICAL_DEVICE"
                           : "RESERVED";
    printf(CYAN "     entry_type : %s (%u)\n" RESET, etype_name, etype);
    printf(CYAN "     target     : %u\n" RESET, target);
}

static void decode_identify_gae(const uint8_t *p, uint32_t len)
{
    if (len < 2) return;
    printf(CYAN "     gae_caps   : 0x%02X%02X\n" RESET, p[1], p[0]);
}

/* ── Pretty-print one received CCI response ──────────────────────────── */
static void print_response(int seq, const mctp_pkt_t *resp)
{
    uint16_t opcode = mctp_get_opcode(resp->data);
    uint8_t  tag    = mctp_get_msg_tag(resp->data);
    uint16_t rc     = mctp_get_return_code(resp->data);
    uint8_t  bg     = mctp_get_background(resp->data);
    uint8_t  cat    = mctp_get_msg_category(resp->data);
    uint8_t  cls    = mctp_get_msg_class(resp->data);
    uint32_t plen   = resp->payload_len;
    const uint8_t *payload = mctp_payload(resp);

    /* ── Response box ── */
    printf("\n");
    printf(BOLD "  ┌─────────────────────────────────────────────────────┐\n" RESET);
    printf(BOLD "  │  Response #%-3d  ", seq);
    print_timestamp();
    printf(BOLD "                          │\n" RESET);
    printf(BOLD "  └─────────────────────────────────────────────────────┘\n" RESET);

    /* ── SystemHeader ── */
    printf(DIM "  SystemHeader\n" RESET);
    printf("    payload_type   : CCI_MCTP (4)\n");
    printf("    payload_length : %u bytes (total)\n", resp->total_len);

    /* ── CciHeader ── */
    printf(DIM "  CciHeader\n" RESET);
    printf("    port_index     : %u\n", resp->data[2]);
    printf("    msg_class      : %s (%u)\n",
           cls == 1 ? "REQ" : cls == 2 ? "RSP" : "?", cls);

    /* ── CciMessageHeader ── */
    printf(DIM "  CciMessageHeader\n" RESET);
    printf("    message_category    : %s (%u)\n",
           cat == 0 ? "REQUEST" : cat == 1 ? "RESPONSE" : "?", cat);
    printf("    message_tag         : %u\n", tag);
    printf("    command_opcode      : " BOLD "0x%04X" RESET " (%s)\n",
           opcode, mctp_opcode_name(opcode));
    printf("    payload_length      : %u bytes\n", plen);
    printf("    background_operation: %u%s\n", bg,
           bg ? YELLOW "  ← background command started" RESET : "");

    /* ── Return code ── */
    if (rc == CCI_RC_SUCCESS)
        printf("    return_code         : " GREEN BOLD "%s (0x%04X)" RESET "\n",
               mctp_rc_name(rc), rc);
    else if (rc == CCI_RC_BACKGROUND_COMMAND_STARTED)
        printf("    return_code         : " YELLOW BOLD "%s (0x%04X)" RESET "\n",
               mctp_rc_name(rc), rc);
    else
        printf("    return_code         : " RED BOLD "%s (0x%04X)" RESET "\n",
               mctp_rc_name(rc), rc);

    /* ── Payload ── */
    printf(DIM "  Payload (%u bytes)\n" RESET, plen);
    if (plen > 0) {
        /* Decoded interpretation */
        switch (opcode) {
        case OPCODE_IDENTIFY_PBR_SWITCH:
            decode_identify_pbr(payload, plen);
            break;
        case OPCODE_GET_PID_BINDING:
            decode_get_pid_binding(payload, plen);
            break;
        case OPCODE_GET_DRT:
            decode_get_drt(payload, plen);
            break;
        case OPCODE_IDENTIFY_GAE:
            decode_identify_gae(payload, plen);
            break;
        default:
            break;
        }
        /* Raw hex dump */
        printf(DIM "    Raw hex:\n" RESET);
        hex_dump(payload, plen, "    ");
    }

    /* ── Overall status banner ── */
    if (rc == CCI_RC_SUCCESS || rc == CCI_RC_BACKGROUND_COMMAND_STARTED)
        printf(GREEN "  ✓ OK\n" RESET);
    else
        printf(RED   "  ✗ ERROR rc=0x%04X\n" RESET, rc);
}

/* ── Receive loop ─────────────────────────────────────────────────────── */
static int receive_loop(int fd)
{
    int seq = 1;
    mctp_pkt_t resp;

    printf(BOLD CYAN "\nListening for CCI responses from adapter...\n"
           "Press Ctrl+C to stop.\n\n" RESET);

    while (1) {
        /* Read SystemHeader (2 bytes) */
        uint8_t sys_hdr[2];
        ssize_t r = recv(fd, sys_hdr, 2, MSG_WAITALL);
        if (r == 0) {
            printf(BOLD "\nAdapter closed connection — all responses received.\n" RESET);
            break;
        }
        if (r < 0) {
            if (errno == EINTR) continue;
            fprintf(stderr, RED "[master] recv error: %s\n" RESET, strerror(errno));
            return -1;
        }

        uint16_t total_len = mctp_get_payload_length(sys_hdr);
        if (total_len < MCTP_HEADER_SIZE || total_len > MCTP_MAX_PACKET) {
            fprintf(stderr, RED "[master] Bad packet length %u\n" RESET, total_len);
            return -1;
        }

        memcpy(resp.data, sys_hdr, 2);
        if (read_exact(fd, resp.data + 2, total_len - 2) != 0) {
            fprintf(stderr, RED "[master] Adapter disconnected mid-packet\n" RESET);
            break;
        }
        mctp_parse(&resp, total_len);

        print_response(seq++, &resp);
    }

    /* Summary */
    printf(BOLD CYAN
           "\n╔══════════════════════════════════════════╗\n"
           "║  SMBus Master — Session Summary          ║\n"
           "╠══════════════════════════════════════════╣\n"
           "║  Total responses received: %-14d║\n"
           "╚══════════════════════════════════════════╝\n\n"
           RESET, seq - 1);
    return 0;
}

/* ── main ─────────────────────────────────────────────────────────────── */
int main(int argc, char *argv[])
{
    const char *sock_path = (argc > 1) ? argv[1] : ADAPTER_MASTER_SOCK_PATH;

    printf(BOLD CYAN
           "\n╔═══════════════════════════════════════════════╗\n"
           "║  SMBus Master — CCI Response Monitor         ║\n"
           "╠═══════════════════════════════════════════════╣\n"
           "║  Master socket: %-29s║\n"
           "╚═══════════════════════════════════════════════╝\n"
           RESET, sock_path);

    printf("\nConnecting to adapter master socket: %s\n", sock_path);

    int fd = connect_master_sock(sock_path);
    if (fd < 0) {
        fprintf(stderr,
            RED "\n  Make sure the adapter is running FIRST:\n"
            "    ./smbus_mctp_adapter\n"
            "  Then run THIS (master) BEFORE the slave.\n" RESET);
        return 1;
    }
    printf(GREEN "  Connected — waiting for slave to send commands...\n" RESET);

    int rc = receive_loop(fd);
    close(fd);
    return (rc == 0) ? 0 : 1;
}
