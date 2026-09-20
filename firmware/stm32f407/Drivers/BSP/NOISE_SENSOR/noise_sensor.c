/**
 ****************************************************************************************************
 * @file        noise_sensor.c
 ****************************************************************************************************
 */
#include "noise_sensor.h"
#include "./BSP/NOISE_USART/noise_usart.h"
#include "./BSP/MODBUS/modbus_crc16.h"
#include "./SYSTEM/sys/sys.h"

#define MODBUS_FUNC_READ_HOLDING_REGISTERS   0x03u

static uint8_t s_slave_address = NOISE_SENSOR_DEFAULT_ADDRESS;
static uint32_t s_request_sent_tick = 0;
static uint8_t s_request_pending = 0;
static uint32_t s_error_count = 0;

void noise_sensor_init(uint32_t baudrate, uint8_t slave_address)
{
    s_slave_address = slave_address;
    s_request_pending = 0u;
    s_error_count = 0u;
    noise_usart_init(baudrate);
}

void noise_sensor_start_request(void)
{
    /* 请求帧：从机地址 + 03H + 寄存器起始地址(0x0000) + 寄存器数量(1) + CRC16 */
    uint8_t request[8];

    request[0] = s_slave_address;
    request[1] = MODBUS_FUNC_READ_HOLDING_REGISTERS;
    request[2] = 0x00u;   /* 寄存器起始地址 高字节 */
    request[3] = 0x00u;   /* 寄存器起始地址 低字节，协议地址 0x0000 */
    request[4] = 0x00u;   /* 寄存器数量 高字节 */
    request[5] = 0x01u;   /* 寄存器数量 低字节，读 1 个寄存器 */

    {
        uint16_t crc = modbus_crc16_calculate(request, 6u);
        request[6] = (uint8_t)(crc & 0xFFu);          /* CRC 低字节在前 */
        request[7] = (uint8_t)((crc >> 8) & 0xFFu);   /* CRC 高字节在后 */
    }

    noise_usart_reset_rx();
    noise_usart_send(request, sizeof(request));

    s_request_sent_tick = HAL_GetTick();
    s_request_pending = 1u;
}

noise_sensor_status_t noise_sensor_poll(float *out_db)
{
    if (!s_request_pending)
    {
        return NOISE_SENSOR_PENDING;   /* 尚未发起过请求 */
    }

    if (noise_usart_frame_ready())
    {
        uint16_t len;
        const uint8_t *frame = noise_usart_take_frame(&len);

        s_request_pending = 0u;

        /* 期望的应答长度：地址(1)+功能码(1)+字节数(1)+数据(2)+CRC(2) = 7 字节 */
        if (len != 7u)
        {
            s_error_count++;
            return NOISE_SENSOR_ERR_FORMAT;
        }

        if (frame[0] != s_slave_address || frame[1] != MODBUS_FUNC_READ_HOLDING_REGISTERS || frame[2] != 0x02u)
        {
            s_error_count++;
            return NOISE_SENSOR_ERR_FORMAT;
        }

        {
            uint16_t crc_expected = (uint16_t)frame[5] | ((uint16_t)frame[6] << 8);   /* 低字节在前 */
            uint16_t crc_actual = modbus_crc16_calculate(frame, 5u);

            if (crc_actual != crc_expected)
            {
                s_error_count++;
                return NOISE_SENSOR_ERR_CRC;
            }
        }

        {
            /* 数据高字节在前、低字节在后（与 PC↔STM32 协议的大端序无关，这是
             * Modbus 寄存器数据本身的字节序约定），每单位 0.1dB */
            uint16_t raw = ((uint16_t)frame[3] << 8) | (uint16_t)frame[4];
            *out_db = (float)raw * 0.1f;
        }

        return NOISE_SENSOR_OK;
    }

    if ((HAL_GetTick() - s_request_sent_tick) > NOISE_SENSOR_TIMEOUT_MS)
    {
        s_request_pending = 0u;
        noise_usart_reset_rx();
        s_error_count++;
        return NOISE_SENSOR_ERR_TIMEOUT;
    }

    return NOISE_SENSOR_PENDING;
}

uint32_t noise_sensor_get_error_count(void)
{
    return s_error_count;
}
