/*
 * smbus_mctp_adapter.c — SMBus Slave + Master two-socket MCTP adapter
 *
 * Two separate Unix domain sockets:
 *   SLAVE  socket (/tmp/smbus_slave.sock)  — receives CCI requests from slave
 *   MASTER socket (/tmp/smbus_master.sock) — sends CCI responses to master
 *
 * Flow for each CCI transaction:
 *   1. Slave sends CciPayloadPacket REQUEST on slave socket
 *   2. Adapter reads it, re-tags with auto-sequence counter
 *   3. Adapter opens TCP connection to FM:8300, forwards the packet
 *   4. FM processes the CCI command, sends back CciPayloadPacket RESPONSE
 *   5. Adapter reads FM response, writes it to master socket
 *   6. Master receives and displays the response
 *
 * Build:
 *   gcc -O2 -Wall -o smbus_mctp_adapter smbus_mctp_adapter.c
 *
 * Usage:
 *   ./smbus_mctp_adapter [slave_sock] [master_sock] [fm_host] [fm_port] [-v]
 *   ./smbus_mctp_adapter /tmp/smbus_slave.sock /tmp/smbus_master.sock 127.0.0.1 8300
 */

#include "smbus_mctp_adapter.h"
#include "mctp_packet.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <unistd.h>
#include <fcntl.h>

#include <sys/socket.h>
#include <sys/un.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <arpa/inet.h>
#include <netdb.h>

/* ── Colours ─────────────────────────────────────────────────────────── */
#define BOLD    "\033[1m"
#define CYAN    "\033[96m"
#define GREEN   "\033[92m"
#define YELLOW  "\033[93m"
#define RED     "\033[91m"
#define RESET   "\033[0m"

