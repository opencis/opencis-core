/*
 * mctp_packet.h  —  Exact CciPayloadPacket wire format for opencis-core
 *
 * Derived from fields.py:
 *
 *   SystemHeader   (2 bytes):
 *     bits  0- 3 : payload_type   (CCI_MCTP = 4)
 *     bits  4-15 : payload_length (total bytes including this header)
 *
 *   CciHeader      (2 bytes):
 *     bits  0- 7 : port_index
 *     bits  8-15 : msg_class      (REQ=1, RSP=2)
 *
 *   CciMessageHeader (12 bytes):
 *     bits  0- 3 : message_category   (REQUEST=0, RESPONSE=1)
 *     bits  4- 7 : reserved0
 *     bits  8-15 : message_tag
 *     bits 16-23 : reserved1
 *     bits 24-39 : command_opcode     (e.g. 0x5700)
 *     bits 40-55 : message_payload_length_low
 *     bits 56-60 : message_payload_length_high
 *     bits 61-62 : reserved2
 *     bit  63    : background_operation
 *     bits 64-79 : return_code
 *     bits 80-95 : vendor_specific_extended_status
 *
 * Total header = 2 + 2 + 12 = 16 bytes
 * Payload follows immediately after the 16-byte header.
 *
 * All multi-byte fields are LITTLE-ENDIAN (as read by Python struct).
 */

#ifndef MCTP_PACKET_H
#define MCTP_PACKET_H

#include <stdint.h>
#include <stddef.h>
#include <string.h>

/* ── Constants ─────────────────────────────────────────────────────────── */

#define MCTP_PAYLOAD_TYPE_CCI       4

#define MCTP_MSG_CLASS_REQ          1
#define MCTP_MSG_CLASS_RSP          2

#define MCTP_MSG_CATEGORY_REQUEST   0
#define MCTP_MSG_CATEGORY_RESPONSE  1

/* PBR CCI Opcodes */
#define OPCODE_IDENTIFY_PBR_SWITCH          0x5700
#define OPCODE_CONFIGURE_PID_ASSIGNMENT     0x5704
#define OPCODE_GET_PID_BINDING              0x5705
#define OPCODE_CONFIGURE_PID_BINDING        0x5706
#define OPCODE_GET_DRT                      0x5708
#define OPCODE_SET_DRT                      0x5709

/* GAE CCI Opcodes */
#define OPCODE_IDENTIFY_GAE                 0x5800
#define OPCODE_GET_PID_ACCESS_VECTORS       0x5801
#define OPCODE_PROXY_GFD_MGMT               0x5802
#define OPCODE_GET_PROXY_THREAD_STATUS      0x5803
#define OPCODE_CANCEL_PROXY_THREAD          0x5804

/* CCI return codes */
#define CCI_RC_SUCCESS                      0x0000
#define CCI_RC_BACKGROUND_COMMAND_STARTED   0x0001
#define CCI_RC_INVALID_INPUT                0x0002
#define CCI_RC_UNSUPPORTED                  0x0003
#define CCI_RC_INTERNAL_ERROR               0x0004

/* Packet size limits */
#define MCTP_HEADER_SIZE    16   /* SystemHeader(2) + CciHeader(2) + CciMsgHdr(12) */
#define MCTP_MAX_PAYLOAD    480
#define MCTP_MAX_PACKET     (MCTP_HEADER_SIZE + MCTP_MAX_PAYLOAD)

/* ── Raw byte-level helpers (little-endian bit-field access) ───────────── */

/*
 * SystemHeader occupies bytes 0-1 (16 bits total):
 *
 *   byte 0 bits[3:0] = payload_type  (4-bit field starting at bit 0)
 *   bytes 0-1 bits[15:4] = payload_length (12-bit field starting at bit 4)
 *
 * In memory (LE):
 *   byte[0] = (payload_type & 0x0F) | ((payload_length & 0xFF) << 4)
 *               but field starts at bit 4, width 12 so:
 *   byte[0] bits[7:4] = payload_length[3:0]
 *   byte[1] bits[7:0] = payload_length[11:4]
 *
 * Using the _read_bits/_write_bits logic from generate_packet_structs.py:
 *   payload_type   : start=0, width=4  → byte[0] & 0x0F
 *   payload_length : start=4, width=12 → bits 4..15
 *                    byte[0] >> 4 | byte[1] << 4
 */

static inline uint16_t mctp_get_payload_length(const uint8_t *pkt)
{
    /* bits 4-15: low nibble of byte[1]<<4 | high nibble of byte[0] */
    return (uint16_t)(((pkt[0] >> 4) & 0x0F) | ((uint16_t)pkt[1] << 4));
}

