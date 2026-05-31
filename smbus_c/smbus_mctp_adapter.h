/*
 * smbus_mctp_adapter.h — SMBus Slave + Master two-socket MCTP adapter
 *
 * Architecture:
 *
 *   smbus_slave  ──► /tmp/smbus_slave.sock ──► [adapter] ──► TCP:8300 ──► FM
 *   smbus_master ◄── /tmp/smbus_master.sock ◄──[adapter] ◄── TCP:8300 ◄── FM
 *
 * The adapter operates two Unix domain socket servers:
 *   1. SLAVE  socket  — accepts exactly ONE slave connection
 *              reads CCI request packets from the slave
 *   2. MASTER socket  — accepts exactly ONE master connection
 *              writes CCI response packets to the master
 *
 * For every CCI request received from the slave:
 *   - Tag is auto-sequenced (0-255 cyclic)
 *   - Packet is forwarded to FM via TCP
 *   - Response is received from FM and written to the master socket
 *
 * The slave and master MAY be separate processes or the same process.
 */

#ifndef SMBUS_MCTP_ADAPTER_H
#define SMBUS_MCTP_ADAPTER_H

#include <stdint.h>
#include <stddef.h>

/* ── Default paths and ports ─────────────────────────────────────────── */
#define ADAPTER_SLAVE_SOCK_PATH     "/tmp/smbus_slave.sock"
#define ADAPTER_MASTER_SOCK_PATH    "/tmp/smbus_master.sock"
#define ADAPTER_DEFAULT_FM_HOST     "127.0.0.1"
#define ADAPTER_DEFAULT_FM_PORT     8300

#define ADAPTER_RECV_BUF_SIZE       512

/* ── Error codes ─────────────────────────────────────────────────────── */
typedef enum {
    ADAPTER_OK               =  0,
    ADAPTER_ERR_SOCKET       = -1,
    ADAPTER_ERR_BIND         = -2,
    ADAPTER_ERR_LISTEN       = -3,
    ADAPTER_ERR_ACCEPT       = -4,
    ADAPTER_ERR_CONNECT_FM   = -5,
    ADAPTER_ERR_SEND         = -6,
    ADAPTER_ERR_RECV         = -7,
    ADAPTER_ERR_PARSE        = -8,
    ADAPTER_ERR_BUFFER_FULL  = -9,
} adapter_err_t;

/* ── Adapter context ─────────────────────────────────────────────────── */
typedef struct {
    /* Two Unix socket servers: one for slave, one for master */
    int         slave_server_fd;
    int         master_server_fd;

    char        slave_sock_path[256];
    char        master_sock_path[256];
    char        fm_host[128];
    uint16_t    fm_port;
    int         verbose;
} smbus_adapter_t;

/* ── Public API ──────────────────────────────────────────────────────── */

/*
 * Initialize the adapter.
 * Pass NULL for any path/host to use the defaults.
 */
adapter_err_t adapter_init(smbus_adapter_t *a,
                            const char *slave_sock_path,
                            const char *master_sock_path,
                            const char *fm_host,
                            uint16_t    fm_port,
                            int         verbose);

/*
 * Run the adapter event loop (blocking).
 * Waits for BOTH slave and master to connect, then relays traffic.
 */
adapter_err_t adapter_run(smbus_adapter_t *a);

/* Clean up all sockets and socket files. */
void adapter_cleanup(smbus_adapter_t *a);

/* ── Internal helpers (also used by tests) ──────────────────────────── */
int adapter_connect_fm(const char *host, uint16_t port);
int read_exact(int fd, void *buf, size_t n);
int write_exact(int fd, const void *buf, size_t n);

#endif /* SMBUS_MCTP_ADAPTER_H */
