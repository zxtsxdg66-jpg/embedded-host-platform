/**
 ****************************************************************************************************
 * @file        soft_i2c.h
 * @brief       软件模拟 I2C（GPIO 位翻转），供 AHT20 温湿度传感器使用。
 *
 * 引脚选择说明（对应 docs/hardware.md D.2/D.5 节
 * "待确认"项的选定结果）：SDA=PE0，SCL=PE1。选择依据——《探索者V3硬件参考手册》
 * 引脚分配表明确将 PE0/PE1 标注为 "FSMC_NBL0"/"FSMC_NBL1"、"SRAM 专用"、
 * 共用标记为 "N"。
 *
 * 【2026-09-07 更新】本模块最初的理由是"本项目从不调用 FSMC 初始化函数"，该前提
 * 在引入板载 2.8 寸 TFT LCD（走 FSMC）之后已经不再成立，因此重新核查并改用更强的
 * 依据——不是"FSMC 没被初始化"，而是"FSMC 被初始化了也不会碰这两个脚"：
 *   1) 厂商 LCD 驱动的 HAL_SRAM_MspInit()（Drivers/BSP/LCD/lcd.c）只把
 *      GPIOD 的 0/1/8/9/10/14/15 与 GPIOE 的 7~15 配成 FSMC 复用，**逐个引脚列举，
 *      不含 PE0/PE1**；lcd_init() 另行配置的 CS/WR/RD/RS/BL 也都不在 PE0/PE1 上。
 *   2) PE0/PE1 是 FSMC_NBL0/NBL1（字节通道选通），只有按字节访问外部 SRAM 时才需要；
 *      LCD 走的是 16 位 NOR/PSRAM 时序，整字读写，用不到字节选通。
 * 结论不变：PE0/PE1 在本项目中始终是普通 GPIO，可以安全复用为软件 I2C；但结论的
 * 依据已从"我们不用 FSMC"换成了"用了 FSMC 也不影响"，后者不会再被功能扩展推翻。
 * 之所以不用板载硬件 I2C1（PB8/PB9），是因为该总线已经被 24C02 EEPROM、
 * ST480MC 磁力计、ES8388 音频编解码器共用，手册原话"我们并不提倡使用硬件IIC，
 * 因为STM32的IIC是鸡肋"，且 ATK-MB016 官方驱动本身也是用软件 I2C 实现的
 * （myiic.c），本模块沿用同样的技术路线。
 *
 * 【已实机确认】PE0/PE1 作为软件 I2C 于 2026-08-16 起随 AHT20 一同实机验证通过，
 * 2026-08-19 完成三通道 1 小时连续运行零错误。**但插上 LCD 之后的共存尚未实测**：
 * 上面第 1、2 条是对厂商驱动源码与 FSMC 时序的静态核查，不是实测结论；接屏后
 * 第一次上电应先确认 AHT20 仍能正常读数。若真出现干扰，只需改本文件的引脚宏
 * 定义即可切换，不影响其它模块。
 ****************************************************************************************************
 */
#ifndef __SOFT_I2C_H
#define __SOFT_I2C_H

#include <stdint.h>

void soft_i2c_init(void);

/**
 * @brief   发送 START 信号
 */
void soft_i2c_start(void);

/**
 * @brief   发送 STOP 信号
 */
void soft_i2c_stop(void);

/**
 * @brief   发送一个字节，返回是否收到从机 ACK
 * @retval  1=收到 ACK，0=未收到（NACK 或总线异常）
 */
uint8_t soft_i2c_send_byte(uint8_t data);

/**
 * @brief   读取一个字节
 * @param   ack  读取完成后是否由主机发送 ACK（1=ACK，继续读下一字节；0=NACK，本次是最后一字节）
 */
uint8_t soft_i2c_read_byte(uint8_t ack);

#endif
