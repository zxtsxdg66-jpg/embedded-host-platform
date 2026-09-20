/**
 ****************************************************************************************************
 * @file        board_uart_msp.c
 ****************************************************************************************************
 */
#include "board_uart_msp.h"
#include "./SYSTEM/sys/sys.h"

void HAL_UART_MspInit(UART_HandleTypeDef *huart)
{
    GPIO_InitTypeDef gpio_init = {0};

    if (huart->Instance == USART1)
    {
        /* PA9(TX)/PA10(RX)，见 pc_link.c */
        __HAL_RCC_USART1_CLK_ENABLE();
        __HAL_RCC_GPIOA_CLK_ENABLE();

        gpio_init.Pin = GPIO_PIN_9;
        gpio_init.Mode = GPIO_MODE_AF_PP;
        gpio_init.Pull = GPIO_PULLUP;
        gpio_init.Speed = GPIO_SPEED_FREQ_HIGH;
        gpio_init.Alternate = GPIO_AF7_USART1;
        HAL_GPIO_Init(GPIOA, &gpio_init);

        gpio_init.Pin = GPIO_PIN_10;
        HAL_GPIO_Init(GPIOA, &gpio_init);

        HAL_NVIC_SetPriority(USART1_IRQn, 3, 3);
        HAL_NVIC_EnableIRQ(USART1_IRQn);
    }
    else if (huart->Instance == USART3)
    {
        /* PB10(TX)/PB11(RX)，见 noise_usart.c */
        __HAL_RCC_USART3_CLK_ENABLE();
        __HAL_RCC_GPIOB_CLK_ENABLE();

        gpio_init.Pin = GPIO_PIN_10;
        gpio_init.Mode = GPIO_MODE_AF_PP;
        gpio_init.Pull = GPIO_PULLUP;
        gpio_init.Speed = GPIO_SPEED_FREQ_HIGH;
        gpio_init.Alternate = GPIO_AF7_USART3;
        HAL_GPIO_Init(GPIOB, &gpio_init);

        gpio_init.Pin = GPIO_PIN_11;
        HAL_GPIO_Init(GPIOB, &gpio_init);

        /* 优先级低于 USART1（3,3）——PC 链路命令响应对时延更敏感，噪声传感器
         * 采用轮询等待、能容忍略高的中断延迟 */
        HAL_NVIC_SetPriority(USART3_IRQn, 4, 4);
        HAL_NVIC_EnableIRQ(USART3_IRQn);
    }
    else if (huart->Instance == USART2)
    {
        /* PA2(TX)/PA3(RX)，见 debug_log.c，仅用于调试日志输出，非本项目通信主链路 */
        __HAL_RCC_USART2_CLK_ENABLE();
        __HAL_RCC_GPIOA_CLK_ENABLE();

        gpio_init.Pin = GPIO_PIN_2;
        gpio_init.Mode = GPIO_MODE_AF_PP;
        gpio_init.Pull = GPIO_PULLUP;
        gpio_init.Speed = GPIO_SPEED_FREQ_HIGH;
        gpio_init.Alternate = GPIO_AF7_USART2;
        HAL_GPIO_Init(GPIOA, &gpio_init);

        gpio_init.Pin = GPIO_PIN_3;
        HAL_GPIO_Init(GPIOA, &gpio_init);

        /* 调试日志不使用中断收发（本项目不需要从调试口接收数据），因此不使能 NVIC */
    }
}
