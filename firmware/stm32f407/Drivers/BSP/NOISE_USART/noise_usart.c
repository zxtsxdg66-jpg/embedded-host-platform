/**
 ****************************************************************************************************
 * @file        noise_usart.c
 ****************************************************************************************************
 */
#include "noise_usart.h"
#include "./SYSTEM/sys/sys.h"

#define NOISE_USART_RX_CAPACITY   64u   /* Modbus 响应最长约几十字节，留有余量 */

static UART_HandleTypeDef s_noise_uart_handle;

static uint8_t s_rx_buf[NOISE_USART_RX_CAPACITY];
static volatile uint16_t s_rx_len = 0;
static volatile uint8_t s_frame_ready = 0;
static volatile uint8_t s_rx_overflow = 0;   /* 缓冲区溢出标志，供调试观测 */

void noise_usart_init(uint32_t baudrate)
{
    s_rx_len = 0;
    s_frame_ready = 0;
    s_rx_overflow = 0;

    s_noise_uart_handle.Instance = USART3;
    s_noise_uart_handle.Init.BaudRate = baudrate;
    s_noise_uart_handle.Init.WordLength = UART_WORDLENGTH_8B;
    s_noise_uart_handle.Init.StopBits = UART_STOPBITS_1;
    s_noise_uart_handle.Init.Parity = UART_PARITY_NONE;
    s_noise_uart_handle.Init.HwFlowCtl = UART_HWCONTROL_NONE;
    s_noise_uart_handle.Init.Mode = UART_MODE_TX_RX;
    HAL_UART_Init(&s_noise_uart_handle);   /* 内部会回调 HAL_UART_MspInit() 配置 PB10/PB11 + NVIC */

    /* 不使用 HAL_UART_Receive_IT，直接使能 RXNE/IDLE 中断，由 USART3_IRQHandler
     * 手动读寄存器处理，见文件头说明 */
    __HAL_UART_ENABLE_IT(&s_noise_uart_handle, UART_IT_RXNE);
    __HAL_UART_ENABLE_IT(&s_noise_uart_handle, UART_IT_IDLE);
}

void noise_usart_send(const uint8_t *data, uint16_t length)
{
    HAL_UART_Transmit(&s_noise_uart_handle, (uint8_t *)data, length, 1000u);
}

uint8_t noise_usart_frame_ready(void)
{
    return s_frame_ready;
}

const uint8_t *noise_usart_take_frame(uint16_t *out_len)
{
    *out_len = s_rx_len;
    s_frame_ready = 0u;
    s_rx_len = 0u;
    return s_rx_buf;
}

void noise_usart_reset_rx(void)
{
    s_rx_len = 0u;
    s_frame_ready = 0u;
    s_rx_overflow = 0u;
}

/**
 * @brief   USART3 中断服务函数——直接处理 RXNE（收字节）与 IDLE（一帧结束）两个
 *          标志位，不调用 HAL_UART_IRQHandler()
 */
void USART3_IRQHandler(void)
{
    /* RXNE：收到一个新字节。读 DR 会自动清除 RXNE 标志。 */
    if (__HAL_UART_GET_FLAG(&s_noise_uart_handle, UART_FLAG_RXNE))
    {
        uint8_t byte = (uint8_t)(s_noise_uart_handle.Instance->DR & 0xFFu);

        if (s_frame_ready)
        {
            /* 上一帧还没被取走，新字节属于"下一帧"的开头，暂不丢弃硬件已收到的
             * 字节，但也不再写入缓冲区，避免覆盖尚未处理的数据；调用方应尽快
             * 通过 noise_usart_take_frame() 取走数据 */
        }
        else if (s_rx_len < NOISE_USART_RX_CAPACITY)
        {
            s_rx_buf[s_rx_len++] = byte;
        }
        else
        {
            s_rx_overflow = 1u;   /* 单帧超出缓冲区容量，视为异常数据 */
        }
    }

    /* IDLE：总线空闲（收完一帧的静默期），标准 Modbus RTU 帧结束判定方式。
     * 清除 IDLE 标志需要"先读 SR 再读 DR"的固定序列（STM32F4 参考手册规定）。 */
    if (__HAL_UART_GET_FLAG(&s_noise_uart_handle, UART_FLAG_IDLE))
    {
        volatile uint32_t tmp;
        tmp = s_noise_uart_handle.Instance->SR;
        tmp = s_noise_uart_handle.Instance->DR;
        (void)tmp;

        if (s_rx_len > 0u && !s_frame_ready)
        {
            s_frame_ready = 1u;
        }
    }
}
