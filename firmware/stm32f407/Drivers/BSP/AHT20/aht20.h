/**
 ****************************************************************************************************
 * @file        aht20.h
 * @brief       AHT20 温湿度传感器驱动（ATK-MB016 模块），基于软件 I2C（soft_i2c.c）。
 *
 * 通信流程与寄存器/命令取值均直接引自《AHT20说明书》第 5 节"传感器通讯"与官方驱动
 * 参考源码 atk_aht20.c/.h（docs/08_YINGJIAN/【正点原子】温湿度传感器模块（ATK-MB016）/
 * 3，程序源码/），未凭型号猜测：
 *   - I2C 地址（8 位，已含方向位）：写 0x70 / 读 0x71，取自官方驱动 atk_aht20.h
 *     宏定义 ATK_AHT20_IIC_ADDR = 0x70（读时 |0x01）
 *   - 初始化命令：地址(写) + 0xBE + 0x08 + 0x00，取自官方驱动 atk_aht20.h 的
 *     INIT 宏定义（0xBE）及 atk_aht20_init() 中固定的两个参数字节 {0x08, 0x00}
 *   - 测量命令：地址(写) + 0xAC + 0x33 + 0x00，取自官方驱动 START_TEST 宏定义
 *     （0xAC）及 atk_aht20_read_data() 中固定的两个参数字节 {0x33, 0x00}，
 *     与 AHT20 说明书 5.2 节"发送写测量命令 0x70 0xAC 0x33 0x00"完全一致
 *   - 读回 7 字节：状态字(1B) + 湿度20bit(跨3字节) + 温度20bit(跨3字节，与湿度共用
 *     中间一个字节的高低nibble) + CRC8(1B)
 *   - 温湿度换算公式与 CRC8 多项式（X8+X5+X4+1，即 0x31，初始值 0xFF）均取自
 *     《AHT20说明书》5.2/5.3 节
 *
 * 与官方 Demo（atk_aht20.c）的差异：官方 Demo 未做 CRC8 校验，本驱动补充了这一步——
 * 呼应第一版正式固件"异常帧/CRC 处理"的要求，读回数据但 CRC 不通过时应判定为
 * 一次无效读数，而不是把可能损坏的数据当作真实温湿度上报给 PC。
 ****************************************************************************************************
 */
#ifndef __AHT20_H
#define __AHT20_H

#include <stdint.h>

typedef enum
{
    AHT20_OK = 0,
    AHT20_ERR_NACK,        /* I2C 总线上未收到从机 ACK（未接线/未上电/地址错） */
    AHT20_ERR_CRC,          /* 读回数据 CRC8 校验失败 */
} aht20_status_t;

/**
 * @brief   初始化 AHT20（含软件 I2C 引脚初始化 + 传感器初始化命令）
 * @retval  AHT20_OK 或 AHT20_ERR_NACK
 */
aht20_status_t aht20_init(void);

/**
 * @brief   读取一次温湿度（阻塞式，内部包含 AHT20 所需的测量延时，总耗时约 80ms+，
 *          与 AHT20 说明书 5.2 节"传感器读取流程"一致；调用方需自行控制采样周期，
 *          说明书建议 采集数据周期应大于 1 秒/1 次）
 * @param   temperature  [出参] 摄氏度
 * @param   humidity     [出参] 相对湿度百分比
 * @retval  AHT20_OK / AHT20_ERR_NACK / AHT20_ERR_CRC
 */
aht20_status_t aht20_read(float *temperature, float *humidity);

#endif
