/**
 ****************************************************************************************************
 * @file        fan.h
 * @brief       小风扇模块 ATK-MB023 驱动 —— 通风执行器。
 *
 * 依据《ATK-MB023 小风扇模块用户手册 V1.0》：模块驱动芯片为 SS6285L，4 脚接口
 * VCC(3.3~5V) / GND / FI(前进输入) / BI(后退输入)，电机接在芯片的 FO/BO 输出端。
 *
 * 本项目只需要单向送风（温湿度超过通风阈值就吹风，恢复后停），**不需要反转、
 * 也不需要调速**，因此没有采用厂商例程那套「定时器互补 PWM」方案：
 *   - 官方例程用 TIM1_CH1 + CH1N 输出互补 PWM，目的是支持正反转与调速；
 *   - 本项目直接用两个普通 GPIO：FI 拉高即全速正转、拉低即停，BI 恒为低。
 * 这样省掉一路定时器通道，选脚也自由得多（探索者V3 上官方例程用的 PA8/PB13
 * 分别被摄像头 XCLK/红外接收头 和 ES8388 的 SCLK 占用）。
 *
 * ⚠ 安全约束：SS6285L 的 FI 与 BI **绝不能同时为高**（那是刹车/直通状态）。
 * 本驱动通过「BI 恒低、只切换 FI」从结构上排除这种情况，调用方无需关心。
 *
 * 引脚选择依据（见 docs/hardware.md）：
 * PE5/PE6 在《探索者V3 硬件参考手册》表 1.2.2.1 中标注为"可做独立 IO"(Y)，
 * 仅连接到 OLED/CAMERA 接口的 D6/D7，而本项目不接摄像头；且与 LCD 占用的
 * PE7~PE15 不重叠，与 AHT20 软件 I2C 占用的 PE0/PE1 也不重叠。
 ****************************************************************************************************
 */
#ifndef __FAN_H
#define __FAN_H

/* 引脚宏里用到 GPIOE / GPIO_PIN_x / __HAL_RCC_GPIOE_CLK_ENABLE，因此这里直接包含
 * sys.h（与 led.h 的做法一致），使本头文件自包含，不依赖调用方的包含顺序。 */
#include "./SYSTEM/sys/sys.h"
#include <stdint.h>

/******************************************************************************************/
/* 引脚定义 */

/* FI：前进输入。由 TIM9_CH1 输出 PWM 调速（2026-09-08 由普通 GPIO 改为 PWM，
 * 原因见下方 FAN_DEFAULT_DUTY_PERCENT 的说明）。 */
#define FAN_FI_GPIO_PORT                GPIOE
#define FAN_FI_GPIO_PIN                 GPIO_PIN_5
#define FAN_FI_GPIO_AF                  GPIO_AF3_TIM9
#define FAN_FI_GPIO_CLK_ENABLE()        do{ __HAL_RCC_GPIOE_CLK_ENABLE(); }while(0)

/* PE5 在 STM32F407 上的 AF3 就是 TIM9_CH1，所以改用 PWM **不需要动任何接线**。
 * TIM9 全项目未被占用（此前唯一提及是本文件里"为什么不用 TIM1"那段注释）。 */
#define FAN_PWM_TIMX                    TIM9
#define FAN_PWM_CHANNEL                 TIM_CHANNEL_1
#define FAN_PWM_CLK_ENABLE()            do{ __HAL_RCC_TIM9_CLK_ENABLE(); }while(0)

/* PWM 频率 20kHz：高于人耳上限，电机不会发出可闻的啸叫。
 * TIM9 挂在 APB2，定时器时钟 168MHz，168000000 / 8400 = 20000Hz。 */
#define FAN_PWM_PERIOD                  8399u

/* BI：后退输入。本项目不使用反转，初始化后恒为低 */
#define FAN_BI_GPIO_PORT                GPIOE
#define FAN_BI_GPIO_PIN                 GPIO_PIN_6
#define FAN_BI_GPIO_CLK_ENABLE()        do{ __HAL_RCC_GPIOE_CLK_ENABLE(); }while(0)

/******************************************************************************************/
/* 外部接口函数 */

/**
 * @brief       初始化风扇控制引脚，并确保风扇处于停止状态
 * @note        上电即停：与 PC 端 application/fan_dispatcher.py 中
 *              「applied_state 初值为 False（假定固件上电时风扇是停的）」
 *              这一假设相对应，两边必须一致，否则上位机会以为风扇已停、
 *              而实际仍在转。
 */
void fan_init(void);

/* 默认占空比。
 *
 * 【2026-09-08 实机反馈】原实现把 FI 直接拉高 = 100% 全速，实测**转速过高，
 * 且持续运行一段时间后驱动可能进入过热保护**。地铁站环境监测这个场景需要的是
 * 持续换气而不是最大风量，全速既没必要也不可持续，因此改为 PWM 调速。
 *
 * 60% 是"够用且能可靠启动"的折中：直流电机的启动转矩需求高于运行时，占空比压太低
 * 会出现通电不转。即便如此，fan_set() 仍会先给一段满占空比的启动脉冲（见其实现）。
 * 若实机仍偏快，把这个数字调小即可；若出现通电不转，调大或延长启动脉冲。 */
#define FAN_DEFAULT_DUTY_PERCENT        60u

/* 启动脉冲：先满占空比转多久，再落到设定占空比。 */
#define FAN_KICKSTART_MS                150u

/**
 * @brief       设置风扇运行状态
 * @param       on : 非 0 = 按当前占空比转，0 = 停
 * @note        启动时会阻塞 FAN_KICKSTART_MS（约 150ms）输出满占空比启动脉冲。
 *              这点阻塞可以接受：风扇启停只在阈值穿越时发生，频率远低于每个采集
 *              周期都要阻塞 80~100ms 的 AHT20 读取。
 */
void fan_set(uint8_t on);

/**
 * @brief       设置风扇占空比（1~100）
 * @param       percent : 占空比百分比，会被钳到 1~100
 * @note        立即生效；风扇停止时只记录，下次启动时采用。
 */
void fan_set_duty(uint8_t percent);

/**
 * @brief       查询当前占空比设定
 */
uint8_t fan_get_duty(void);

/**
 * @brief       查询风扇当前状态
 * @retval      1 = 正在转，0 = 已停止
 */
uint8_t fan_is_running(void);

#endif
