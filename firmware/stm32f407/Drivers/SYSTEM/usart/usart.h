/**
 ****************************************************************************************************
 * @file        usart.h
 * @brief       兼容垫片：让厂商驱动里的 #include "./SYSTEM/usart/usart.h" 能编译通过。
 *
 * 本项目**没有**沿用厂商的 SYSTEM/usart 模块——USART1 由 Drivers/BSP/PC_LINK 接管
 * （与上位机的二进制协议链路），USART2 由 Drivers/BSP/DEBUG_LOG 接管（调试日志），
 * 两者都有自己的初始化与收发实现，与厂商那份基于全局缓冲区 + 行结束符的实现不兼容。
 *
 * 但原样引入的厂商驱动（LCD、TOUCH/gt9xxx、TOUCH/ft5206）里有 #include 这个路径的语句，
 * 它们真正需要的只是 printf 的声明。既然要保持"厂商文件一字不改"这条纪律
 * （见 docs/09_STM32Hardware/STM32F407_硬件落地方案.md），就不去删它们的 include，
 * 而是在这里提供一个只拉 <stdio.h> 的垫片。
 *
 * printf 本身的重定向在 Drivers/BSP/DEBUG_LOG/debug_log.c —— 那里声明了
 * __use_no_semihosting 并把 fputc 接到 USART2，否则厂商 lcd_init() 末尾那句
 * printf 会走 ARM 半主机，脱机上电时直接卡死。
 *
 * 刻意**不**提供厂商 usart.h 里的 USART_UX / g_uart1_handle / g_usart_rx_buf 等符号：
 * 谁要是真的用到了它们，就应该在编译期报错并改用 PC_LINK/DEBUG_LOG，而不是
 * 悄悄链到一份平行的串口实现上。
 ****************************************************************************************************
 */
#ifndef __USART_H
#define __USART_H

#include <stdio.h>

#endif /* __USART_H */
