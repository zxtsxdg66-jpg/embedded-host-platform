/**
 ****************************************************************************************************
 * @file        crc32.c
 * @brief       CRC-32/ISO-HDLC 实现，逐位计算（不用查表，代码量小、正确性易核对）。
 ****************************************************************************************************
 */
#include "crc32.h"

uint32_t crc32_calculate(const uint8_t *data, uint32_t length)
{
    uint32_t crc = 0xFFFFFFFFu;
    uint32_t i;
    uint8_t bit;

    for (i = 0; i < length; i++)
    {
        crc ^= data[i];
        for (bit = 0; bit < 8; bit++)
        {
            if (crc & 1u)
            {
                crc = (crc >> 1) ^ 0xEDB88320u;
            }
            else
            {
                crc >>= 1;
            }
        }
    }

    return crc ^ 0xFFFFFFFFu;
}
