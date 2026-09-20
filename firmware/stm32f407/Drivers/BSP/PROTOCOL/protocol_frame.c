/**
 ****************************************************************************************************
 * @file        protocol_frame.c
 ****************************************************************************************************
 */
#include "protocol_frame.h"
#include "crc32.h"
#include <string.h>

uint16_t protocol_encode(uint8_t device_id, uint8_t command_type,
                          const uint8_t *payload, uint16_t payload_len,
                          uint8_t *out, uint16_t out_capacity)
{
    uint16_t total_len = PROTOCOL_OVERHEAD_SIZE + payload_len;
    uint16_t offset;
    uint32_t crc;

    if (out_capacity < total_len)
    {
        return 0;
    }

    offset = 0;
    out[offset++] = PROTOCOL_HEADER_BYTE0;
    out[offset++] = PROTOCOL_HEADER_BYTE1;
    out[offset++] = device_id;
    out[offset++] = command_type;
    out[offset++] = (uint8_t)(payload_len >> 8);   /* 数据长度，大端序，高字节在前 */
    out[offset++] = (uint8_t)(payload_len & 0xFFu);

    if (payload_len > 0u && payload != 0)
    {
        memcpy(&out[offset], payload, payload_len);
        offset += payload_len;
    }

    /* CRC 覆盖 设备ID+命令类型+长度+Payload，即帧头之后的全部内容 */
    crc = crc32_calculate(&out[PROTOCOL_HEADER_SIZE], PROTOCOL_PREFIX_SIZE + payload_len);
    out[offset++] = (uint8_t)(crc >> 24);
    out[offset++] = (uint8_t)(crc >> 16);
    out[offset++] = (uint8_t)(crc >> 8);
    out[offset++] = (uint8_t)(crc & 0xFFu);

    return offset;
}

protocol_status_t protocol_decode(const uint8_t *frame, uint16_t frame_len,
                                   uint8_t *device_id, uint8_t *command_type,
                                   const uint8_t **payload, uint16_t *payload_len)
{
    uint16_t declared_len;
    uint32_t crc_expected;
    uint32_t crc_actual;
    uint16_t crc_offset;

    if (frame_len < PROTOCOL_OVERHEAD_SIZE)
    {
        return PROTOCOL_ERR_LENGTH;
    }

    if (frame[0] != PROTOCOL_HEADER_BYTE0 || frame[1] != PROTOCOL_HEADER_BYTE1)
    {
        return PROTOCOL_ERR_SYNC;
    }

    declared_len = ((uint16_t)frame[4] << 8) | (uint16_t)frame[5];

    if ((uint16_t)(PROTOCOL_OVERHEAD_SIZE + declared_len) != frame_len)
    {
        return PROTOCOL_ERR_LENGTH;
    }

    crc_offset = PROTOCOL_HEADER_SIZE + PROTOCOL_PREFIX_SIZE + declared_len;
    crc_expected = ((uint32_t)frame[crc_offset] << 24)
                 | ((uint32_t)frame[crc_offset + 1] << 16)
                 | ((uint32_t)frame[crc_offset + 2] << 8)
                 | (uint32_t)frame[crc_offset + 3];

    crc_actual = crc32_calculate(&frame[PROTOCOL_HEADER_SIZE], PROTOCOL_PREFIX_SIZE + declared_len);

    if (crc_actual != crc_expected)
    {
        return PROTOCOL_ERR_CHECKSUM;
    }

    *device_id = frame[2];
    *command_type = frame[3];
    *payload = &frame[PROTOCOL_HEADER_SIZE + PROTOCOL_PREFIX_SIZE];
    *payload_len = declared_len;

    return PROTOCOL_OK;
}

uint8_t protocol_payload_get_uint(const uint8_t *payload, uint16_t payload_len,
                                   const char *key, uint32_t *out_value)
{
    uint16_t key_len = 0u;
    uint16_t i;

    if ((payload == 0) || (key == 0) || (out_value == 0))
    {
        return 0u;
    }

    while (key[key_len] != '\0')
    {
        key_len++;
    }

    if ((key_len == 0u) || (payload_len < (uint16_t)(key_len + 2u)))
    {
        return 0u;
    }

    /* 找 "key" —— 连同两侧的引号一起匹配，避免把 "bitsX" 当成 "bits" */
    for (i = 0u; (uint16_t)(i + key_len + 2u) <= payload_len; i++)
    {
        uint16_t k;
        uint8_t matched = 1u;

        if (payload[i] != (uint8_t)'"')
        {
            continue;
        }

        for (k = 0u; k < key_len; k++)
        {
            if (payload[i + 1u + k] != (uint8_t)key[k])
            {
                matched = 0u;
                break;
            }
        }

        if ((matched == 0u) || (payload[i + 1u + key_len] != (uint8_t)'"'))
        {
            continue;
        }

        {
            uint16_t pos = (uint16_t)(i + key_len + 2u);
            uint32_t value = 0u;
            uint8_t digits = 0u;

            /* 跳过冒号与空白 */
            while ((pos < payload_len)
                   && ((payload[pos] == (uint8_t)':') || (payload[pos] == (uint8_t)' ')))
            {
                pos++;
            }

            while ((pos < payload_len)
                   && (payload[pos] >= (uint8_t)'0') && (payload[pos] <= (uint8_t)'9'))
            {
                value = (value * 10u) + (uint32_t)(payload[pos] - (uint8_t)'0');
                pos++;
                digits++;
            }

            if (digits == 0u)
            {
                return 0u;   /* 键找到了但值不是十进制整数 */
            }

            *out_value = value;
            return 1u;
        }
    }

    return 0u;
}