static inline void mctp_set_system_header(uint8_t *pkt, uint16_t payload_length)
{
    /* payload_type = CCI_MCTP = 4, bits 0-3 of byte[0] */
    pkt[0] = (MCTP_PAYLOAD_TYPE_CCI & 0x0F) | (uint8_t)((payload_length & 0x0F) << 4);
    pkt[1] = (uint8_t)((payload_length >> 4) & 0xFF);
}

/*
 * CciHeader occupies bytes 2-3:
 *   byte[2] = port_index (8 bits, bits 0-7)
 *   byte[3] = msg_class  (8 bits, bits 8-15)
 */
static inline void mctp_set_cci_header(uint8_t *pkt, uint8_t port_index, uint8_t msg_class)
{
    pkt[2] = port_index;
    pkt[3] = msg_class;
}

static inline uint8_t mctp_get_msg_class(const uint8_t *pkt)
{
    return pkt[3];
}

/*
 * CciMessageHeader occupies bytes 4-15 (12 bytes = 96 bits):
 *
 *   byte[4]       bits[3:0] = message_category  (4 bits, start=0 of msg hdr)
 *   byte[4]       bits[7:4] = reserved0
 *   byte[5]                 = message_tag        (8 bits, start=8)
 *   byte[6]                 = reserved1           (8 bits, start=16)
 *   bytes[7..8]             = command_opcode      (16 bits LE, start=24)
 *   bytes[9..10]            = payload_length_low  (16 bits LE, start=40)
 *   byte[11]      bits[4:0] = payload_length_high (5 bits, start=56)
 *   byte[11]      bits[6:5] = reserved2
 *   byte[11]      bit[7]    = background_operation
 *   bytes[12..13]           = return_code         (16 bits LE, start=64)
 *   bytes[14..15]           = vendor_status        (16 bits LE, start=80)
 */

#define MCTP_MSG_HDR_OFFSET  4   /* CciMessageHeader starts at byte 4 */

static inline uint8_t  mctp_get_msg_category(const uint8_t *pkt)
{
    return pkt[MCTP_MSG_HDR_OFFSET + 0] & 0x0F;
}
static inline uint8_t  mctp_get_msg_tag(const uint8_t *pkt)
{
    return pkt[MCTP_MSG_HDR_OFFSET + 1];
}
static inline uint16_t mctp_get_opcode(const uint8_t *pkt)
{
    return (uint16_t)pkt[MCTP_MSG_HDR_OFFSET + 3]
         | ((uint16_t)pkt[MCTP_MSG_HDR_OFFSET + 4] << 8);
}
static inline uint32_t mctp_get_payload_len(const uint8_t *pkt)
{
    uint32_t low  = (uint32_t)pkt[MCTP_MSG_HDR_OFFSET + 5]
                  | ((uint32_t)pkt[MCTP_MSG_HDR_OFFSET + 6] << 8);
    uint32_t high = (uint32_t)(pkt[MCTP_MSG_HDR_OFFSET + 7] & 0x1F);
    return low | (high << 16);
}
static inline uint8_t  mctp_get_background(const uint8_t *pkt)
{
    return (pkt[MCTP_MSG_HDR_OFFSET + 7] >> 7) & 0x01;
}
static inline uint16_t mctp_get_return_code(const uint8_t *pkt)
{
    return (uint16_t)pkt[MCTP_MSG_HDR_OFFSET + 8]
         | ((uint16_t)pkt[MCTP_MSG_HDR_OFFSET + 9] << 8);
}

static inline void mctp_set_msg_header(uint8_t *pkt,
                                       uint8_t  category,
                                       uint8_t  tag,
                                       uint16_t opcode,
                                       uint32_t payload_len,
                                       uint8_t  background,
                                       uint16_t return_code)
{
    uint8_t *m = pkt + MCTP_MSG_HDR_OFFSET;
    memset(m, 0, 12);
    m[0] = category & 0x0F;          /* message_category in bits[3:0] */
    m[1] = tag;                       /* message_tag */
    m[2] = 0;                         /* reserved1 */
    m[3] = (uint8_t)(opcode & 0xFF); /* command_opcode low */
    m[4] = (uint8_t)(opcode >> 8);   /* command_opcode high */
    m[5] = (uint8_t)(payload_len & 0xFFFF);       /* payload_length_low low */
    m[6] = (uint8_t)((payload_len & 0xFFFF) >> 8);/* payload_length_low high */
    m[7] = (uint8_t)((payload_len >> 16) & 0x1F)  /* payload_length_high */
         | (uint8_t)((background & 0x01) << 7);   /* background_operation */
    m[8]  = (uint8_t)(return_code & 0xFF);         /* return_code low */
    m[9]  = (uint8_t)(return_code >> 8);           /* return_code high */
    m[10] = 0;                                     /* vendor_status low */
    m[11] = 0;                                     /* vendor_status high */
}

