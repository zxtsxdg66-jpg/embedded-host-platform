/**
 ****************************************************************************************************
 * @file        debug_log.h
 * @brief       调试日志接口，运行在 USART2（PA2=TX/PA3=RX，对应开发板 RS232 COM2
 *              接口），与 USART1（PC 二进制协议）、USART3（噪声传感器 Modbus）完全
 *              独立，互不干扰。
 *
 * 用法：接一根 USB 转 TTL（或 RS232）线到开发板 COM2/P4 排针（3.3V TTL 侧），用任意
 * 串口调试助手以 115200 8N1 打开，即可看到固件运行时的调试文本，不影响 PC 端二进制
 * 协议链路。若不接调试线，本模块的发送调用会正常返回（阻塞发送有 1 秒超时保护），
 * 不会导致固件卡死。
 *
 * 仅用于开发调试，不是 STM32<->PC 正式协议的一部分，PC 端代码不需要、也不会解析
 * 这路输出。
 ****************************************************************************************************
 */
#ifndef __DEBUG_LOG_H
#define __DEBUG_LOG_H

#include <stdint.h>

#define DEBUG_LOG_DEFAULT_BAUDRATE   115200u

/**
 * @brief   是否编译进调试日志功能。设为 0 时下面的 debug_log_printf 会被预处理器
 *          替换为空操作，不占用 USART2 资源、不影响 Flash/RAM 占用，用于第一版
 *          正式固件如果需要"去掉调试口"时的一键开关，不需要逐处删代码
 */
#define DEBUG_LOG_ENABLED   1

void debug_log_init(uint32_t baudrate);

#if DEBUG_LOG_ENABLED
void debug_log_printf(const char *fmt, ...);
#else
#define debug_log_printf(...)   do { } while (0)
#endif

#endif
