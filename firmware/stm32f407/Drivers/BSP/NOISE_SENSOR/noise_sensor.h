/**
 ****************************************************************************************************
 * @file        noise_sensor.h
 * @brief       噪声检测模块 HH_07.06 —— ModbusRTU 模式驱动。
 *
 * 依据《噪声检测模块(HH_07.06)应用手册V1.2》3.3 节：使用 03H 功能码（读保持寄存器）
 * 读取分贝值，协议地址为 0x0000，寄存器数量为 1，返回 2 字节数据，每单位 0.1dB。
 *
 * 该模块必须已经用厂商配套的【噪声检测模块Modbus模式配置工具】预先配置为
 * ModbusRTU 模式（出厂默认可能是主动/被动模式，需先用配置工具切换，详见手册
 * 2.3 节），并记下配置好的从机地址与波特率，通过 noise_sensor_init() 传入。
 ****************************************************************************************************
 */
#ifndef __NOISE_SENSOR_H
#define __NOISE_SENSOR_H

#include <stdint.h>

/* 出厂默认地址为 1（手册 3.2.1 节示例均以地址 1 举例），若已用配置工具改过，
 * 需要在初始化时传入实际值 */
#define NOISE_SENSOR_DEFAULT_ADDRESS   1u

/* 单次请求的应答超时时间（毫秒）。模块内部测量周期约 400ms，但那是"多久刷新一次
 * 缓存值"，不是 Modbus 请求-应答的耗时——请求应答应远快于此，500ms 留有充分余量。 */
#define NOISE_SENSOR_TIMEOUT_MS        500u

typedef enum
{
    NOISE_SENSOR_PENDING = 0,   /* 尚在等待应答，需继续调用 noise_sensor_poll() */
    NOISE_SENSOR_OK,             /* 已取得有效读数 */
    NOISE_SENSOR_ERR_TIMEOUT,    /* 超时未收到应答 */
    NOISE_SENSOR_ERR_CRC,        /* 应答帧 CRC16 校验失败 */
    NOISE_SENSOR_ERR_FORMAT,     /* 应答帧格式不符合预期（地址/功能码/字节数不对） */
} noise_sensor_status_t;

/**
 * @brief   初始化（配置 USART3），需与噪声传感器实际配置好的波特率/地址一致
 */
void noise_sensor_init(uint32_t baudrate, uint8_t slave_address);

/**
 * @brief   发起一次读取请求（异步，非阻塞）：组装 Modbus 请求帧、计算 CRC16、
 *          通过 USART3 发出，并记录起始时间用于超时判断
 */
void noise_sensor_start_request(void);

/**
 * @brief   轮询是否已取得应答（需在 main 循环中反复调用，不阻塞）
 * @param   out_db  [出参] 解析出的声压级（dB），仅当返回值为 NOISE_SENSOR_OK 时有效
 * @retval  当前状态，PENDING 表示还需要继续调用本函数等待
 */
noise_sensor_status_t noise_sensor_poll(float *out_db);

/**
 * @brief   统计：CRC 校验失败/格式错误/超时的累计次数（用于观测链路质量）
 */
uint32_t noise_sensor_get_error_count(void);

#endif