/* ── High-level builder ────────────────────────────────────────────────── */

typedef struct {
    uint8_t  data[MCTP_MAX_PACKET];
    uint16_t total_len;      /* total bytes including MCTP_HEADER_SIZE */
    uint32_t payload_len;    /* bytes of CCI payload (after 16-byte header) */
} mctp_pkt_t;

/*
 * Build a CCI REQUEST packet.
 *
 * @pkt         output buffer
 * @opcode      CCI command opcode (e.g. OPCODE_IDENTIFY_PBR_SWITCH)
 * @tag         message tag (0-255)
 * @payload     CCI payload bytes (may be NULL if payload_len == 0)
 * @payload_len number of payload bytes
 * @port_index  switch port index (default 0)
 */
static inline void mctp_build_request(mctp_pkt_t *pkt,
                                      uint16_t    opcode,
                                      uint8_t     tag,
                                      const void *payload,
                                      uint32_t    payload_len,
                                      uint8_t     port_index)
{
    uint16_t total = (uint16_t)(MCTP_HEADER_SIZE + payload_len);
    memset(pkt->data, 0, MCTP_HEADER_SIZE);

    mctp_set_system_header(pkt->data, total);
    mctp_set_cci_header(pkt->data, port_index, MCTP_MSG_CLASS_REQ);
    mctp_set_msg_header(pkt->data,
                        MCTP_MSG_CATEGORY_REQUEST,
                        tag, opcode, payload_len,
                        0 /* not background */, 0 /* return_code */);

    if (payload && payload_len)
        memcpy(pkt->data + MCTP_HEADER_SIZE, payload, payload_len);

    pkt->total_len  = total;
    pkt->payload_len = payload_len;
}

/*
 * Parse a received CCI RESPONSE packet.
 *
 * @pkt         raw bytes received from the socket
 * @raw_len     number of valid bytes in pkt->data
 */
static inline void mctp_parse(mctp_pkt_t *pkt, uint16_t raw_len)
{
    pkt->total_len   = raw_len;
    pkt->payload_len = (raw_len > MCTP_HEADER_SIZE)
                       ? (raw_len - MCTP_HEADER_SIZE) : 0;
}

/* Access payload of a parsed packet */
static inline const uint8_t *mctp_payload(const mctp_pkt_t *pkt)
{
    return pkt->data + MCTP_HEADER_SIZE;
}

/* Return the const name of a known opcode (for logging) */
static inline const char *mctp_opcode_name(uint16_t opcode)
{
    switch (opcode) {
    case OPCODE_IDENTIFY_PBR_SWITCH:        return "IDENTIFY_PBR_SWITCH";
    case OPCODE_CONFIGURE_PID_ASSIGNMENT:   return "CONFIGURE_PID_ASSIGNMENT";
    case OPCODE_GET_PID_BINDING:            return "GET_PID_BINDING";
    case OPCODE_CONFIGURE_PID_BINDING:      return "CONFIGURE_PID_BINDING";
    case OPCODE_GET_DRT:                    return "GET_DRT";
    case OPCODE_SET_DRT:                    return "SET_DRT";
    case OPCODE_IDENTIFY_GAE:               return "IDENTIFY_GAE";
    case OPCODE_GET_PID_ACCESS_VECTORS:     return "GET_PID_ACCESS_VECTORS";
    case OPCODE_PROXY_GFD_MGMT:             return "PROXY_GFD_MGMT";
    case OPCODE_GET_PROXY_THREAD_STATUS:    return "GET_PROXY_THREAD_STATUS";
    case OPCODE_CANCEL_PROXY_THREAD:        return "CANCEL_PROXY_THREAD";
    default: return "UNKNOWN";
    }
}

static inline const char *mctp_rc_name(uint16_t rc)
{
    switch (rc) {
    case CCI_RC_SUCCESS:                    return "SUCCESS";
    case CCI_RC_BACKGROUND_COMMAND_STARTED: return "BACKGROUND_COMMAND_STARTED";
    case CCI_RC_INVALID_INPUT:              return "INVALID_INPUT";
    case CCI_RC_UNSUPPORTED:                return "UNSUPPORTED";
    case CCI_RC_INTERNAL_ERROR:             return "INTERNAL_ERROR";
    default: return "UNKNOWN_RC";
    }
}

#endif /* MCTP_PACKET_H */
