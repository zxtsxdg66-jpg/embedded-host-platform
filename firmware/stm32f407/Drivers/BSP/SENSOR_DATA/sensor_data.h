/**
 ****************************************************************************************************
 * @file        sensor_data.h
 * @brief       统一的传感器数据结构，供 main.c 的采集/上报状态机在温湿度、噪声两个
 *              驱动模块（返回值类型不同：aht20_status_t / noise_sensor_status_t）
 *              之间传递数据时使用统一的"某通道读数是否有效"表达方式，不需要 main.c
 *              分别记住每个驱动各自的错误码含义。
 *
 * 三个 channel 名称字符串（"temperature"/"humidity"/"noise"）与 PC 端
 * src/device/sensors/channels.py 的 TEMPERATURE_CHANNEL/HUMIDITY_CHANNEL/
 * NOISE_CHANNEL 常量完全一致，见 pc_report.c 组帧时的实际引用处。
 ****************************************************************************************************
 */
#ifndef __SENSOR_DATA_H
#define __SENSOR_DATA_H

#include <stdint.h>

typedef struct
{
    uint8_t valid;    /* 1=本次读数有效可上报，0=本次读数无效（超时/CRC失败/总线异常等） */
    float value;
} sensor_reading_t;

typedef struct
{
    sensor_reading_t temperature;   /* 摄氏度 */
    sensor_reading_t humidity;      /* 相对湿度 % */
    sensor_reading_t noise;         /* 声压级 dB */
} sensor_data_t;

#endif
