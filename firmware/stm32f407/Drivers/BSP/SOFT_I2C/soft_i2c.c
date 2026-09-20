/**
 ****************************************************************************************************
 * @file        soft_i2c.c
 ****************************************************************************************************
 */
#include "soft_i2c.h"
#include "./SYSTEM/sys/sys.h"
#include "./SYSTEM/delay/delay.h"

#define SOFT_I2C_GPIO_PORT       GPIOE
#define SOFT_I2C_SCL_PIN         GPIO_PIN_1
#define SOFT_I2C_SDA_PIN         GPIO_PIN_0

/* 时序半周期延时（微秒）：约 4us 对应标准 I2C 模式（100kHz 附近），
 * AHT20 说明书 5.1 节标准模式 SCL 最高 100kHz，取值留有余量 */
#define SOFT_I2C_DELAY_US        4u

#define SOFT_I2C_SCL(x)    HAL_GPIO_WritePin(SOFT_I2C_GPIO_PORT, SOFT_I2C_SCL_PIN, (x) ? GPIO_PIN_SET : GPIO_PIN_RESET)
#define SOFT_I2C_SDA(x)    HAL_GPIO_WritePin(SOFT_I2C_GPIO_PORT, SOFT_I2C_SDA_PIN, (x) ? GPIO_PIN_SET : GPIO_PIN_RESET)
#define SOFT_I2C_SDA_READ() HAL_GPIO_ReadPin(SOFT_I2C_GPIO_PORT, SOFT_I2C_SDA_PIN)

void soft_i2c_init(void)
{
    GPIO_InitTypeDef gpio_init = {0};

    __HAL_RCC_GPIOE_CLK_ENABLE();

    /* 开漏输出 + 上拉：输出'1'时只是释放总线（由上拉电阻拉高，或允许从机拉低应答），
     * 因此读取 SDA 电平无需切换引脚方向，简化了 ACK 检测与读字节的实现 */
    gpio_init.Mode = GPIO_MODE_OUTPUT_OD;
    gpio_init.Pull = GPIO_PULLUP;
    gpio_init.Speed = GPIO_SPEED_FREQ_HIGH;

    gpio_init.Pin = SOFT_I2C_SCL_PIN;
    HAL_GPIO_Init(SOFT_I2C_GPIO_PORT, &gpio_init);

    gpio_init.Pin = SOFT_I2C_SDA_PIN;
    HAL_GPIO_Init(SOFT_I2C_GPIO_PORT, &gpio_init);

    SOFT_I2C_SCL(1);
    SOFT_I2C_SDA(1);
}

void soft_i2c_start(void)
{
    SOFT_I2C_SDA(1);
    SOFT_I2C_SCL(1);
    delay_us(SOFT_I2C_DELAY_US);
    SOFT_I2C_SDA(0);   /* SCL 高电平期间 SDA 由高变低 = START 条件 */
    delay_us(SOFT_I2C_DELAY_US);
    SOFT_I2C_SCL(0);
}

void soft_i2c_stop(void)
{
    SOFT_I2C_SDA(0);
    SOFT_I2C_SCL(1);
    delay_us(SOFT_I2C_DELAY_US);
    SOFT_I2C_SDA(1);   /* SCL 高电平期间 SDA 由低变高 = STOP 条件 */
    delay_us(SOFT_I2C_DELAY_US);
}

/**
 * @brief   等待从机 ACK（SDA 被从机拉低），带超时保护，避免总线异常时永久卡死
 * @retval  1=收到 ACK，0=超时未收到（NACK 或总线故障）
 */
static uint8_t soft_i2c_wait_ack(void)
{
    uint16_t timeout = 200u;

    SOFT_I2C_SDA(1);   /* 释放总线，让从机可以拉低 */
    delay_us(SOFT_I2C_DELAY_US);
    SOFT_I2C_SCL(1);
    delay_us(SOFT_I2C_DELAY_US);

    while (SOFT_I2C_SDA_READ() == GPIO_PIN_SET)
    {
        if (--timeout == 0u)
        {
            SOFT_I2C_SCL(0);
            return 0u;
        }
    }

    SOFT_I2C_SCL(0);
    return 1u;
}

uint8_t soft_i2c_send_byte(uint8_t data)
{
    uint8_t i;

    for (i = 0; i < 8u; i++)
    {
        SOFT_I2C_SDA((data & 0x80u) != 0u);
        data <<= 1;
        delay_us(SOFT_I2C_DELAY_US);
        SOFT_I2C_SCL(1);
        delay_us(SOFT_I2C_DELAY_US);
        SOFT_I2C_SCL(0);
        delay_us(SOFT_I2C_DELAY_US);
    }

    return soft_i2c_wait_ack();
}

uint8_t soft_i2c_read_byte(uint8_t ack)
{
    uint8_t i;
    uint8_t value = 0;

    SOFT_I2C_SDA(1);   /* 读之前先释放总线 */

    for (i = 0; i < 8u; i++)
    {
        value <<= 1;
        SOFT_I2C_SCL(1);
        delay_us(SOFT_I2C_DELAY_US);
        if (SOFT_I2C_SDA_READ() == GPIO_PIN_SET)
        {
            value |= 0x01u;
        }
        SOFT_I2C_SCL(0);
        delay_us(SOFT_I2C_DELAY_US);
    }

    /* 主机在读完每字节后回复 ACK（继续读）或 NACK（结束读取） */
    SOFT_I2C_SDA(ack ? 0u : 1u);
    delay_us(SOFT_I2C_DELAY_US);
    SOFT_I2C_SCL(1);
    delay_us(SOFT_I2C_DELAY_US);
    SOFT_I2C_SCL(0);
    SOFT_I2C_SDA(1);   /* 释放总线 */

    return value;
}