/* ── Logging ─────────────────────────────────────────────────────────── */
#define LOG_INFO(fmt, ...) \
    fprintf(stdout, GREEN "[adapter] " RESET fmt "\n", ##__VA_ARGS__)
#define LOG_ERR(fmt, ...) \
    fprintf(stderr, RED "[adapter:ERR] " fmt " (errno=%d: %s)\n" RESET, \
            ##__VA_ARGS__, errno, strerror(errno))
#define LOG_DBG(a, fmt, ...) \
    do { if ((a)->verbose) \
        fprintf(stdout, CYAN "[adapter:DBG] " RESET fmt "\n", \
                ##__VA_ARGS__); } while(0)
#define LOG_TX(fmt, ...) \
    fprintf(stdout, YELLOW "  [slave →adapter] " RESET fmt "\n", ##__VA_ARGS__)
#define LOG_RX(fmt, ...) \
    fprintf(stdout, GREEN  "  [adapter→master] " RESET fmt "\n", ##__VA_ARGS__)

/* ── I/O helpers ─────────────────────────────────────────────────────── */

int read_exact(int fd, void *buf, size_t n)
{
    size_t done = 0;
    while (done < n) {
        ssize_t r = recv(fd, (char *)buf + done, n - done, MSG_WAITALL);
        if (r <= 0) return -1;
        done += (size_t)r;
    }
    return 0;
}

int write_exact(int fd, const void *buf, size_t n)
{
    size_t done = 0;
    while (done < n) {
        ssize_t w = send(fd, (const char *)buf + done, n - done, 0);
        if (w <= 0) return -1;
        done += (size_t)w;
    }
    return 0;
}

/* ── Create a Unix socket server fd ─────────────────────────────────── */
static int create_unix_server(const char *path)
{
    struct sockaddr_un addr;
    int fd;

    unlink(path);   /* remove stale socket file */

    fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) {
        LOG_ERR("socket(AF_UNIX) for %s failed", path);
        return -1;
    }

    memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    strncpy(addr.sun_path, path, sizeof(addr.sun_path) - 1);

    if (bind(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        LOG_ERR("bind(%s) failed", path);
        close(fd);
        return -1;
    }
    if (listen(fd, 2) < 0) {
        LOG_ERR("listen(%s) failed", path);
        close(fd);
        return -1;
    }
    return fd;
}

/* ── FM TCP connection ───────────────────────────────────────────────── */

int adapter_connect_fm(const char *host, uint16_t port)
{
    struct addrinfo hints, *res;
    char port_str[16];
    int fd, opt = 1;

    memset(&hints, 0, sizeof(hints));
    hints.ai_family   = AF_INET;
    hints.ai_socktype = SOCK_STREAM;
    snprintf(port_str, sizeof(port_str), "%u", (unsigned)port);

    if (getaddrinfo(host, port_str, &hints, &res) != 0) {
        LOG_ERR("getaddrinfo(%s:%u) failed", host, port);
        return -1;
    }

    fd = socket(res->ai_family, res->ai_socktype, res->ai_protocol);
    if (fd < 0) {
        LOG_ERR("socket() for FM failed");
        freeaddrinfo(res);
        return -1;
    }

    setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &opt, sizeof(opt));

    if (connect(fd, res->ai_addr, res->ai_addrlen) < 0) {
        LOG_ERR("connect to FM %s:%u failed", host, port);
        close(fd);
        freeaddrinfo(res);
        return -1;
    }
    freeaddrinfo(res);
    return fd;
}

/* ── Core relay loop ─────────────────────────────────────────────────── */

/*
 * Relay CCI traffic between slave_fd and master_fd through FM TCP.
 *
 * Runs until:
 *   - Slave disconnects (EOF on slave_fd)
 *   - FM error
 *   - Master disconnects mid-write
 *
 * Returns number of transactions completed (≥0) or -1 on hard error.
 */
static int relay_loop(smbus_adapter_t *a, int slave_fd, int master_fd)
{
    int    tag   = 0;
    int    count = 0;
    int    fm_fd = -1;
    mctp_pkt_t req, resp;

    /* Open persistent TCP connection to FM for this session */
    fm_fd = adapter_connect_fm(a->fm_host, a->fm_port);
    if (fm_fd < 0) {
        LOG_ERR("Cannot reach FM %s:%u", a->fm_host, a->fm_port);
        return -1;
    }
    LOG_INFO("FM TCP connected: %s:%u", a->fm_host, a->fm_port);

    while (1) {
        /* ── Read SystemHeader (2 bytes) from slave ── */
        uint8_t sys_hdr[2];
        if (read_exact(slave_fd, sys_hdr, 2) != 0) {
            LOG_INFO("Slave disconnected — relay done (%d transactions)", count);
            break;
        }

        uint16_t total_len = mctp_get_payload_length(sys_hdr);
        if (total_len < MCTP_HEADER_SIZE || total_len > MCTP_MAX_PACKET) {
            LOG_ERR("Bad packet length %u from slave", total_len);
            break;
        }

        /* ── Read rest of slave packet ── */
        memcpy(req.data, sys_hdr, 2);
        if (read_exact(slave_fd, req.data + 2, total_len - 2) != 0) {
            LOG_ERR("Slave disconnected mid-packet");
            break;
        }
        mctp_parse(&req, total_len);

        uint16_t opcode   = mctp_get_opcode(req.data);
        uint8_t  orig_tag = mctp_get_msg_tag(req.data);
        uint32_t plen     = req.payload_len;

        LOG_TX("opcode=0x%04X (%s) orig_tag=%u → new_tag=%d payload=%u B",
               opcode, mctp_opcode_name(opcode), orig_tag, tag, plen);

        /* ── Rebuild with auto-sequenced tag and forward to FM ── */
        mctp_pkt_t fwd;
        mctp_build_request(&fwd, opcode, (uint8_t)(tag & 0xFF),
                           mctp_payload(&req), plen, req.data[2]);

        if (write_exact(fm_fd, fwd.data, fwd.total_len) != 0) {
            LOG_ERR("Send to FM failed");
            break;
        }
        LOG_DBG(a, "→ FM  opcode=0x%04X tag=%d bytes=%u", opcode, tag, fwd.total_len);

        /* ── Read FM response ── */
        if (read_exact(fm_fd, sys_hdr, 2) != 0) {
            LOG_ERR("FM disconnected before response");
            break;
        }
        uint16_t resp_len = mctp_get_payload_length(sys_hdr);
        if (resp_len < MCTP_HEADER_SIZE || resp_len > MCTP_MAX_PACKET) {
            LOG_ERR("FM bad response length %u", resp_len);
            break;
        }
        memcpy(resp.data, sys_hdr, 2);
        if (read_exact(fm_fd, resp.data + 2, resp_len - 2) != 0) {
            LOG_ERR("FM disconnected mid-response");
            break;
        }
        mctp_parse(&resp, resp_len);

        uint16_t rc = mctp_get_return_code(resp.data);
        uint8_t  bg = mctp_get_background(resp.data);

        LOG_RX("opcode=0x%04X tag=%d rc=%s(%u) bg=%u payload=%u B",
               opcode, tag, mctp_rc_name(rc), rc, bg, resp.payload_len);

        /* ── Forward response to master ── */
        if (write_exact(master_fd, resp.data, resp_len) != 0) {
            LOG_ERR("Send to master failed — master disconnected?");
            break;
        }

        tag = (tag + 1) & 0xFF;
        count++;
    }

    close(fm_fd);
    return count;
}

/* ── Adapter init / run / cleanup ─────────────────────────────────────── */

adapter_err_t adapter_init(smbus_adapter_t *a,
                            const char *slave_sock,
                            const char *master_sock,
                            const char *fm_host,
                            uint16_t    fm_port,
                            int         verbose)
{
    memset(a, 0, sizeof(*a));
    a->slave_server_fd  = -1;
    a->master_server_fd = -1;
    a->verbose          = verbose;
    a->fm_port          = fm_port ? fm_port : ADAPTER_DEFAULT_FM_PORT;

    strncpy(a->slave_sock_path,
            slave_sock  ? slave_sock  : ADAPTER_SLAVE_SOCK_PATH,
            sizeof(a->slave_sock_path)  - 1);
    strncpy(a->master_sock_path,
            master_sock ? master_sock : ADAPTER_MASTER_SOCK_PATH,
            sizeof(a->master_sock_path) - 1);
    strncpy(a->fm_host,
            fm_host ? fm_host : ADAPTER_DEFAULT_FM_HOST,
            sizeof(a->fm_host) - 1);
    return ADAPTER_OK;
}

adapter_err_t adapter_run(smbus_adapter_t *a)
{
    /* Create both Unix socket servers */
    a->slave_server_fd = create_unix_server(a->slave_sock_path);
    if (a->slave_server_fd < 0) return ADAPTER_ERR_SOCKET;

    a->master_server_fd = create_unix_server(a->master_sock_path);
    if (a->master_server_fd < 0) {
        close(a->slave_server_fd);
        return ADAPTER_ERR_SOCKET;
    }

    printf(BOLD CYAN
           "\n╔══════════════════════════════════════════════════╗\n"
           "║  SMBus-MCTP Adapter  (two-socket mode)          ║\n"
           "╚══════════════════════════════════════════════════╝\n"
           RESET);
    LOG_INFO("Slave  socket : %s  (SMBus Slave connects here)", a->slave_sock_path);
    LOG_INFO("Master socket : %s  (SMBus Master connects here)", a->master_sock_path);
    LOG_INFO("FM target     : %s:%u", a->fm_host, a->fm_port);
    printf("\n");

    while (1) {
        /*
         * Accept order:
         *   1. Wait for MASTER to connect first (so it is ready to receive
         *      responses before the slave starts sending)
         *   2. Then wait for SLAVE to connect
         *
         * This prevents the race where the slave sends before the master
         * is ready.
         */
        LOG_INFO("Waiting for SMBus Master to connect on %s ...",
                 a->master_sock_path);
        int master_fd = accept(a->master_server_fd, NULL, NULL);
        if (master_fd < 0) {
            if (errno == EINTR) continue;
            LOG_ERR("accept(master) failed");
            return ADAPTER_ERR_ACCEPT;
        }
        LOG_INFO(BOLD "SMBus Master connected." RESET);

        LOG_INFO("Waiting for SMBus Slave to connect on %s ...",
                 a->slave_sock_path);
        int slave_fd = accept(a->slave_server_fd, NULL, NULL);
        if (slave_fd < 0) {
            if (errno == EINTR) { close(master_fd); continue; }
            LOG_ERR("accept(slave) failed");
            close(master_fd);
            return ADAPTER_ERR_ACCEPT;
        }
        LOG_INFO(BOLD "SMBus Slave connected. Starting relay..." RESET);

        int n = relay_loop(a, slave_fd, master_fd);
        close(slave_fd);
        close(master_fd);

        LOG_INFO("Session ended (%d CCI transactions).", n);
    }

    return ADAPTER_OK;
}

void adapter_cleanup(smbus_adapter_t *a)
{
    if (a->slave_server_fd  >= 0) { close(a->slave_server_fd);  a->slave_server_fd  = -1; }
    if (a->master_server_fd >= 0) { close(a->master_server_fd); a->master_server_fd = -1; }
    unlink(a->slave_sock_path);
    unlink(a->master_sock_path);
}

/* ── main ─────────────────────────────────────────────────────────────── */

int main(int argc, char *argv[])
{
    smbus_adapter_t adapter;
    const char *slave_sock  = (argc > 1) ? argv[1] : NULL;
    const char *master_sock = (argc > 2) ? argv[2] : NULL;
    const char *fm_host     = (argc > 3) ? argv[3] : NULL;
    uint16_t    fm_port     = (argc > 4) ? (uint16_t)atoi(argv[4]) : 0;
    int         verbose     = 0;

    for (int i = 1; i < argc; i++)
        if (strcmp(argv[i], "-v") == 0) verbose = 1;

    adapter_init(&adapter, slave_sock, master_sock, fm_host, fm_port, verbose);
    adapter_err_t rc = adapter_run(&adapter);
    adapter_cleanup(&adapter);

    return (rc == ADAPTER_OK) ? 0 : 1;
}
