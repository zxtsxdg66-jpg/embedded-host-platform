/**
 ****************************************************************************************************
 * @file        aht20.c
 * @brief       字节级通信序列完整复刻官方驱动 atk_aht20.c（write_nbytes/read_nbytes/
 *              init/check 四个函数的行为一一对应），仅把底层 I2C 实现从官方的
 *              myiic.c 换成本项目自己的 soft_i2c.c（引脚不同：PE0/PE1 而非官方
 *              Demo 使用的 PA3/PA2），并新增 CRC8 校验（见 aht20.h 顶部说明）。
 ****************************************************************************************************
 */
#include "aht20.h"
#include "./BSP/SOFT_I2C/soft_i2c.h"
#include "./SYSTEM/delay/delay.h"

#define AHT20_IIC_ADDR      0x70u
#define AHT20_CMD_INIT      0xBEu
#define AHT20_CMD_MEASURE   0xACu

/**
 * @brief   写 N 字节到 AHT20（地址 + reg_addr(命令字) + data[0..len-1]），
 *          与官方 atk_aht20_write_nbytes() 行为一致
 * @retval  0=成功，1=失败（任一步骤未收到 ACK）
 */
static uint8_t aht20_write_nbytes(uint8_t reg_addr, const uint8_t *data, uint8_t len)
{
    uint8_t i;

    soft_i2c_start();

    if (!soft_i2c_send_byte(AHT20_IIC_ADDR | 0x00u))
    {
        soft_i2c_stop();
        return 1u;
    }

    if (!soft_i2c_send_byte(reg_addr))
    {
        soft_i2c_stop();
        return 1u;
    }

    for (i = 0; i < len; i++)
    {
        if (!soft_i2c_send_byte(data[i]))
        {
            soft_i2c_stop();
            return 1u;
        }
    }

    soft_i2c_stop();
    return 0u;
}

/**
 * @brief   从 AHT20 读 N 字节（地址 + data[0..len-1]，最后一字节主机回 NACK），
 *          与官方 atk_aht20_read_nbytes() 行为一致
 * @retval  0=成功，1=失败（地址阶段未收到 ACK）
 */
static uint8_t aht20_read_nbytes(uint8_t *data, uint8_t len)
{
    soft_i2c_start();

    if (!soft_i2c_send_byte(AHT20_IIC_ADDR | 0x01u))
    {
        soft_i2c_stop();
        return 1u;
    }

    while (len > 0u)
    {
        *data = soft_i2c_read_byte((len > 1u) ? 1u : 0u);
        len--;
        data++;
    }

    soft_i2c_stop();
    return 0u;
}

/**
 * @brief   CRC8，多项式 X8+X5+X4+1（0x31），初始值 0xFF，与 AHT20 说明书 5.2 节
 *          "3.CRC校验"给出的参考代码逻辑一致
 */
static uint8_t aht20_crc8(const uint8_t *data, uint8_t len)
{
    uint8_t crc = 0xFFu;
    uint8_t byte_index;
    uint8_t bit_index;

    for (byte_index = 0; byte_index < len; byte_index++)
    {
        crc ^= data[byte_index];
        for (bit_index = 8; bit_index > 0u; bit_index--)
        {
            if (crc & 0x80u)
            {
                crc = (uint8_t)((crc << 1) ^ 0x31u);
            }
            else
            {
                crc = (uint8_t)(crc << 1);
            }
        }
    }

    return crc;
}

aht20_status_t aht20_init(void)
{
    uint8_t init_params[2] = {0x08u, 0x00u};
    uint8_t status_byte;

    soft_i2c_init();
    delay_ms(40u);   /* 等硬件稳定，与官方驱动一致 */

    if (aht20_write_nbytes(AHT20_CMD_INIT, init_params, 2u) != 0u)
    {
        return AHT20_ERR_NACK;
    }

    delay_ms(500u);   /* 等硬件稳定，与官方驱动一致 */

    if (aht20_read_nbytes(&status_byte, 1u) != 0u)
    {
        return AHT20_ERR_NACK;
    }

    /* Bit[3]=校准计算使能，1 表示传感器状态正常（与官方 atk_aht20_check() 判据一致），
     * 不满足则视为初始化异常；本驱动用 NACK 错误码统一表达"传感器未就绪"，
     * 不为这种情况单独新增错误码，保持接口简洁 */
    if ((status_byte & 0x08u) != 0x08u)
    {
        return AHT20_ERR_NACK;
    }

    return AHT20_OK;
}

aht20_status_t aht20_read(float *temperature, float *humidity)
{
    uint8_t measure_params[2] = {0x33u, 0x00u};
    uint8_t raw_data[7];
    uint32_t humi_data;
    uint32_t temp_data;

    if (aht20_write_nbytes(AHT20_CMD_MEASURE, measure_params, 2u) != 0u)
    {
        return AHT20_ERR_NACK;
    }

    delay_ms(80u);   /* 等测量完成，与 AHT20 说明书 5.2 节一致 */

    if (aht20_read_nbytes(raw_data, 7u) != 0u)
    {
        return AHT20_ERR_NACK;
    }

    if (aht20_crc8(raw_data, 6u) != raw_data[6])
    {
        return AHT20_ERR_CRC;
    }

    /* 状态字 Bit[7]=1 表示传感器忙（仍在测量中），此时读到的是上一次的数据，
     * 与官方驱动的判断条件一致，视为无效读数上报为 NACK 错误（本次读数作废，
     * 调用方应等待下一个采样周期重试，而不是使用这份陈旧数据） */
    if ((raw_data[0] & 0x80u) != 0x00u)
    {
        return AHT20_ERR_NACK;
    }

    humi_data = 0;
    humi_data = (humi_data | raw_data[1]) << 8;
    humi_data = (humi_data | raw_data[2]) << 8;
    humi_data = (humi_data | raw_data[3]);
    humi_data = humi_data >> 4;
    *humidity = (float)humi_data * 100.0f / 1024.0f / 1024.0f;

    temp_data = 0;
    temp_data = (temp_data | raw_data[3]) << 8;
    temp_data = (temp_data | raw_data[4]) << 8;
    temp_data = (temp_data | raw_data[5]);
    temp_data = temp_data & 0xFFFFFu;
    *temperature = (float)temp_data * 200.0f / 1024.0f / 1024.0f - 50.0f;

    return AHT20_OK;
}
