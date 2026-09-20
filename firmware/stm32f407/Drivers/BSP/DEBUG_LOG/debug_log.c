/**
 ****************************************************************************************************
 * @file        debug_log.c
 ****************************************************************************************************
 */
#include "debug_log.h"
#include "./SYSTEM/sys/sys.h"
#include <stdio.h>
#include <stdarg.h>

#if DEBUG_LOG_ENABLED

#define DEBUG_LOG_BUF_SIZE   128u

static UART_HandleTypeDef s_debug_uart_handle;
static uint8_t s_debug_uart_ready = 0u;

void debug_log_init(uint32_t baudrate)
{
    s_debug_uart_ready = 0u;
    s_debug_uart_handle.Instance = USART2;
    s_debug_uart_handle.Init.BaudRate = baudrate;
    s_debug_uart_handle.Init.WordLength = UART_WORDLENGTH_8B;
    s_debug_uart_handle.Init.StopBits = UART_STOPBITS_1;
    s_debug_uart_handle.Init.Parity = UART_PARITY_NONE;
    s_debug_uart_handle.Init.HwFlowCtl = UART_HWCONTROL_NONE;
    s_debug_uart_handle.Init.Mode = UART_MODE_TX_RX;
    HAL_UART_Init(&s_debug_uart_handle);   /* MspInit 由 board_uart_msp.c 统一处理 */
    s_debug_uart_ready = 1u;
}

void debug_log_printf(const char *fmt, ...)
{
    char buf[DEBUG_LOG_BUF_SIZE];
    va_list args;
    int len;

    va_start(args, fmt);
    len = vsnprintf(buf, sizeof(buf), fmt, args);
    va_end(args);

    if (len > 0)
    {
        if ((size_t)len >= sizeof(buf))
        {
            len = (int)sizeof(buf) - 1;   /* 被截断，仍发送已格式化的部分 */
        }
        HAL_UART_Transmit(&s_debug_uart_handle, (uint8_t *)buf, (uint16_t)len, 1000u);
    }
}

#else

void debug_log_init(uint32_t baudrate)
{
    (void)baudrate;
}

#endif /* DEBUG_LOG_ENABLED */

/* ---------------------------------------------------------------------------
 * 标准输出重定向
 *
 * 为什么必须有这段：厂商的 LCD 驱动在 lcd_init() 末尾有一句
 *     printf("LCD ID:%x\r\n", lcddev.id);
 * （lcd.c 里那句注释"会卡死在 printf"说的就是这件事）。本工程没有启用 MicroLIB
 * （.uvprojx 里 useUlib=0），ARM Compiler 5 的完整 C 库在没有重定向时会用**半主机**
 * （semihosting）实现 printf——半主机靠调试器接管 SVC 指令来完成 I/O，脱机运行
 * （烧录后拔掉调试器直接上电）时那条 SVC 无人应答，程序当场停住。
 *
 * 所以这里做两件事：声明 __use_no_semihosting 断掉半主机依赖，并把 fputc 接到
 * USART2 的调试串口上。顺带的好处是厂商那句 "LCD ID:9341" 会真的打印出来，
 * 屏幕不显示时可以据此判断到底是没检出屏、还是检出了但没画上去。
 *
 * 放在 DEBUG_LOG_ENABLED 之外：即使关掉调试日志，printf 的重定向也必须存在，
 * 否则半主机依赖仍在。日志关闭时 fputc 直接丢弃字符。
 * ------------------------------------------------------------------------- */
#if defined(__CC_ARM)

#pragma import(__use_no_semihosting)

struct __FILE
{
    int handle;
};

FILE __stdout;

void _sys_exit(int x)
{
    (void)x;

    while (1)
    {
        /* 标准库要求这个函数不返回 */
    }
}

char *_sys_command_string(char *cmd, int len)
{
    (void)len;
    return cmd;
}

int fputc(int ch, FILE *f)
{
    (void)f;

#if DEBUG_LOG_ENABLED
    if (s_debug_uart_ready != 0u)
    {
        uint8_t byte = (uint8_t)ch;
        HAL_UART_Transmit(&s_debug_uart_handle, &byte, 1u, 100u);
    }
#endif

    /* 串口尚未初始化、或调试日志被关闭时静默丢弃：printf 不应该成为启动顺序的
     * 约束条件，更不该在这里阻塞。 */
    return ch;
}

#endif /* __CC_ARM */
