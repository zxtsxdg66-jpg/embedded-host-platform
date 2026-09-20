/**
 ****************************************************************************************************
 * @file        modbus_crc16.c
 ****************************************************************************************************
 */
#include "modbus_crc16.h"

uint16_t modbus_crc16_calculate(const uint8_t *data, uint16_t length)
{
    uint16_t crc = 0xFFFFu;
    uint16_t i;
    uint8_t bit;

    for (i = 0; i < length; i++)
    {
        crc ^= (uint16_t)data[i];
        for (bit = 0; bit < 8; bit++)
        {
            if (crc & 1u)
            {
                crc = (uint16_t)((crc >> 1) ^ 0xA001u);
            }
            else
            {
                crc >>= 1;
            }
        }
    }

    return crc;
}
